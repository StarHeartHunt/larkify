import builtins
import keyword
import re

from pydantic import BaseModel

# A field with one of these names would shadow a type in the same class body.
_ANNOTATION_NAMES = {
    "Any",
    "Field",
    "Literal",
    "bool",
    "dict",
    "float",
    "int",
    "list",
    "str",
}
RESERVED_FIELD_NAMES = {n for n in dir(BaseModel) if not n.startswith("__")} | (
    _ANNOTATION_NAMES | {"page_items"}
)
RESERVED_CLASS_NAMES = {
    "Any",
    "ClassVar",
    "EventV1",
    "EventV2",
    "FeishuModel",
    "Field",
    "FileTypes",
    "Literal",
    "Required",
    "TypedDict",
    *dir(builtins),
}
RESERVED_ARGUMENTS = {"self", "data", "headers", "stream", "params"}


def camel(value: str) -> str:
    words = re.split(r"[^0-9A-Za-z]+|_", value)
    name = "".join(w[:1].upper() + w[1:] for w in words if w)
    if name[:1].isdigit():
        name = "N" + name
    return name


def snake(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z]+", "_", value)
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    return value.strip("_").lower()


def identifier(value: str, reserved: frozenset[str] | set[str] = frozenset()) -> str:
    """Turn a wire name into a Python identifier that is safe to use."""
    name = value if value.isidentifier() else snake(value)
    name = name.lstrip("_") or "field"
    if name[0].isdigit():
        name = f"n{name}"
    if keyword.iskeyword(name) or name in reserved:
        name = f"{name}_"
    return name


def singular(value: str) -> str:
    for suffix in ("_list", "List"):
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)]
    if value.endswith("ies") and len(value) > 4:
        return value[:-3] + "y"
    if value.endswith("s") and not value.endswith(("ss", "us", "is")):
        return value[:-1]
    return value
