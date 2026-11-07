from collections.abc import Callable
import json
from typing import Any

import httpx2
import pytest

from feishukit import AppAuthStrategy, Feishu
from feishukit.cache import MemCacheStrategy

OAUTH_TOKEN_URL = "https://accounts.feishu.cn/oauth/v3/token"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def ok(data: Any = None, **headers: str) -> httpx2.Response:
    return httpx2.Response(
        200, json={"code": 0, "msg": "success", "data": data or {}}, headers=headers
    )


def oauth_token(token: str = "tenant-jwt", expires_in: int = 7200) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "code": 0,
            "access_token": token,
            "expires_in": expires_in,
            "token_type": "Bearer",
        },
    )


class Server:
    """A fake Feishu: token endpoints answered, API calls recorded and routed."""

    def __init__(self, api: Callable[[httpx2.Request], httpx2.Response]) -> None:
        self.api = api
        self.requests: list[httpx2.Request] = []
        # Auth flows resend the same object, so headers are captured on arrival.
        self.authorizations: list[str | None] = []
        self.token_requests: list[httpx2.Request] = []
        self.tokens = iter(f"tenant-{n}" for n in range(1, 100))

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == OAUTH_TOKEN_URL:
            self.token_requests.append(request)
            return oauth_token(next(self.tokens))
        self.requests.append(request)
        self.authorizations.append(request.headers.get("authorization"))
        return self.api(request)

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self)

    @property
    def last_json(self) -> Any:
        return json.loads(self.requests[-1].content)


@pytest.fixture
def make_client():
    def factory(
        api: Callable[[httpx2.Request], httpx2.Response], **options: Any
    ) -> tuple[Feishu, Server]:
        server = Server(api)
        options.setdefault("auto_retry", False)
        auth = options.pop("auth", AppAuthStrategy("cli_test", "secret"))
        feishu = Feishu(
            auth,
            transport=server.transport,
            async_transport=server.transport,
            cache_strategy=MemCacheStrategy(),
            **options,
        )
        return feishu, server

    return factory
