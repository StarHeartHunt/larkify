"""Normalise the `schema/` snapshot into the generator's IR."""

from collections import defaultdict
from collections.abc import Iterable, Iterator
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .ir import (
    Endpoint,
    FileType,
    ListOf,
    MapOf,
    Model,
    ModelField,
    Param,
    Project,
    Raw,
    Resource,
    Scalar,
    TypeRef,
    Variant,
    Version,
)
from .naming import (
    RESERVED_ARGUMENTS,
    RESERVED_CLASS_NAMES,
    RESERVED_FIELD_NAMES,
    camel,
    identifier,
    singular,
    snake,
)

SCHEMA_DIR = Path(__file__).parent.parent / "schema"
DOC_BASE = "https://open.feishu.cn"

KINDS = {
    "string": "str",
    "int": "int",
    "int64": "int",
    "boolean": "bool",
    "bool": "bool",
    "float": "float",
    "file": "file",
    "object": "object",
    "list": "list",
    "map": "map",
}

# Field names too vague to stand on their own as a class name.
GENERIC_NAMES = {
    "Attribute",
    "Body",
    "Config",
    "Content",
    "Data",
    "Detail",
    "Element",
    "Entity",
    "Enum",
    "Field",
    "Info",
    "Item",
    "List",
    "Meta",
    "Object",
    "Option",
    "Param",
    "Property",
    "Record",
    "Request",
    "Response",
    "Result",
    "Value",
}

TOKEN_ORDER = ("tenant", "user", "app")


def clean_text(text: str | None) -> str:
    """Reduce documentation Markdown to one line suitable for a docstring."""
    if not text:
        return ""
    text = text.split("\n\n", 1)[0]
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\{[^{}]*\}\(url=[^)]*\)", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("**", "").replace("`", "")
    text = " ".join(text.split())
    # The documents use a lone dash for "nothing to say".
    if text in ("\\-", "-", "/", "/-"):
        return ""
    return text[:200].rstrip() + "..." if len(text) > 200 else text


def enum_values(options: Iterable[dict[str, Any]], kind: str) -> tuple[Any, ...]:
    values: list[Any] = []
    for option in options:
        value = option.get("value")
        if value in (None, ""):
            continue
        if kind == "int":
            try:
                values.append(int(value))
            except (TypeError, ValueError):
                return ()
        elif kind == "str":
            values.append(str(value))
    return tuple(dict.fromkeys(values))


def normalize(node: dict[str, Any], detail: dict[str, Any] | None = None) -> Raw:
    """Merge a definition node with the matching node of the document, if any.

    The definition has the complete field list and precise types. The document
    was written by hand: its `required` flags, enums and text win when present.
    """
    kind = KINDS.get(node.get("type") or "", "any")
    raw = Raw(
        name=node.get("name") or "",
        kind=kind,
        required=bool((detail if detail is not None else node).get("required", False)),
        description=clean_text(
            (detail or {}).get("description") or node.get("description")
        ),
        ref=node.get("ref") or (detail or {}).get("objectName") or "",
    )
    options = (detail or {}).get("options") or node.get("options") or []
    raw.values = enum_values(options, kind)

    if kind == "object":
        by_name = {p.get("name"): p for p in (detail or {}).get("properties") or []}
        raw.fields = [
            normalize(p, by_name.get(p.get("name")))
            for p in node.get("properties") or []
        ]
    elif kind == "list":
        item = node.get("items") or {}
        raw.item = normalize(item, (detail or {}).get("items"))
    elif kind == "map":
        raw.item = normalize(node.get("valueType") or {})
    return raw


def strip_json_extras(text: str) -> str:
    """Remove `//` comments and trailing commas, leaving strings untouched."""
    out: list[str] = []
    position = 0
    in_string = False
    while position < len(text):
        char = text[position]
        if in_string:
            out.append(char)
            if char == "\\" and position + 1 < len(text):
                out.append(text[position + 1])
                position += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            out.append(char)
        elif text.startswith("//", position):
            end = text.find("\n", position)
            position = len(text) if end == -1 else end
            continue
        else:
            out.append(char)
        position += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load_example(text: Any) -> Any:
    """Parse a documented example, which are often not quite JSON."""
    if not isinstance(text, str) or not text.strip():
        return None
    for candidate in (text, strip_json_extras(text)):
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


_EXAMPLE_TYPES: dict[str, tuple[type, ...]] = {
    "str": (str, int, float),
    "int": (int, str),
    "float": (int, float, str),
    "bool": (bool, str, int),
    "object": (dict,),
    "list": (list,),
    "map": (dict,),
}


def reconcile(raw: Raw, example: Any) -> None:
    """Loosen nodes whose documented example contradicts the declared type.

    A few fields are declared as one type and documented with another. Either
    could be right, so such a field stays unchecked rather than failing a whole
    response. Scalar pairs that pydantic converts are not contradictions.
    """
    if example is None or raw.kind == "any":
        return
    if raw.kind == "file":
        return
    if not isinstance(example, _EXAMPLE_TYPES[raw.kind]):
        raw.kind, raw.fields, raw.item, raw.values = "any", [], None, ()
        return
    if raw.kind == "object":
        for child in raw.fields:
            if child.name in example:
                reconcile(child, example[child.name])
    elif raw.kind == "list" and raw.item is not None:
        for value in example:
            reconcile(raw.item, value)
    elif raw.kind == "map" and raw.item is not None:
        for value in example.values():
            reconcile(raw.item, value)


def signature(raw: Raw, variant: Variant) -> str:
    """Hash of a node's shape. Text is ignored, requiredness only matters on input."""
    if raw.kind == "object" and raw.fields:
        parts = sorted(
            (
                f.name,
                f.required if variant == "request" else False,
                signature(f, variant),
            )
            for f in raw.fields
        )
        return hashlib.sha1(repr(parts).encode()).hexdigest()
    if raw.kind in ("list", "map"):
        assert raw.item is not None
        return f"{raw.kind}:{signature(raw.item, variant)}"
    return raw.kind


class ModelRegistry:
    """Assign one class to each distinct shape, within one namespace."""

    def __init__(self) -> None:
        self.models: list[Model] = []
        self.used_names: set[str] = set()
        self.by_key: dict[tuple[str, str, str], Model] = {}
        self.shapes: defaultdict[tuple[str, str], set[str]] = defaultdict(set)

    @staticmethod
    def _candidate(raw: Raw, owner_field: str) -> str:
        name = camel(raw.ref) or camel(singular(owner_field)) or "Item"
        return f"{name}Model" if name in RESERVED_CLASS_NAMES else name

    def survey(self, raw: Raw, variant: Variant, owner_field: str = "") -> None:
        """First pass, to learn which names cover more than one shape."""
        if raw.kind == "object" and raw.fields:
            key = (variant, self._candidate(raw, owner_field))
            self.shapes[key].add(signature(raw, variant))
            for child in raw.fields:
                self.survey(child, variant, child.name)
        elif raw.item is not None:
            self.survey(raw.item, variant, owner_field)

    def reserve(self, name: str) -> None:
        self.used_names.add(name)

    def _pick_name(self, candidate: str, variant: Variant, parent: Model) -> str:
        """Prefer short names, going by the nearest owner when one is not enough."""
        suffix = "Param" if variant == "request" else ""
        choices = [
            f"{parent.short_name}{candidate}{suffix}",
            f"{parent.name.removesuffix('Param')}{candidate}{suffix}",
        ]
        ambiguous = len(self.shapes[(variant, candidate)]) > 1
        if not ambiguous and candidate not in GENERIC_NAMES:
            choices.insert(0, f"{candidate}{suffix}")

        for name in choices:
            if name not in self.used_names:
                self.used_names.add(name)
                return name

        index = 2
        while (name := f"{choices[-1]}{index}") in self.used_names:
            index += 1
        self.used_names.add(name)
        return name

    def add_user(self, model: Model, user: str) -> None:
        if user not in model.users:
            model.users.add(user)
            for dependency in model.dependencies:
                self.add_user(dependency, user)

    def build_fields(self, raw: Raw, model: Model, user: str) -> None:
        taken: set[str] = set()
        for child in raw.fields:
            py_name = identifier(child.name, RESERVED_FIELD_NAMES | taken)
            taken.add(py_name)
            model.fields.append(
                ModelField(
                    child.name,
                    py_name,
                    self.type_of(child, model.variant, model, child.name, user),
                    child.required,
                    child.description,
                )
            )

    def top_level(self, raw: Raw, variant: Variant, name: str, user: str) -> Model:
        model = Model(name, variant, raw.description, short_name=name)
        model.users.add(user)
        self.models.append(model)
        self.build_fields(raw, model, user)
        return model

    def type_of(
        self, raw: Raw, variant: Variant, parent: Model, owner_field: str, user: str
    ) -> TypeRef:
        if raw.kind == "object":
            if not raw.fields:
                return MapOf(Scalar("Any"))
            candidate = self._candidate(raw, owner_field)
            key = (variant, candidate, signature(raw, variant))
            model = self.by_key.get(key)
            if model is None:
                name = self._pick_name(candidate, variant, parent)
                model = Model(name, variant, raw.description, short_name=candidate)
                self.by_key[key] = model
                self.models.append(model)
                model.users.add(user)
                self.build_fields(raw, model, user)
            else:
                self.add_user(model, user)
            return model
        if raw.kind == "list":
            assert raw.item is not None
            return ListOf(self.type_of(raw.item, variant, parent, owner_field, user))
        if raw.kind == "map":
            assert raw.item is not None
            return MapOf(self.type_of(raw.item, variant, parent, owner_field, user))
        if raw.kind == "file":
            return FileType()
        if raw.kind == "any":
            return Scalar("Any")
        return Scalar(raw.kind, raw.values)


def sorted_models(models: Iterable[Model]) -> list[Model]:
    """Order models so that each one comes after those it refers to."""
    ordered: list[Model] = []
    seen: set[int] = set()
    selected = {id(m) for m in models}

    def visit(model: Model) -> None:
        if id(model) in seen:
            return
        seen.add(id(model))
        for dependency in model.dependencies:
            if id(dependency) in selected:
                visit(dependency)
        ordered.append(model)

    for model in models:
        visit(model)
    return ordered


def _body_media(detail: dict[str, Any]) -> dict[str, Any]:
    for media in ((detail.get("requestBody") or {}).get("content") or {}).values():
        return media
    return {}


def _response_media(detail: dict[str, Any]) -> dict[str, Any]:
    responses = detail.get("responses") or {}
    for media in ((responses.get("200") or {}).get("content") or {}).values():
        return media
    return {}


def _parameter_details(detail: dict[str, Any], location: str) -> dict[str, Any]:
    found = {}
    for parameter in detail.get("parameters") or []:
        schema = parameter.get("schema") or {}
        if parameter.get("in") == location:
            found[schema.get("name")] = schema
    return found


def path_placeholders(path: str) -> list[str]:
    return re.findall(r":([A-Za-z_][A-Za-z0-9_]*)", path)


def url_expression(path: str, params: dict[str, str]) -> str:
    if not params:
        return repr(path)

    def replace(match: re.Match[str]) -> str:
        return "{path_param(" + params[match.group(1)] + ")}"

    escaped = path.replace("{", "{{").replace("}", "}}")
    return "f" + repr(re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", replace, escaped))


class RawEndpoint:
    """One API, normalised, before classes have been assigned to its nodes."""

    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document
        self.definition: dict[str, Any] = document["definition"]
        self.detail: dict[str, Any] = document["detail"].get("apiSchema") or {}
        catalog = document["catalog"]
        meta = catalog["meta"]

        self.project = meta["Project"]
        self.version = meta["Version"]
        self.wire_resource: str = meta["Resource"]
        self.wire_method: str = meta["Name"]
        self.resource = identifier(snake(self.wire_resource))
        self.method = identifier(snake(self.wire_method))

        request = self.definition.get("request") or {}
        response = self.definition.get("response") or {}

        body = request.get("body")
        body_media = _body_media(self.detail)
        self.body = (
            normalize(body, body_media.get("schema"))
            if isinstance(body, dict) and body.get("type") == "object"
            else None
        )
        self.has_opaque_body = bool(self.body is None and body)
        if self.body is not None:
            reconcile(self.body, load_example(body_media.get("example")))

        envelope = response.get("body")
        response_media = _response_media(self.detail)
        self.response = (
            normalize(envelope, response_media.get("schema"))
            if isinstance(envelope, dict) and envelope.get("properties")
            else None
        )
        if self.response is not None:
            reconcile(self.response, load_example(response_media.get("example")))

    @property
    def user(self) -> str:
        return self.resource

    @property
    def data_node(self) -> Raw | None:
        if self.response is None:
            return None
        for child in self.response.fields:
            if child.name == "data" and child.kind == "object":
                return child
        return None

    @property
    def top_level_fields(self) -> list[Raw]:
        """Fields of an API without the `data` envelope."""
        if self.response is None or self.data_node is not None:
            return []
        return [f for f in self.response.fields if f.name not in ("code", "msg")]

    @property
    def base_name(self) -> str:
        return f"{camel(self.wire_method)}{camel(self.wire_resource)}"


def page_items_field(model: Model, query: list[Param], body: Model | None) -> None:
    """Mark the data model of a paginated API.

    The `pagination` flag of the definition misses about a third of them, so
    this goes by shape: a page token going in, and a continuation coming out.
    """
    names = {f.wire_name: f for f in model.fields}
    takes_token = any(p.wire_name == "page_token" for p in query) or (
        body is not None and any(f.wire_name == "page_token" for f in body.fields)
    )
    continues = {"has_more", "page_token", "next_page_token"} & names.keys()
    if not takes_token or not continues:
        return

    lists = [f for f in model.fields if isinstance(f.type, ListOf)]
    if "items" in names and isinstance(names["items"].type, ListOf):
        model.page_items = names["items"]
    elif len(lists) == 1:
        model.page_items = lists[0]


def build_params(
    nodes: Iterable[dict[str, Any]], details: dict[str, Any], taken: set[str]
) -> list[Param]:
    params: list[Param] = []
    for node in nodes:
        raw = normalize(node, details.get(node.get("name")))
        py_name = identifier(raw.name, RESERVED_ARGUMENTS | taken)
        taken.add(py_name)
        if raw.kind == "list" and raw.item is not None:
            item = Scalar(raw.item.kind if raw.item.kind != "any" else "Any")
            type_: TypeRef = ListOf(item)
        elif raw.kind in ("str", "int", "float", "bool"):
            type_ = Scalar(raw.kind, raw.values)
        else:
            type_ = Scalar("Any")
        params.append(Param(raw.name, py_name, type_, raw.required, raw.description))
    return params


def build_endpoint(raw: RawEndpoint, registry: ModelRegistry) -> Endpoint:
    document = raw.document
    catalog = document["catalog"]
    definition = raw.definition
    request = definition.get("request") or {}
    detail_doc = document["detail"]

    # Not the catalog's `url`: that one has mistakes, like missing version segments.
    http_method, path = definition["httpMethod"], definition["apiPath"]

    taken: set[str] = set()
    path_nodes = {
        p.get("name"): p for p in (request.get("path") or {}).get("properties") or []
    }
    path_details = _parameter_details(raw.detail, "path")
    ordered_nodes = [
        path_nodes.get(n, {"name": n, "type": "string", "required": True})
        for n in dict.fromkeys(path_placeholders(path))
    ]
    path_params = build_params(ordered_nodes, path_details, taken)
    for param in path_params:
        param.type = Scalar("str")
        param.required = True

    query_params = build_params(
        (request.get("query") or {}).get("properties") or [],
        _parameter_details(raw.detail, "query"),
        taken,
    )

    body_model = None
    if raw.body is not None and raw.body.fields:
        body_model = registry.top_level(
            raw.body, "request", f"{raw.base_name}Body", raw.user
        )

    data_model = None
    data_node = raw.data_node
    data_key: str | None = "data"
    if data_node is not None and data_node.fields:
        data_model = registry.top_level(
            data_node, "response", f"{raw.base_name}Response", raw.user
        )
    elif raw.top_level_fields:
        data_key = None
        envelope = Raw("", "object", fields=raw.top_level_fields)
        data_model = registry.top_level(
            envelope, "response", f"{raw.base_name}Response", raw.user
        )

    if data_model is not None:
        page_items_field(data_model, query_params, body_model)

    if definition.get("supportFileDownload"):
        response_model = "bytes"
    elif data_model is not None:
        response_model = data_model.name
    else:
        response_model = "Any"

    file_fields: list[str] = []
    kwargs: list[Param] = []
    if body_model is not None:
        argument_names = {p.py_name for p in path_params + query_params}
        for model_field in body_model.fields:
            if isinstance(model_field.type, FileType):
                file_fields.append(model_field.wire_name)
            # A body field named like a query argument has to go through `data`.
            if model_field.py_name in argument_names | RESERVED_ARGUMENTS:
                continue
            kwargs.append(
                Param(
                    model_field.wire_name,
                    model_field.py_name,
                    model_field.type,
                    model_field.required,
                )
            )

    tokens = definition.get("accessTokens") or []
    redirect = detail_doc.get("redirectUri")
    doc_url = (
        f"{DOC_BASE}/document{redirect}"
        if redirect
        else f"{DOC_BASE}{catalog['fullPath']}"
    )

    return Endpoint(
        project=raw.project,
        version=raw.version,
        resource=raw.resource,
        method=raw.method,
        http_method=http_method,
        url=url_expression(path, {p.wire_name: p.py_name for p in path_params}),
        title=clean_text(catalog.get("name")),
        description=clean_text(detail_doc.get("description") or catalog.get("detail")),
        doc_url=doc_url,
        token_types=tuple(t for t in TOKEN_ORDER if t in tokens),
        path_params=path_params,
        query_params=query_params,
        body=body_model,
        has_opaque_body=raw.has_opaque_body
        or (raw.body is not None and not raw.body.fields),
        kwargs=kwargs,
        file_fields=file_fields,
        response_model=response_model,
        data_key=data_key,
    )


def legacy_method_name(path: str, wire_name: str, taken: set[str]) -> str:
    """Name an API that only exists as a path, by its static path segments."""
    static = [s for s in wire_name.split("/") if s and not s.startswith(":")]
    base = identifier(snake("_".join(static)) or snake(path.rsplit("/", 1)[-1]))
    name, index = base, 2
    while name in taken:
        name, index = f"{base}_{index}", index + 1
    taken.add(name)
    return name


def build_legacy_endpoint(document: dict[str, Any], taken: set[str]) -> Endpoint:
    catalog = document["catalog"]
    meta = catalog["meta"]
    http_method, _, path = catalog["url"].partition(":")
    method = legacy_method_name(path, meta["Name"], taken)

    path_taken: set[str] = set()
    path_params = [
        Param(
            name,
            identifier(snake(name), RESERVED_ARGUMENTS | path_taken),
            Scalar("str"),
            True,
        )
        for name in dict.fromkeys(path_placeholders(path))
    ]
    redirect = document["detail"].get("redirectUri")
    return Endpoint(
        project=meta["Project"],
        version="legacy",
        resource="legacy",
        method=method,
        http_method=http_method,
        url=url_expression(path, {p.wire_name: p.py_name for p in path_params}),
        title=clean_text(catalog.get("name")),
        description=clean_text(catalog.get("detail")),
        doc_url=(
            f"{DOC_BASE}/document{redirect}"
            if redirect
            else f"{DOC_BASE}{catalog['fullPath']}"
        ),
        token_types=None,
        path_params=path_params,
        legacy=True,
    )


def iter_documents() -> Iterator[dict[str, Any]]:
    for path in sorted((SCHEMA_DIR / "apis").glob("*/*/*.json")):
        yield json.loads(path.read_text(encoding="utf-8"))


def parse_projects() -> list[Project]:
    grouped: defaultdict[str, defaultdict[str, list[dict[str, Any]]]]
    grouped = defaultdict(lambda: defaultdict(list))
    for document in iter_documents():
        meta = document["catalog"]["meta"]
        version = "legacy" if meta["Version"] == "old" else meta["Version"]
        grouped[meta["Project"]][version].append(document)

    projects: list[Project] = []
    for project_name, versions in sorted(grouped.items()):
        project = Project(snake(project_name), camel(project_name))
        for version_name, documents in sorted(versions.items()):
            class_name = f"{project.class_name}{camel(version_name)}"
            version = Version(project_name, version_name, class_name)
            if version_name == "legacy":
                version.legacy = True
                taken: set[str] = set()
                resource = Resource("legacy", class_name)
                resource.endpoints = [
                    build_legacy_endpoint(d, taken) for d in documents
                ]
                version.resources = [resource]
            else:
                _build_version(version, documents)
            project.versions.append(version)
        projects.append(project)
    return projects


def _build_version(version: Version, documents: list[dict[str, Any]]) -> None:
    raws = [RawEndpoint(d) for d in documents]
    raws.sort(key=lambda r: (r.resource, r.method))

    registry = ModelRegistry()
    for raw in raws:
        registry.reserve(f"{raw.base_name}Body")
        registry.reserve(f"{raw.base_name}Response")
        if raw.body is not None:
            for child in raw.body.fields:
                registry.survey(child, "request", child.name)
        for child in raw.top_level_fields:
            registry.survey(child, "response", child.name)
        if raw.data_node is not None:
            for child in raw.data_node.fields:
                registry.survey(child, "response", child.name)

    resources: dict[str, Resource] = {}
    seen_methods: set[tuple[str, str]] = set()
    for raw in raws:
        if (raw.resource, raw.method) in seen_methods:
            raise ValueError(f"duplicate method {raw.resource}.{raw.method}")
        seen_methods.add((raw.resource, raw.method))
        resource = resources.setdefault(
            raw.resource, Resource(raw.resource, f"{camel(raw.wire_resource)}Client")
        )
        resource.endpoints.append(build_endpoint(raw, registry))

    version.resources = list(resources.values())
    version.models = sorted_models(registry.models)
