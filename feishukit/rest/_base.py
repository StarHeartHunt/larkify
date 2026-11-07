from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar, overload

from .paginator import Paginator, RequestFunc

if TYPE_CHECKING:
    from feishukit import FeishuCore
    from feishukit.model import Page
    from feishukit.response import Response

CP = ParamSpec("CP")
CT = TypeVar("CT")
RT = TypeVar("RT")


class BaseClient:
    def __init__(self, feishu: "FeishuCore"):
        self._feishu = feishu


class BaseRestNamespace(BaseClient):
    @overload
    def paginate(
        self,
        request: "RequestFunc[CP, Page[RT]]",
        *args: CP.args,
        **kwargs: CP.kwargs,
    ) -> Paginator[RT]: ...

    @overload
    def paginate(
        self,
        request: "RequestFunc[CP, Any]",
        *args: CP.args,
        **kwargs: CP.kwargs,
    ) -> Paginator[Any]: ...

    def paginate(
        self,
        request: "RequestFunc[CP, Any]",
        *args: CP.args,
        **kwargs: CP.kwargs,
    ) -> Paginator[Any]:
        """Iterate over every item of a paginated API.

        ```python
        for chat in feishu.rest.paginate(feishu.rest.im.v1.chat.list):
            print(chat.name)

        async for chat in feishu.rest.paginate(feishu.rest.im.v1.chat.async_list):
            print(chat.name)
        ```

        Use `paginate_with` when the items need to be picked out by hand.
        """
        return Paginator(request, *args, **kwargs)

    def paginate_with(
        self,
        request: "RequestFunc[CP, CT]",
        map_func: "Callable[[Response[CT]], list[RT]]",
        *args: CP.args,
        **kwargs: CP.kwargs,
    ) -> Paginator[RT]:
        """Like `paginate`, reading the items of a page with `map_func`."""
        return Paginator(request, *args, map_func=map_func, **kwargs)  # type: ignore
