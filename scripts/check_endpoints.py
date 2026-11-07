"""Call every generated method and compare the request against the metadata.

Templates are exercised by a handful of unit tests. This goes over all of them,
sync and async, so that nothing is left to run for the first time in production.
"""

import asyncio
from collections import Counter
import inspect
import json
from pathlib import Path
import re
import sys
from typing import Any

import httpx2

from feishukit import Feishu, TokenAuthStrategy
from feishukit.rest._base import BaseClient

SCHEMA = Path("schema/apis")
METHOD_NAMES = {"get", "post", "put", "patch", "delete"}


def expected_requests() -> dict[str, dict[str, Any]]:
    expected: dict[str, dict[str, Any]] = {}
    for path in SCHEMA.glob("*/*/*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        definition = document["definition"]
        if definition:
            method, route = definition["httpMethod"], definition["apiPath"]
            tokens = definition.get("accessTokens") or []
            query = (definition.get("request") or {}).get("query") or {}
            required = [
                p["name"] for p in query.get("properties") or [] if p.get("required")
            ]
        else:
            method, _, route = document["catalog"]["url"].partition(":")
            tokens, required = None, []
        key = f"{method} {re.sub(r':[A-Za-z_][A-Za-z0-9_]*', ':p', route)}"
        expected[key] = {"tokens": tokens, "required": required}
    return expected


def walk(client: Any, path: str = "rest"):
    """Yield every endpoint method of a generated client."""
    for name in dir(type(client)):
        attribute = getattr(type(client), name)
        if name.startswith("_") or name in ("paginate", "paginate_with"):
            continue
        if hasattr(attribute, "__set_name__") and hasattr(attribute, "func"):
            child = getattr(client, name)
            if isinstance(child, BaseClient):
                yield from walk(child, f"{path}.{name}")
        elif inspect.isfunction(attribute) and not name.startswith("async_"):
            yield (
                f"{path}.{name}",
                getattr(client, name),
                getattr(client, f"async_{name}"),
            )


def arguments(method: Any) -> tuple[list[str], dict[str, Any]]:
    positional, keyword = [], {}
    for name, parameter in inspect.signature(method).parameters.items():
        if parameter.kind == parameter.POSITIONAL_OR_KEYWORD:
            positional.append(f"value-{name}")
        elif (
            parameter.kind == parameter.KEYWORD_ONLY
            and parameter.default is parameter.empty
        ):
            annotation = str(parameter.annotation)
            if "Sequence" in annotation:
                keyword[name] = ["x"]
            elif "int" in annotation.replace("Literal", "") and "str" not in annotation:
                keyword[name] = 1
            elif annotation.startswith("bool"):
                keyword[name] = True
            else:
                keyword[name] = "x"
    return positional, keyword


def main() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"code": 0, "msg": "", "data": {}})

    transport = httpx2.MockTransport(handler)
    feishu = Feishu(
        TokenAuthStrategy("t-test"),
        transport=transport,
        async_transport=transport,
        auto_retry=False,
        # Bodies are covered by the example replay.
        rest_api_validate_body=False,
    )

    expected = expected_requests()
    stats: Counter[str] = Counter()
    problems: list[str] = []
    covered: set[str] = set()

    for name, sync_method, async_method in walk(feishu.rest):
        positional, keyword = arguments(sync_method)
        body = (
            {"data": {}} if "data" in inspect.signature(sync_method).parameters else {}
        )
        for variant, call in (("sync", sync_method), ("async", async_method)):
            seen.clear()
            try:
                if variant == "sync":
                    response = call(*positional, **keyword, **body)
                else:
                    response = asyncio.run(call(*positional, **keyword, **body))
                _ = response.parsed_data
            except Exception as e:
                stats["errors"] += 1
                problems.append(f"{name} {variant}: {e!r}"[:200])
                continue
            request = seen[0]
            stats["calls"] += 1

            route = request.url.path
            for value in positional:
                route = route.replace(value, ":p")
            key = f"{request.method} {route}"
            if key not in expected:
                stats["unexpected"] += 1
                problems.append(f"{name}: unexpected {key}")
                continue
            covered.add(key)
            for param in expected[key]["required"]:
                if param not in request.url.params:
                    stats["missing query"] += 1
                    problems.append(f"{name}: query {param} not sent")

            allowed = request.extensions.get("feishukit.token_types")
            tokens = expected[key]["tokens"]
            if tokens is None:
                if allowed is not None:
                    problems.append(f"{name}: legacy API restricts tokens")
            elif set(allowed) != set(tokens):
                stats["token mismatch"] += 1
                problems.append(f"{name}: tokens {allowed} != {tokens}")

    uncovered = sorted(set(expected) - covered)
    print(dict(stats), f"{len(covered)}/{len(expected)} endpoints covered")
    for line in uncovered[:20]:
        print("NOT COVERED", line)
    for line in problems[:30]:
        print(line)
    sys.exit(1 if problems or uncovered else 0)


if __name__ == "__main__":
    main()
