"""Auth flows, written once and driven from both sync and async clients.

Fetching a token needs network and cache I/O. Those are expressed as steps
yielded by a plain generator (`FeishuAuth.flow`), and `sync_auth_flow` /
`async_auth_flow` perform the steps. Strategies therefore never have to
implement anything twice.
"""

import abc
from collections.abc import AsyncGenerator, Callable, Generator
from datetime import timedelta
import inspect
import json
import threading
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple, TypeAlias

import anyio
import httpx2

from feishukit.exception import (
    AuthCredentialError,
    RateLimitExceeded,
    RequestFailed,
)
from feishukit.log import logger
from feishukit.typing import TokenType

if TYPE_CHECKING:
    from feishukit import FeishuCore

# Set on each request by the generated client: the token types the API accepts.
TOKEN_TYPES_EXTENSION = "feishukit.token_types"

# Rejected token, from the generic error code document.
# https://open.feishu.cn/document/server-docs/api-call-guide/generic-error-code
TOKEN_REJECTED_CODES = frozenset(
    {
        4001,
        20005,
        20006,
        20013,
        20014,
        99991661,
        99991663,
        99991664,
        99991665,
        99991668,
        99991671,
        99991677,
    }
)


class CacheGet(NamedTuple):
    key: str


class CacheSet(NamedTuple):
    key: str
    value: str
    ex: timedelta


class CacheDelete(NamedTuple):
    key: str


class LockAcquire(NamedTuple):
    pass


class LockRelease(NamedTuple):
    pass


class CallHook(NamedTuple):
    func: Callable[..., Any]
    arg: Any


CacheStep: TypeAlias = CacheGet | CacheSet | CacheDelete
FlowStep: TypeAlias = httpx2.Request | CacheStep | LockAcquire | LockRelease | CallHook
TokenFlow: TypeAlias = Generator[FlowStep, Any, str]
AuthFlow: TypeAlias = Generator[FlowStep, Any, None]


class Locks:
    """Serialises token mutation across threads or tasks.

    The two locks are independent: a client is either sync or async, and a
    thread lock must not be held across an `await`.
    """

    __slots__ = ("asynchronous", "sync")

    def __init__(self) -> None:
        self.sync = threading.Lock()
        self.asynchronous = anyio.Lock()


class BaseAuthStrategy(abc.ABC):
    @abc.abstractmethod
    def get_auth_flow(self, feishu: "FeishuCore") -> httpx2.Auth:
        raise NotImplementedError


def build_token_request(
    feishu: "FeishuCore",
    url: httpx2.URL,
    *,
    request: httpx2.Request | None = None,
    **kwargs: Any,
) -> httpx2.Request:
    """Build a request sent from inside an auth flow.

    httpx2 only sets the timeout extension on the request passed to `send`, so it
    is copied from the request being authenticated.
    """
    timeout = (
        request.extensions.get("timeout") if request is not None else None
    ) or feishu.config.timeout.as_dict()
    return httpx2.Request(
        "POST",
        url,
        extensions={"timeout": timeout},
        headers={"User-Agent": feishu.config.user_agent},
        **kwargs,
    )


def parse_token_response(
    feishu: "FeishuCore", response: httpx2.Response, description: str
) -> dict[str, Any]:
    """Validate a token endpoint response.

    Rate limiting and server errors stay `RequestFailed` so that the configured
    retry policy applies. Everything else means the credentials are not usable.
    """
    try:
        return feishu._check(response, Any, data_key=None).json()
    except RateLimitExceeded:
        raise
    except RequestFailed as e:
        if e.response.status_code >= 500:
            raise
        raise AuthCredentialError(
            f"Failed to obtain {description}: code={e.code}, msg={e.msg!r}, "
            f"log_id={e.log_id}"
        ) from e


def is_token_rejected(response: httpx2.Response) -> bool:
    if not response.is_error:
        return False
    try:
        body = json.loads(response.content)
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("code") in TOKEN_REJECTED_CODES


class FeishuAuth(httpx2.Auth, abc.ABC):
    """Authenticate a request with the token type its API accepts."""

    # Token types this auth can produce, preferred first.
    token_types: ClassVar[tuple[TokenType, ...]]

    feishu: "FeishuCore"

    @property
    def refreshable(self) -> bool:
        """Whether a token rejected by the server can be replaced."""
        return True

    @property
    def locks(self) -> Locks | None:
        return None

    @abc.abstractmethod
    def token_flow(
        self, request: httpx2.Request, token_type: TokenType, *, refresh: bool
    ) -> TokenFlow:
        """Produce a token, replacing the current one if `refresh` is set."""
        raise NotImplementedError

    def select_token_type(
        self, allowed: tuple[TokenType, ...] | None
    ) -> TokenType | None:
        # None means the API metadata has no information, an empty tuple means
        # the API takes no token at all (the token endpoints themselves).
        if allowed is None:
            return self.token_types[0]
        if not allowed:
            return None
        for token_type in self.token_types:
            if token_type in allowed:
                return token_type
        raise AuthCredentialError(
            f"This API accepts {', '.join(allowed)} access tokens, which "
            f"{self.__class__.__name__} cannot provide. "
            "Use `feishu.with_auth(...)` to switch identity."
        )

    def flow(self, request: httpx2.Request) -> AuthFlow:
        token_type = self.select_token_type(
            request.extensions.get(TOKEN_TYPES_EXTENSION)
        )
        if token_type is None:
            yield request
            return

        token = yield from self.token_flow(request, token_type, refresh=False)
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request

        # 99991663 and 99991668 also mean "this API does not take that token
        # type", so a second rejection has to be surfaced instead of looping.
        if self.refreshable and is_token_rejected(response):
            logger.debug("%s access token rejected, replacing it", token_type)
            token = yield from self.token_flow(request, token_type, refresh=True)
            request.headers["Authorization"] = f"Bearer {token}"
            yield request

    def sync_auth_flow(
        self, request: httpx2.Request
    ) -> Generator[httpx2.Request, httpx2.Response, None]:
        cache = self.feishu.config.cache_strategy.get_cache_storage()
        locks = self.locks
        flow = self.flow(request)
        held = False
        try:
            step = next(flow)
            while True:
                result: Any = None
                if isinstance(step, httpx2.Request):
                    result = yield step
                    # Bodies of successful API calls stay unread: they may be
                    # large file downloads requested with `stream=True`.
                    if step is not request or result.is_error:
                        result.read()
                elif isinstance(step, CacheGet):
                    result = cache.get(step.key)
                elif isinstance(step, CacheSet):
                    cache.set(step.key, step.value, step.ex)
                elif isinstance(step, CacheDelete):
                    cache.delete(step.key)
                elif isinstance(step, LockAcquire):
                    assert locks is not None
                    locks.sync.acquire()
                    held = True
                elif isinstance(step, LockRelease):
                    assert locks is not None
                    locks.sync.release()
                    held = False
                else:
                    step.func(step.arg)
                step = flow.send(result)
        except StopIteration:
            return
        finally:
            if held and locks is not None:
                locks.sync.release()

    async def async_auth_flow(
        self, request: httpx2.Request
    ) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
        strategy = self.feishu.config.cache_strategy
        cache = await strategy.get_async_cache_storage()
        locks = self.locks
        flow = self.flow(request)
        held = False
        try:
            step = next(flow)
            while True:
                result: Any = None
                if isinstance(step, httpx2.Request):
                    result = yield step
                    if step is not request or result.is_error:
                        await result.aread()
                elif isinstance(step, CacheGet):
                    result = await cache.aget(step.key)
                elif isinstance(step, CacheSet):
                    await cache.aset(step.key, step.value, step.ex)
                elif isinstance(step, CacheDelete):
                    await cache.adelete(step.key)
                elif isinstance(step, LockAcquire):
                    assert locks is not None
                    await locks.asynchronous.acquire()
                    held = True
                elif isinstance(step, LockRelease):
                    assert locks is not None
                    locks.asynchronous.release()
                    held = False
                else:
                    outcome = step.func(step.arg)
                    if inspect.isawaitable(outcome):
                        await outcome
                step = flow.send(result)
        except StopIteration:
            return
        finally:
            if held and locks is not None:
                locks.asynchronous.release()
