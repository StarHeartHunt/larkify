"""Compare the generated surface with a checkout of larksuite/oapi-sdk-python.

python scripts/check_official_sdk.py /path/to/oapi-sdk-python
"""

import json
from pathlib import Path
import re
import sys

METHOD = re.compile(r"\.http_method = HttpMethod\.(\w+)")
URI = re.compile(r'\.uri = \(?\s*"([^"]+)"')
TOKENS = re.compile(r"\.token_types = \{(.*?)\}", re.S)
TOKEN = re.compile(r"AccessTokenType\.(\w+)")
EVENT = re.compile(r"""[f'"]p2\.([a-z0-9_.]+)['"]""")


def route(method: str, path: str) -> tuple[str, str]:
    return method, re.sub(r":\w+", ":p", path.rstrip("/"))


def official_endpoints(root: Path) -> dict[tuple[str, str], set[str]]:
    found = {}
    for path in (root / "lark_oapi" / "api").glob("*/*/model/*_request.py"):
        source = path.read_text(encoding="utf-8")
        method, uri = METHOD.search(source), URI.search(source)
        if method is None or uri is None:
            continue
        tokens = TOKENS.search(source)
        found[route(method.group(1), uri.group(1))] = (
            {t.lower() for t in TOKEN.findall(tokens.group(1))} if tokens else set()
        )
    return found


def our_endpoints() -> dict[tuple[str, str], set[str] | None]:
    found: dict[tuple[str, str], set[str] | None] = {}
    for path in Path("schema/apis").glob("*/*/*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        definition = document["definition"]
        if definition:
            key = route(definition["httpMethod"], definition["apiPath"])
            found[key] = set(definition.get("accessTokens") or [])
        else:
            method, _, uri = document["catalog"]["url"].partition(":")
            found[route(method, uri)] = None
    return found


def main() -> None:
    root = Path(sys.argv[1])
    official, ours = official_endpoints(root), our_endpoints()

    missing = sorted(set(official) - set(ours))
    print(f"official SDK: {len(official)}, feishu-kit: {len(ours)}")
    print(f"common: {len(set(official) & set(ours))}")
    print(f"only in feishu-kit: {len(set(ours) - set(official))}")
    print(f"only in the official SDK: {len(missing)}")
    for key in missing:
        print("  ", *key)

    differing = [
        (key, ours[key], official[key])
        for key in set(official) & set(ours)
        if ours[key] is not None and ours[key] != official[key]
    ]
    print(f"token types differ: {len(differing)}")
    for key, mine, theirs in sorted(differing):
        print("  ", *key, sorted(mine or ()), "official:", sorted(theirs))

    from feishukit.webhooks import get_event_class

    source = (root / "lark_oapi/event/dispatcher_handler.py").read_text(
        encoding="utf-8"
    )
    events = sorted(set(EVENT.findall(source)))
    unknown = [e for e in events if get_event_class(e) is None]
    print(f"events in the official SDK: {len(events)}, without a model: {len(unknown)}")
    for event in unknown:
        print("  ", event)


if __name__ == "__main__":
    main()
