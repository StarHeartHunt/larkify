from collections.abc import AsyncGenerator, Generator, Sequence
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import timedelta
import json as jsonlib
import time
from types import TracebackType
from typing import TYPE_CHECKING, Any, Generic, TypeVar, overload
from typing_extensions import TypeForm

import anyio
import httpx2
from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from .auth import BaseAuthStrategy, TokenAuthStrategy, UnauthAuthStrategy
from .auth.base import TOKEN_TYPES_EXTENSION
from .cache import BaseCacheStrategy
from .config import Config, get_config
from .exception import (
    FeishuException,
    RateLimitExceeded,
    RequestError,
    RequestFailed,
    RequestTimeout,
)
from .response import Response
from .throttling import BaseThrottler
from .typing import (
    ContentTypes,
    CookieTypes,
    EventHookTypes,
    HeaderTypes,
    ProxyTypes,
    QueryParamTypes,
    RequestFiles,
    RetryDecisionFunc,
    TimeoutTypes,
    TokenType,
    UnsetType,
    URLTypes,
)
from .utils import UNSET, exclude_unset

if TYPE_CHECKING:
    import ssl

T = TypeVar("T")
A = TypeVar("A", bound="BaseAuthStrategy")
AS = TypeVar("AS", bound="BaseAuthStrategy")

# https://open.feishu.cn/document/server-docs/api-call-guide/frequency-control
# https://open.feishu.cn/document/server-docs/api-call-guide/generic-error-code
RATE_LIMIT_CODES = frozenset({90217, 1000004, 1000005, 11232, 11233, 11247, 99991400})
DEFAULT_RETRY_AFTER = timedelta(seconds=1)


class FeishuCore(Generic[A]):
    # none auth with config
    @overload
    def __init__(
        self: "FeishuCore[UnauthAuthStrategy]",
        auth: None = None,
        *,
        config: Config,
    ): ...

    # token auth with config
    @overload
    def __init__(
        self: "FeishuCore[TokenAuthStrategy]",
        auth: str,
        *,
        config: Config,
    ): ...

    # other auth strategies with config
    @overload
    def __init__(
        self: "FeishuCore[AS]",
        auth: AS,
        *,
        config: Config,
    ): ...

    # none auth without config
    @overload
    def __init__(
        self: "FeishuCore[UnauthAuthStrategy]",
        auth: None = None,
        *,
        base_url: str | httpx2.URL | None = None,
        oauth_base_url: str | httpx2.URL | None = None,
        user_agent: str | None = None,
        follow_redirects: bool = True,
        timeout: float | httpx2.Timeout | None = None,
        ssl_verify: "bool | ssl.SSLContext" = ...,
        trust_env: bool = True,
        proxy: ProxyTypes | None = None,
        transport: httpx2.BaseTransport | None = None,
        async_transport: httpx2.AsyncBaseTransport | None = None,
        event_hooks: EventHookTypes | None = None,
        async_event_hooks: EventHookTypes | None = None,
        cache_strategy: BaseCacheStrategy | None = None,
        throttler: BaseThrottler | None = None,
        auto_retry: bool | RetryDecisionFunc = True,
        rest_api_validate_body: bool = True,
        insecure_allow_http: bool = False,
    ): ...

    # token auth without config
    @overload
    def __init__(
        self: "FeishuCore[TokenAuthStrategy]",
        auth: str,
        *,
        base_url: str | httpx2.URL | None = None,
        oauth_base_url: str | httpx2.URL | None = None,
        user_agent: str | None = None,
        follow_redirects: bool = True,
        timeout: float | httpx2.Timeout | None = None,
        ssl_verify: "bool | ssl.SSLContext" = ...,
        trust_env: bool = True,
        proxy: ProxyTypes | None = None,
        transport: httpx2.BaseTransport | None = None,
        async_transport: httpx2.AsyncBaseTransport | None = None,
        event_hooks: EventHookTypes | None = None,
        async_event_hooks: EventHookTypes | None = None,
        cache_strategy: BaseCacheStrategy | None = None,
        throttler: BaseThrottler | None = None,
        auto_retry: bool | RetryDecisionFunc = True,
        rest_api_validate_body: bool = True,
        insecure_allow_http: bool = False,
    ): ...

    # other auth strategies without config
    @overload
    def __init__(
        self: "FeishuCore[AS]",
        auth: AS,
        *,
        base_url: str | httpx2.URL | None = None,
        oauth_base_url: str | httpx2.URL | None = None,
        user_agent: str | None = None,
        follow_redirects: bool = True,
        timeout: float | httpx2.Timeout | None = None,
        ssl_verify: "bool | ssl.SSLContext" = ...,
        trust_env: bool = True,
        proxy: ProxyTypes | None = None,
        transport: httpx2.BaseTransport | None = None,
        async_transport: httpx2.AsyncBaseTransport | None = None,
        event_hooks: EventHookTypes | None = None,
        async_event_hooks: EventHookTypes | None = None,
        cache_strategy: BaseCacheStrategy | None = None,
        throttler: BaseThrottler | None = None,
        auto_retry: bool | RetryDecisionFunc = True,
        rest_api_validate_body: bool = True,
        insecure_allow_http: bool = False,
    ): ...

    def __init__(
        self,
        auth: A | str | None = None,
        *,
        config: Config | None = None,
        base_url: str | httpx2.URL | None = None,
        oauth_base_url: str | httpx2.URL | None = None,
        user_agent: str | None = None,
        follow_redirects: bool = True,
        timeout: float | httpx2.Timeout | None = None,
        ssl_verify: "bool | ssl.SSLContext" = True,
        trust_env: bool = True,
        proxy: ProxyTypes | None = None,
        transport: httpx2.BaseTransport | None = None,
        async_transport: httpx2.AsyncBaseTransport | None = None,
        event_hooks: EventHookTypes | None = None,
        async_event_hooks: EventHookTypes | None = None,
        cache_strategy: BaseCacheStrategy | None = None,
        throttler: BaseThrottler | None = None,
        auto_retry: bool | RetryDecisionFunc = True,
        rest_api_validate_body: bool = True,
        insecure_allow_http: bool = False,
    ):
        auth = auth or UnauthAuthStrategy()  # type: ignore
        self.auth: A = (  # type: ignore
            TokenAuthStrategy(auth) if isinstance(auth, str) else auth
        )

        self.config = config or get_config(
            base_url=base_url,
            oauth_base_url=oauth_base_url,
            user_agent=user_agent,
            follow_redirects=follow_redirects,
            timeout=timeout,
            ssl_verify=ssl_verify,
            trust_env=trust_env,
            proxy=proxy,
            transport=transport,
            async_transport=async_transport,
            event_hooks=event_hooks,
            async_event_hooks=async_event_hooks,
            cache_strategy=cache_strategy,
            throttler=throttler,
            auto_retry=auto_retry,
            rest_api_validate_body=rest_api_validate_body,
            insecure_allow_http=insecure_allow_http,
        )

        self.__sync_client: ContextVar[httpx2.Client | None] = ContextVar(
            "sync_client", default=None
        )
        self.__async_client: ContextVar[httpx2.AsyncClient | None] = ContextVar(
            "async_client", default=None
        )

    # sync context
    def __enter__(self):
        if self.__sync_client.get() is not None:
            raise RuntimeError("Cannot enter sync context twice")
        self.__sync_client.set(self._create_sync_client())
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ):
        if client := self.__sync_client.get():
            try:
                client.close()
            finally:
                self.__sync_client.set(None)

    # async context
    async def __aenter__(self):
        if self.__async_client.get() is not None:
            raise RuntimeError("Cannot enter async context twice")
        self.__async_client.set(self._create_async_client())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ):
        if client := self.__async_client.get():
            try:
                await client.aclose()
            finally:
                self.__async_client.set(None)

    def _get_client_defaults(self) -> dict[str, Any]:
        """Get default arguments for creating a httpx2 client."""
        return {
            "auth": self.auth.get_auth_flow(self),
            "base_url": self.config.base_url,
            "headers": {"User-Agent": self.config.user_agent},
            "timeout": self.config.timeout,
            "follow_redirects": self.config.follow_redirects,
            "verify": self.config.ssl_verify,
            "trust_env": self.config.trust_env,
            "proxy": self.config.proxy,
        }

    def _create_sync_client(self) -> httpx2.Client:
        return httpx2.Client(
            **self._get_client_defaults(),
            transport=self.config.transport,
            event_hooks=self.config.event_hooks,
        )

    # get or create sync client
    @contextmanager
    def get_sync_client(self) -> Generator[httpx2.Client, None, None]:
        if client := self.__sync_client.get():
            yield client
        else:
            client = self._create_sync_client()
            try:
                yield client
            finally:
                client.close()

    def _create_async_client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            **self._get_client_defaults(),
            transport=self.config.async_transport,
            event_hooks=self.config.async_event_hooks,
        )

    # get or create async client
    @asynccontextmanager
    async def get_async_client(self) -> AsyncGenerator[httpx2.AsyncClient, None]:
        if client := self.__async_client.get():
            yield client
        else:
            client = self._create_async_client()
            try:
                yield client
            finally:
                await client.aclose()

    # request bodies
    def build_body(self, model: type[BaseModel], data: Any, kwargs: dict) -> Any:
        """Turn the `data` or keyword arguments of a generated method into JSON."""
        body = kwargs if data is UNSET else data
        if isinstance(body, dict):
            body = exclude_unset(body)

        if self.config.rest_api_validate_body:
            body = model.model_validate(body)
        if isinstance(body, BaseModel):
            return body.model_dump(mode="json", by_alias=True, exclude_unset=True)
        if isinstance(body, dict):
            # Validation is what maps `from_` to `from`, do that much by hand.
            fields = model.model_fields
            return {
                (fields[k].alias or k) if k in fields else k: v for k, v in body.items()
            }
        return body

    def build_form(
        self,
        model: type[BaseModel],
        file_fields: Sequence[str],
        data: Any,
        kwargs: dict,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Split the arguments of an upload into form fields and file parts.

        File objects must not go through pydantic, which would consume streams
        and mangle tuples, so a placeholder takes their place during validation.
        """
        body = kwargs if data is UNSET else data
        if isinstance(body, BaseModel):
            files = {
                name: getattr(body, name)
                for name in file_fields
                if name in body.model_fields_set
            }
            body = body.model_copy(update=dict.fromkeys(files, ""))
        else:
            files = {
                name: body[name]
                for name in file_fields
                if body.get(name, UNSET) is not UNSET
            }
            body = {**body, **dict.fromkeys(files, "")}

        form = self.build_body(model, body, {})
        for name in files:
            form.pop(name, None)
        return {
            # Multipart values are text: anything else travels as JSON.
            k: v if isinstance(v, str) else jsonlib.dumps(v, ensure_ascii=False)
            for k, v in form.items()
            if v is not None
        }, files

    # sync request
    def _request(
        self,
        method: str,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        content: ContentTypes | None = None,
        data: dict | None = None,
        files: RequestFiles | None = None,
        json: Any | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        stream: bool = False,
        timeout: TimeoutTypes | UnsetType = UNSET,
        token_types: tuple[TokenType, ...] | None = None,
    ) -> httpx2.Response:
        with self.get_sync_client() as client:
            request = client.build_request(
                method,
                url,
                params=params,
                content=content,
                data=data,
                files=files,
                json=to_jsonable_python(json),
                headers=headers,
                cookies=cookies,
                timeout=httpx2.USE_CLIENT_DEFAULT if timeout is UNSET else timeout,
                extensions={TOKEN_TYPES_EXTENSION: token_types},
            )
            with self.config.throttler.acquire(request):
                try:
                    return client.send(request, stream=stream)
                except httpx2.TimeoutException as e:
                    raise RequestTimeout(e) from e
                except FeishuException:
                    raise
                except Exception as e:
                    raise RequestError(e) from e

    # async request
    async def _arequest(
        self,
        method: str,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        content: ContentTypes | None = None,
        data: dict | None = None,
        files: RequestFiles | None = None,
        json: Any | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        stream: bool = False,
        timeout: TimeoutTypes | UnsetType = UNSET,
        token_types: tuple[TokenType, ...] | None = None,
    ) -> httpx2.Response:
        async with self.get_async_client() as client:
            request = client.build_request(
                method,
                url,
                params=params,
                content=content,
                data=data,
                files=files,
                json=to_jsonable_python(json),
                headers=headers,
                cookies=cookies,
                timeout=httpx2.USE_CLIENT_DEFAULT if timeout is UNSET else timeout,
                extensions={TOKEN_TYPES_EXTENSION: token_types},
            )
            async with self.config.throttler.async_acquire(request):
                try:
                    return await client.send(request, stream=stream)
                except httpx2.TimeoutException as e:
                    raise RequestTimeout(e) from e
                except FeishuException:
                    raise
                except Exception as e:
                    raise RequestError(e) from e

    # check and parse response
    def _needs_body(self, response: httpx2.Response) -> bool:
        """Whether a streamed response has to be read to judge its outcome."""
        return response.is_error or "json" in response.headers.get("content-type", "")

    def _check(
        self,
        response: httpx2.Response,
        response_model: Any = UNSET,
        *,
        data_key: str | None = "data",
    ) -> Response[Any]:
        resp = Response(
            response,
            Any if response_model is UNSET else response_model,
            data_key=data_key,
        )
        code = resp.code

        if response.status_code == 429 or code in RATE_LIMIT_CODES:
            raise RateLimitExceeded(resp, self._extract_retry_after(resp))
        # Feishu reports most failures as HTTP 200 with a non-zero `code`.
        if response.is_error or code:
            raise RequestFailed(resp)
        return resp

    def _extract_retry_after(self, response: Response[Any]) -> timedelta:
        for header in ("x-ogw-ratelimit-reset", "retry-after"):
            try:
                return timedelta(seconds=int(response.headers[header]))
            except (KeyError, ValueError):
                continue
        return DEFAULT_RETRY_AFTER

    # sync request and check
    @overload
    def request(
        self,
        method: str,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        content: ContentTypes | None = None,
        data: dict | None = None,
        files: RequestFiles | None = None,
        json: Any | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        stream: bool = False,
        timeout: TimeoutTypes | UnsetType = UNSET,
        token_types: tuple[TokenType, ...] | None = None,
        response_model: TypeForm[T],
        data_key: str | None = "data",
    ) -> Response[T]: ...

    @overload
    def request(
        self,
        method: str,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        content: ContentTypes | None = None,
        data: dict | None = None,
        files: RequestFiles | None = None,
        json: Any | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        stream: bool = False,
        timeout: TimeoutTypes | UnsetType = UNSET,
        token_types: tuple[TokenType, ...] | None = None,
        response_model: UnsetType = UNSET,
        data_key: str | None = "data",
    ) -> Response[Any]: ...

    def request(
        self,
        method: str,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        content: ContentTypes | None = None,
        data: dict | None = None,
        files: RequestFiles | None = None,
        json: Any | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        stream: bool = False,
        timeout: TimeoutTypes | UnsetType = UNSET,
        token_types: tuple[TokenType, ...] | None = None,
        response_model: TypeForm[T] | UnsetType = UNSET,
        data_key: str | None = "data",
    ) -> Response[T] | Response[Any]:
        """Send a request.

        Response will be checked and the request will be retried if necessary.
        `timeout` replaces the client's for this call, `None` turns it off. It
        applies to each attempt, and to fetching the token the call needs.
        """
        retry_count: int = 0
        while True:
            try:
                raw_resp = self._request(
                    method,
                    url,
                    params=params,
                    content=content,
                    data=data,
                    files=files,
                    json=json,
                    headers=headers,
                    cookies=cookies,
                    stream=stream,
                    timeout=timeout,
                    token_types=token_types,
                )
                if stream and self._needs_body(raw_resp):
                    raw_resp.read()
                return self._check(raw_resp, response_model, data_key=data_key)
            except FeishuException as e:
                if self.config.auto_retry is None:
                    raise

                do_retry, retry_after = self.config.auto_retry(e, retry_count)
                if not do_retry:
                    raise

                time.sleep(retry_after.total_seconds() if retry_after else 1)
                retry_count += 1

    # async request and check
    @overload
    async def arequest(
        self,
        method: str,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        content: ContentTypes | None = None,
        data: dict | None = None,
        files: RequestFiles | None = None,
        json: Any | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        stream: bool = False,
        timeout: TimeoutTypes | UnsetType = UNSET,
        token_types: tuple[TokenType, ...] | None = None,
        response_model: TypeForm[T],
        data_key: str | None = "data",
    ) -> Response[T]: ...

    @overload
    async def arequest(
        self,
        method: str,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        content: ContentTypes | None = None,
        data: dict | None = None,
        files: RequestFiles | None = None,
        json: Any | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        stream: bool = False,
        timeout: TimeoutTypes | UnsetType = UNSET,
        token_types: tuple[TokenType, ...] | None = None,
        response_model: UnsetType = UNSET,
        data_key: str | None = "data",
    ) -> Response[Any]: ...

    async def arequest(
        self,
        method: str,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        content: ContentTypes | None = None,
        data: dict | None = None,
        files: RequestFiles | None = None,
        json: Any | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        stream: bool = False,
        timeout: TimeoutTypes | UnsetType = UNSET,
        token_types: tuple[TokenType, ...] | None = None,
        response_model: TypeForm[T] | UnsetType = UNSET,
        data_key: str | None = "data",
    ) -> Response[T] | Response[Any]:
        """Asynchronously send a request.

        Response will be checked and the request will be retried if necessary.
        `timeout` replaces the client's for this call, `None` turns it off. It
        applies to each attempt, and to fetching the token the call needs.
        """
        retry_count: int = 0
        while True:
            try:
                raw_resp = await self._arequest(
                    method,
                    url,
                    params=params,
                    content=content,
                    data=data,
                    files=files,
                    json=json,
                    headers=headers,
                    cookies=cookies,
                    stream=stream,
                    timeout=timeout,
                    token_types=token_types,
                )
                if stream and self._needs_body(raw_resp):
                    await raw_resp.aread()
                return self._check(raw_resp, response_model, data_key=data_key)
            except FeishuException as e:
                if self.config.auto_retry is None:
                    raise

                do_retry, retry_after = self.config.auto_retry(e, retry_count)
                if not do_retry:
                    raise

                await anyio.sleep(retry_after.total_seconds() if retry_after else 1)
                retry_count += 1
