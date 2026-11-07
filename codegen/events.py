"""Build event models from the documents.

Events have no machine readable definition. V2 documents carry a table whose rows
state their nesting level, and most V1 documents only have a JSON sample.
"""

from collections import defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any

from .ir import EventDef, Model, Raw
from .naming import camel, snake
from .parser import (
    DOC_BASE,
    ModelRegistry,
    clean_text,
    load_example,
    reconcile,
    sorted_models,
)

SCHEMA_DIR = Path(__file__).parent.parent / "schema"

_SECTION = re.compile(r"^#{2,3} 事件体\s*$", re.M)
_NEXT_SECTION = re.compile(r"^#{2,3} ", re.M)
_ROW = re.compile(r'<md-dt-tr level="(\d+)">(.*?)</md-dt-tr>', re.S)
_NAME = re.compile(r'<md-text type="field-name"\s*>(.*?)</md-text>', re.S)
_TYPE = re.compile(r'<md-text type="field-type"\s*>(.*?)</md-text>', re.S)
_CELL = re.compile(r"<md-dt-td>(.*?)</md-dt-td>", re.S)
_SAMPLE = re.compile(r"<md-code-json>(.*?)</md-code-json>|```json\n(.*?)```", re.S)

_SCALARS = {
    "string": "str",
    "int": "int",
    "int64": "int",
    "number": "float",
    "float": "float",
    "boolean": "bool",
    "bool": "bool",
}


@dataclass
class Row:
    name: str
    type: str
    description: str
    children: list["Row"] = field(default_factory=list)


def parse_rows(content: str) -> list[Row]:
    """Read the event body table into a tree."""
    match = _SECTION.search(content)
    if match is None:
        return []
    following = _NEXT_SECTION.search(content, match.end())
    section = content[match.end() : following.start() if following else None]

    roots: list[Row] = []
    stack: list[tuple[int, Row]] = []
    for level_text, body in _ROW.findall(section):
        name = _NAME.search(body)
        type_ = _TYPE.search(body)
        cells = _CELL.findall(body)
        if name is None or type_ is None:
            continue
        row = Row(
            name.group(1).strip(),
            type_.group(1).replace("\\", "").strip(),
            clean_text(cells[2]) if len(cells) > 2 else "",
        )
        level = int(level_text)
        while stack and stack[-1][0] >= level:
            stack.pop()
        (stack[-1][1].children if stack else roots).append(row)
        stack.append((level, row))
    return roots


def row_to_raw(row: Row) -> Raw:
    base = row.type
    is_list = base.endswith("[]") or base == "list"
    base = base.removesuffix("[]")

    if row.children:
        ref = "" if base in ("-", "list", "object", "") else base
        inner = Raw(row.name, "object", ref=ref)
        inner.fields = [row_to_raw(child) for child in row.children]
    else:
        inner = Raw(row.name, _SCALARS.get(base, "any"))

    if is_list:
        return Raw(row.name, "list", description=row.description, item=inner)
    inner.description = row.description
    return inner


def value_to_raw(name: str, value: Any) -> Raw:
    """Infer a node from a sample value."""
    if isinstance(value, bool):
        return Raw(name, "bool")
    if isinstance(value, int):
        return Raw(name, "int")
    if isinstance(value, float):
        return Raw(name, "float")
    if isinstance(value, str):
        return Raw(name, "str")
    if isinstance(value, dict) and value:
        return Raw(
            name, "object", fields=[value_to_raw(k, v) for k, v in value.items()]
        )
    if isinstance(value, list) and value:
        return Raw(name, "list", item=value_to_raw(name, value[0]))
    return Raw(name, "any")


def event_sample(content: str) -> dict[str, Any] | None:
    """Find the sample delivery in a document."""
    for match in _SAMPLE.finditer(content):
        sample = load_example(match.group(1) or match.group(2))
        if isinstance(sample, dict) and isinstance(sample.get("event"), dict):
            return sample
    return None


def event_body(content: str) -> Raw | None:
    """Find the shape of the `event` object in a document."""
    sample = event_sample(content)
    for row in parse_rows(content):
        if row.name == "event" and row.children:
            raw = row_to_raw(row)
            if sample is not None:
                reconcile(raw, sample["event"])
            return raw

    if sample is None:
        return None
    raw = value_to_raw("event", sample["event"])
    return raw if raw.kind == "object" else None


def parse_events() -> tuple[dict[str, list[Model]], list[EventDef]]:
    documents = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((SCHEMA_DIR / "events").glob("*.json"))
    ]

    registries: defaultdict[str, ModelRegistry] = defaultdict(ModelRegistry)
    bodies: list[tuple[dict[str, Any], str, Raw | None]] = []
    for document in documents:
        meta = document["catalog"]["meta"]
        project = snake(meta["Project"])
        body = event_body(document["detail"].get("content") or "")
        bodies.append((document, project, body))
        if body is not None:
            for child in body.fields:
                registries[project].survey(child, "response", child.name)

    events: list[EventDef] = []
    for document, project, body in bodies:
        catalog = document["catalog"]
        event_type = catalog["url"]
        class_name = f"{camel(event_type)}Event"
        registry = registries[project]
        registry.reserve(class_name)

        data_class = None
        if body is not None:
            data_class = f"{class_name}Data"
            registry.reserve(data_class)
            registry.top_level(body, "response", data_class, project)

        redirect = document["detail"].get("redirectUri")
        events.append(
            EventDef(
                event_type=event_type,
                project=project,
                class_name=class_name,
                data_class=data_class,
                title=clean_text(catalog.get("name")),
                doc_url=(
                    f"{DOC_BASE}/document{redirect}"
                    if redirect
                    else f"{DOC_BASE}{catalog['fullPath']}"
                ),
                schema_version="v2" if catalog.get("version") == "V2.0" else "v1",
            )
        )

    models = {p: sorted_models(r.models) for p, r in registries.items()}
    return models, events
