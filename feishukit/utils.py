from enum import Enum
from functools import partial
import inspect
import re
from typing import Any, Literal, TypeVar, final
from urllib.parse import quote, unquote

T = TypeVar("T")


@final
class Unset(Enum):
    _UNSET = "<UNSET>"

    def __repr__(self) -> str:
        return "<UNSET>"

    def __str__(self) -> str:
        return self.__repr__()

    def __bool__(self) -> Literal[False]:
        return False

    def __copy__(self):
        return self._UNSET

    def __deepcopy__(self, memo: dict[int, Any]):
        return self._UNSET


UNSET = Unset._UNSET


def exclude_unset(data: Any) -> Any:
    """Recursively drop the values left as `UNSET`."""
    if isinstance(data, dict):
        return data.__class__(
            (k, exclude_unset(v)) for k, v in data.items() if v is not UNSET
        )
    if isinstance(data, list):
        return data.__class__(exclude_unset(i) for i in data)
    return None if data is UNSET else data


def path_param(value: str | int) -> str:
    """Encode one URL path segment.

    An empty value would silently route the call to a different endpoint
    (`/messages/` instead of `/messages/{id}`) and an unescaped `/` or `?` could
    rewrite the path, so both are ruled out here.
    """
    encoded = quote(str(value), safe="")
    if not encoded:
        raise ValueError("path parameter must not be empty")
    return encoded


def _unwrap_partial(func: T) -> T:
    while isinstance(func, partial):
        func = func.func
    return func


def is_async(obj: Any) -> bool:
    """Check if an object is an async callable (coroutine function)."""
    obj = _unwrap_partial(obj)

    if inspect.isroutine(obj):
        return inspect.iscoroutinefunction(obj)
    if inspect.isclass(obj):
        return False
    return inspect.iscoroutinefunction(type(obj).__call__)


def parse_file_name(content_disposition: str | None) -> str | None:
    """Extract the file name from a `Content-Disposition` header."""
    if not content_disposition:
        return None

    params: dict[str, str] = {}
    for part in content_disposition.split(";"):
        key, sep, value = part.strip().partition("=")
        if sep:
            params[key.lower()] = value.strip().strip('"')

    if extended := params.get("filename*"):
        # RFC 5987: charset'language'percent-encoded-value
        match = re.fullmatch(r"([^']*)'[^']*'(.*)", extended)
        if match is None:
            return unquote(extended)
        return unquote(match.group(2), encoding=match.group(1) or "utf-8")

    if (name := params.get("filename")) is None:
        return None

    name = unquote(name)
    try:
        # Servers commonly put raw UTF-8 bytes in the latin-1 header value.
        return name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name
