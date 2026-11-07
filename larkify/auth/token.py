from collections.abc import Generator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx2

from larkify.typing import TokenType

from .base import TOKEN_TYPES_EXTENSION, BaseAuthStrategy

if TYPE_CHECKING:
    from larkify import FeishuCore


_TOKEN_PREFIXES: dict[str, TokenType] = {"t-": "tenant", "a-": "app", "u-": "user"}


@dataclass
class TokenAuth(httpx2.Auth):
    """Fixed access token hook"""

    token: str = field(repr=False)

    def auth_flow(
        self, request: httpx2.Request
    ) -> Generator[httpx2.Request, httpx2.Response, None]:
        # An empty tuple marks the APIs that take no token at all. Anything else
        # is left for the server to judge, this token is all there is to send.
        if request.extensions.get(TOKEN_TYPES_EXTENSION) != ():
            request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


@dataclass
class TokenAuthStrategy(BaseAuthStrategy):
    """Fixed access token, of any type, managed by the caller"""

    token: str = field(repr=False)

    @property
    def token_type(self) -> TokenType | None:
        """Token type read from the prefix. JWT format tokens have none."""
        return _TOKEN_PREFIXES.get(self.token[:2])

    def get_auth_flow(self, feishu: "FeishuCore") -> httpx2.Auth:
        return TokenAuth(self.token)
