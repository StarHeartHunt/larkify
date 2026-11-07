"""Intermediate representation shared by the parsers and the templates."""

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

Variant: TypeAlias = Literal["request", "response"]


@dataclass
class Raw:
    """A schema node, normalised from whichever document it came from."""

    name: str
    kind: str  # str, int, float, bool, any, file, object, list, map
    required: bool = False
    description: str = ""
    values: tuple[str | int, ...] = ()
    ref: str = ""
    fields: list["Raw"] = field(default_factory=list)
    item: "Raw | None" = None


@dataclass(frozen=True)
class Scalar:
    name: str  # str, int, float, bool, Any
    values: tuple[str | int, ...] = ()


@dataclass(frozen=True)
class FileType:
    pass


@dataclass(frozen=True)
class ListOf:
    item: "TypeRef"


@dataclass(frozen=True)
class MapOf:
    value: "TypeRef"


@dataclass(eq=False)
class ModelField:
    wire_name: str
    py_name: str
    type: "TypeRef"
    required: bool
    description: str


@dataclass(eq=False)
class Model:
    name: str
    variant: Variant
    description: str = ""
    fields: list[ModelField] = field(default_factory=list)
    users: set[str] = field(default_factory=set)
    # Name without any qualification, for naming what is nested in this model.
    short_name: str = ""
    # Attribute holding the items, when this is the data of a paginated API.
    page_items: ModelField | None = None

    @property
    def typed_name(self) -> str:
        return f"{self.name}Type"

    @property
    def dependencies(self) -> list["Model"]:
        found: list[Model] = []
        for model_field in self.fields:
            found.extend(models_in(model_field.type))
        return found


TypeRef: TypeAlias = Scalar | FileType | ListOf | MapOf | Model


def models_in(type_: TypeRef) -> list[Model]:
    if isinstance(type_, Model):
        return [type_]
    if isinstance(type_, ListOf):
        return models_in(type_.item)
    if isinstance(type_, MapOf):
        return models_in(type_.value)
    return []


def _literal(type_: Scalar) -> str:
    return "Literal[" + ", ".join(repr(v) for v in type_.values) + "]"


def model_hint(type_: TypeRef) -> str:
    """Annotation on a pydantic model.

    Enums are not enforced at runtime: the documented values lag behind the API
    and a rejected call is worse than an unchecked value.
    """
    if isinstance(type_, Scalar):
        return type_.name
    if isinstance(type_, FileType):
        return "Any"
    if isinstance(type_, ListOf):
        return f"list[{model_hint(type_.item)}]"
    if isinstance(type_, MapOf):
        return f"dict[str, {model_hint(type_.value)}]"
    return type_.name


def typed_dict_hint(type_: TypeRef) -> str:
    """Annotation on a TypedDict."""
    if isinstance(type_, Scalar):
        return _literal(type_) if type_.values else type_.name
    if isinstance(type_, FileType):
        return "FileTypes"
    if isinstance(type_, ListOf):
        return f"list[{typed_dict_hint(type_.item)}]"
    if isinstance(type_, MapOf):
        return f"dict[str, {typed_dict_hint(type_.value)}]"
    return type_.typed_name


def argument_hint(type_: TypeRef) -> str:
    """Annotation on a method argument.

    Client classes have methods called `list`, which shadow the builtin inside
    the class body, hence the abstract collection types.
    """
    if isinstance(type_, Scalar):
        return _literal(type_) if type_.values else type_.name
    if isinstance(type_, FileType):
        return "FileTypes"
    if isinstance(type_, ListOf):
        return f"Sequence[{argument_hint(type_.item)}]"
    if isinstance(type_, MapOf):
        return f"Mapping[str, {argument_hint(type_.value)}]"
    return f"{type_.typed_name} | {type_.name}"


@dataclass
class Param:
    wire_name: str
    py_name: str
    type: TypeRef
    required: bool
    description: str = ""


@dataclass
class Endpoint:
    project: str
    version: str
    resource: str
    method: str
    http_method: str
    url: str  # expression, a Python string literal or f-string
    title: str
    description: str
    doc_url: str
    token_types: tuple[str, ...] | None
    path_params: list[Param] = field(default_factory=list)
    query_params: list[Param] = field(default_factory=list)
    body: Model | None = None
    has_opaque_body: bool = False
    kwargs: list[Param] = field(default_factory=list)
    file_fields: list[str] = field(default_factory=list)
    response_model: str = "Any"
    data_key: str | None = "data"
    legacy: bool = False


@dataclass
class Resource:
    py_name: str
    class_name: str
    endpoints: list[Endpoint] = field(default_factory=list)


@dataclass
class Version:
    project: str
    version: str
    class_name: str
    resources: list[Resource] = field(default_factory=list)
    models: list[Model] = field(default_factory=list)
    legacy: bool = False
    project_module: str = ""


@dataclass
class Project:
    py_name: str
    class_name: str
    versions: list[Version] = field(default_factory=list)


@dataclass
class EventDef:
    event_type: str
    project: str
    class_name: str
    data_class: str | None
    title: str
    doc_url: str
    schema_version: str  # "v1" or "v2"
