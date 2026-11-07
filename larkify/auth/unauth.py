from collections.abc import Generator
from typing import TYPE_CHECKING

import httpx2

from .base import BaseAuthStrategy

if TYPE_CHECKING:
    from larkify import FeishuCore


class UnauthAuth(httpx2.Auth):
    """Send requests without an access token"""

    def auth_flow(
        self, request: httpx2.Request
    ) -> Generator[httpx2.Request, httpx2.Response, None]:
        yield request


class UnauthAuthStrategy(BaseAuthStrategy):
    """Send requests without an access token"""

    def get_auth_flow(self, feishu: "FeishuCore") -> httpx2.Auth:
        return UnauthAuth()
