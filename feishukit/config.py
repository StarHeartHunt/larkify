from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any, Self

import httpx2

from .cache import DEFAULT_CACHE_STRATEGY, BaseCacheStrategy
from .retry import RETRY_DEFAULT
from .throttling import BaseThrottler, LocalThrottler
from .typing import EventHookTypes, ProxyTypes, RetryDecisionFunc

if TYPE_CHECKING:
    import ssl

FEISHU_BASE_URL = "https://open.feishu.cn/"
LARK_BASE_URL = "https://open.larksuite.com/"
FEISHU_OAUTH_BASE_URL = "https://accounts.feishu.cn/"
LARK_OAUTH_BASE_URL = "https://accounts.larksuite.com/"

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_CONCURRENCY = 100

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True)
class Config:
    base_url: httpx2.URL
    oauth_base_url: httpx2.URL | None
    user_agent: str
    follow_redirects: bool
    timeout: httpx2.Timeout
    ssl_verify: "bool | ssl.SSLContext"
    trust_env: bool  # effects the `httpx2` proxy and ssl cert
    proxy: ProxyTypes | None
    transport: httpx2.BaseTransport | None
    async_transport: httpx2.AsyncBaseTransport | None
    event_hooks: EventHookTypes | None
    async_event_hooks: EventHookTypes | None
    cache_strategy: BaseCacheStrategy
    throttler: BaseThrottler
    auto_retry: RetryDecisionFunc | None
    rest_api_validate_body: bool

    def dict(self) -> dict[str, Any]:
        """Return the config as a dictionary without copy values."""
        return {field.name: getattr(self, field.name) for field in fields(self)}

    def copy(self) -> Self:
        """Return a shallow copy of the config."""
        return self.__class__(**self.dict())


def _build_origin_url(url: str | httpx2.URL) -> httpx2.URL:
    """Validate a URL that credentials are going to be sent to."""
    url = url if isinstance(url, httpx2.URL) else httpx2.URL(url)

    if url.scheme != "https" and not (
        url.scheme == "http" and url.host in _LOOPBACK_HOSTS
    ):
        raise ValueError(f"url must use https: {url}")
    if url.userinfo:
        raise ValueError("url must not embed credentials")

    # enforce trailing slash
    if not url.raw_path.endswith(b"/"):
        url = url.copy_with(raw_path=url.raw_path + b"/")
    return url


def build_base_url(base_url: str | httpx2.URL | None) -> httpx2.URL:
    return _build_origin_url(base_url or FEISHU_BASE_URL)


def build_oauth_base_url(
    oauth_base_url: str | httpx2.URL | None, base_url: httpx2.URL
) -> httpx2.URL | None:
    if oauth_base_url:
        return _build_origin_url(oauth_base_url)
    if base_url.host == httpx2.URL(FEISHU_BASE_URL).host:
        return httpx2.URL(FEISHU_OAUTH_BASE_URL)
    if base_url.host == httpx2.URL(LARK_BASE_URL).host:
        return httpx2.URL(LARK_OAUTH_BASE_URL)
    # A private deployment has its own accounts host, which cannot be guessed.
    return None


def build_user_agent(user_agent: str | None = None) -> str:
    return user_agent or "feishu-kit/Python"


def build_timeout(timeout: float | httpx2.Timeout | None = None) -> httpx2.Timeout:
    if isinstance(timeout, httpx2.Timeout):
        return timeout
    return httpx2.Timeout(DEFAULT_TIMEOUT if timeout is None else timeout)


def build_cache_strategy(
    cache_strategy: BaseCacheStrategy | None,
) -> BaseCacheStrategy:
    return cache_strategy or DEFAULT_CACHE_STRATEGY


def build_throttler(throttler: BaseThrottler | None) -> BaseThrottler:
    return throttler or LocalThrottler(DEFAULT_MAX_CONCURRENCY)


def build_auto_retry(
    auto_retry: bool | RetryDecisionFunc = True,
) -> RetryDecisionFunc | None:
    if auto_retry is True:
        return RETRY_DEFAULT
    return auto_retry or None


def get_config(
    *,
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
) -> Config:
    """Build the configs from the given options."""
    url = build_base_url(base_url)
    return Config(
        url,
        build_oauth_base_url(oauth_base_url, url),
        build_user_agent(user_agent),
        follow_redirects,
        build_timeout(timeout),
        ssl_verify,
        trust_env,
        proxy,
        transport,
        async_transport,
        event_hooks,
        async_event_hooks,
        build_cache_strategy(cache_strategy),
        build_throttler(throttler),
        build_auto_retry(auto_retry),
        rest_api_validate_body,
    )
