from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from typing import IO, Any, Literal, NamedTuple, TypeAlias, TypeVar

import httpx2

from .exception import FeishuException
from .utils import Unset

T = TypeVar("T")

URLTypes: TypeAlias = httpx2.URL | str

ProxyTypes: TypeAlias = httpx2.URL | str | httpx2.Proxy

PrimitiveData: TypeAlias = str | int | float | bool | None
QueryParamTypes: TypeAlias = (
    httpx2.QueryParams
    | Mapping[str, PrimitiveData | Sequence[PrimitiveData]]
    | list[tuple[str, PrimitiveData]]
    | tuple[tuple[str, PrimitiveData], ...]
    | str
    | bytes
)

HeaderTypes: TypeAlias = (
    httpx2.Headers
    | Mapping[str, str]
    | Mapping[bytes, bytes]
    | Sequence[tuple[str, str]]
    | Sequence[tuple[bytes, bytes]]
)

CookieTypes: TypeAlias = httpx2.Cookies | dict[str, str] | list[tuple[str, str]]

ContentTypes: TypeAlias = str | bytes

TimeoutTypes: TypeAlias = float | httpx2.Timeout | None

FileContent: TypeAlias = IO[bytes] | bytes
FileTypes: TypeAlias = (
    FileContent
    | tuple[str | None, FileContent]
    | tuple[str | None, FileContent, str | None]
)
RequestFiles: TypeAlias = Mapping[str, FileTypes] | Sequence[tuple[str, FileTypes]]

UnsetType: TypeAlias = Literal[Unset._UNSET]

Missing: TypeAlias = UnsetType | T | None

TokenType: TypeAlias = Literal["tenant", "app", "user"]


class RetryOption(NamedTuple):
    do_retry: bool
    retry_after: timedelta | None = None


RetryDecisionFunc: TypeAlias = Callable[[FeishuException, int], RetryOption]

EventHookTypes: TypeAlias = Mapping[str, list[Callable[..., Any]]]
