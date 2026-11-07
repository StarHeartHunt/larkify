"""Snapshot the Feishu open platform metadata into ``schema/``.

Three public documentation endpoints describe the server-side API surface:

``/api/tools/server-side-api/list``
    Catalog of every API (method, path, project, version, resource, name).
``/api_explorer/v1/api_definition``
    Machine readable definition: tokens, pagination, upload / download flags,
    typed request and response trees.
``/document_portal/v1/document/get_detail``
    The rendered document: better descriptions, reliable ``required`` flags and
    enum options, and scopes. Events are only available here, as Markdown.

Snapshots are resumable: anything already on disk is skipped unless
``--refresh`` is given.
"""

import argparse
import asyncio
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote, urlencode

import httpx2

BASE_URL = "https://open.feishu.cn"
API_LIST = "/api/tools/server-side-api/list"
EVENT_LIST = "/api/tools/server-side-event/list"
API_DEFINITION = "/api_explorer/v1/api_definition"
DOCUMENT_DETAIL = "/document_portal/v1/document/get_detail"

SCHEMA_DIR = Path(__file__).parent.parent / "schema"

# Keep the crawl gentle: this is a public documentation site.
CONCURRENCY = 4
MAX_ATTEMPTS = 5

# Long prose that the generator never reads. Dropped to keep the snapshot small.
DROPPED_API_KEYS = (
    "requestBeforeContent",
    "responseBeforeContent",
    "requiredScopesEndingContent",
    "endingContent",
)


def slug(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", value).strip("_") or "_"


def api_file(meta: dict[str, Any]) -> Path:
    return (
        SCHEMA_DIR
        / "apis"
        / meta["Project"]
        / meta["Version"]
        / f"{slug(meta['Resource'])}.{slug(meta['Name'])}.json"
    )


def event_file(item: dict[str, Any]) -> Path:
    return SCHEMA_DIR / "events" / f"{slug(item['url'])}.json"


def dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )


async def get_json(
    client: httpx2.AsyncClient, url: str, semaphore: asyncio.Semaphore
) -> dict[str, Any]:
    delay = 1.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            async with semaphore:
                response = await client.get(url)
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx2.HTTPStatusError(
                    "retryable status", request=response.request, response=response
                )
            return response.json()
        except (httpx2.TransportError, httpx2.HTTPStatusError, ValueError):
            if attempt == MAX_ATTEMPTS:
                raise
            await asyncio.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")


def strip_detail(payload: dict[str, Any], keep_content: bool) -> dict[str, Any]:
    data = payload.get("data") or {}
    schema = data.get("schema") or {}
    api_schema = dict(schema.get("apiSchema") or {})
    for key in DROPPED_API_KEYS:
        api_schema.pop(key, None)
    result: dict[str, Any] = {
        "code": payload.get("code"),
        "name": data.get("name"),
        "title": schema.get("title"),
        "description": schema.get("description"),
        "redirectUri": data.get("redirectUri"),
        "apiSchema": api_schema or None,
    }
    if keep_content or not api_schema:
        result["content"] = data.get("content")
    return result


async def fetch_api(
    client: httpx2.AsyncClient,
    semaphore: asyncio.Semaphore,
    item: dict[str, Any],
    refresh: bool,
) -> str:
    target = api_file(item["meta"])
    if target.exists() and not refresh:
        return "skipped"

    meta = item["meta"]
    definition: dict[str, Any] = {}
    if meta["Version"] != "old":
        query = urlencode(
            {
                "project": meta["Project"],
                "version": meta["Version"],
                "resource": meta["Resource"],
                "apiName": meta["Name"],
            }
        )
        definition = await get_json(client, f"{API_DEFINITION}?{query}", semaphore)

    full_path = item["fullPath"].removeprefix("/document")
    detail = await get_json(
        client, f"{DOCUMENT_DETAIL}?fullPath={quote(full_path)}", semaphore
    )
    dump(
        target,
        {
            "catalog": item,
            "definition": definition.get("data") or None,
            "definition_code": definition.get("code"),
            "detail": strip_detail(detail, keep_content=False),
        },
    )
    return "fetched"


async def fetch_event(
    client: httpx2.AsyncClient,
    semaphore: asyncio.Semaphore,
    item: dict[str, Any],
    refresh: bool,
) -> str:
    target = event_file(item)
    if target.exists() and not refresh:
        return "skipped"

    full_path = item["fullPath"].removeprefix("/document")
    detail = await get_json(
        client, f"{DOCUMENT_DETAIL}?fullPath={quote(full_path)}", semaphore
    )
    dump(target, {"catalog": item, "detail": strip_detail(detail, keep_content=True)})
    return "fetched"


async def run(refresh: bool) -> None:
    semaphore = asyncio.Semaphore(CONCURRENCY)
    headers = {"User-Agent": "feishu-kit-codegen"}
    timeout = httpx2.Timeout(30.0)
    async with httpx2.AsyncClient(
        base_url=BASE_URL, headers=headers, timeout=timeout, follow_redirects=True
    ) as client:
        apis = (await get_json(client, API_LIST, semaphore))["data"]
        events = (await get_json(client, EVENT_LIST, semaphore))["data"]
        dump(
            SCHEMA_DIR / "catalog.json",
            {
                "apis": apis["apis"],
                "events": events["events"],
                "bizInfos": apis["bizInfos"],
            },
        )

        jobs = [fetch_api(client, semaphore, a, refresh) for a in apis["apis"]]
        jobs += [fetch_event(client, semaphore, e, refresh) for e in events["events"]]

        done = failed = 0
        for job in asyncio.as_completed(jobs):
            try:
                await job
            except Exception as e:  # keep going, a re-run picks up what failed
                failed += 1
                print(f"failed: {e!r}", flush=True)
            done += 1
            if done % 200 == 0:
                print(f"{done}/{len(jobs)} done, {failed} failed", flush=True)
        print(f"finished: {done}/{len(jobs)} done, {failed} failed", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh", action="store_true", help="refetch documents already on disk"
    )
    args = parser.parse_args()
    asyncio.run(run(args.refresh))


if __name__ == "__main__":
    main()
