from collections.abc import Awaitable, Callable
from typing import Any, Generic, ParamSpec, Self, TypeAlias, TypeVar, cast

from feishukit.exception import PaginationError
from feishukit.model import Page
from feishukit.response import Response
from feishukit.utils import is_async

CP = ParamSpec("CP")
CT = TypeVar("CT")
RT = TypeVar("RT")

RequestFunc: TypeAlias = (
    Callable[CP, Response[CT]] | Callable[CP, Awaitable[Response[CT]]]
)


class Paginator(Generic[RT]):
    """Follow the `page_token` of a Feishu list API, one item at a time."""

    def __init__(
        self,
        request: Callable[..., Any],
        *args: Any,
        map_func: Callable[[Response[Any]], list[RT]] | None = None,
        **kwargs: Any,
    ):
        self.request = request
        self.args = args
        self.kwargs = kwargs
        self.map_func = map_func

        self._next_token: str | None = kwargs.get("page_token")
        self._finished = False
        self._latest_response: Response[Any] | None = None

        self._index: int = 0
        self._cached_data: list[RT] = []

    @property
    def latest_response(self) -> Response[Any] | None:
        """The latest API response of the paginator."""
        return self._latest_response

    @property
    def finalized(self) -> bool:
        """Whether the last page has been fetched."""
        return self._finished

    def reset(self) -> None:
        """Reset the paginator to the initial state."""
        self._next_token = self.kwargs.get("page_token")
        self._finished = False
        self._latest_response = None
        self._index = 0
        self._cached_data = []

    def __iter__(self) -> Self:
        if is_async(self.request):
            raise TypeError(f"Request method {self.request} is not a sync function")
        return self

    def __next__(self) -> RT:
        while self._index >= len(self._cached_data):
            if self._finished:
                raise StopIteration
            self._accept(cast(Response[Any], self.request(*self.args, **self._page())))

        current = self._cached_data[self._index]
        self._index += 1
        return current

    def __aiter__(self) -> Self:
        if not is_async(self.request):
            raise TypeError(f"Request method {self.request} is not an async function")
        return self

    async def __anext__(self) -> RT:
        while self._index >= len(self._cached_data):
            if self._finished:
                raise StopAsyncIteration
            self._accept(await self.request(*self.args, **self._page()))

        current = self._cached_data[self._index]
        self._index += 1
        return current

    def _page(self) -> dict[str, Any]:
        kwargs = dict(self.kwargs)
        if self._next_token:
            kwargs["page_token"] = self._next_token
        return kwargs

    def _items(self, response: Response[Any]) -> list[RT]:
        if self.map_func is not None:
            items = self.map_func(response)
            if not isinstance(items, list):
                raise TypeError(f"Map function must return a list, got {type(items)}")
            return items

        data = response.parsed_data
        if not isinstance(data, Page):
            raise TypeError(
                f"Cannot locate the items of {type(data).__name__}, "
                "use `paginate_with` to pick them out"
            )
        return cast(Page[RT], data).page_items

    def _accept(self, response: Response[Any]) -> None:
        self._latest_response = response
        self._cached_data = self._items(response)
        self._index = 0

        data = response.json().get("data") or {}
        token = data.get("page_token") or data.get("next_page_token")
        # A few APIs have no `has_more`: a token is then the only signal.
        if not data.get("has_more", bool(token)) or not token:
            self._finished = True
            return
        if token == self._next_token:
            raise PaginationError(f"page_token {token!r} did not advance")
        self._next_token = token
