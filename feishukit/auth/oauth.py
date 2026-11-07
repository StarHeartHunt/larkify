from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar

import httpx2

from feishukit.exception import AuthCredentialError, AuthExpiredError
from feishukit.typing import TokenType

from .base import (
    BaseAuthStrategy,
    CallHook,
    FeishuAuth,
    LockAcquire,
    LockRelease,
    Locks,
    TokenFlow,
    build_token_request,
    parse_token_response,
)

if TYPE_CHECKING:
    from feishukit import FeishuCore

OAUTH_TOKEN_PATH = "oauth/v3/token"

# Refresh ahead of the deadline: the server rejects a token that has expired.
EXPIRY_MARGIN = timedelta(minutes=1)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class OAuthToken:
    """What the token endpoint issued. Passed to `on_refresh`."""

    token: str = field(repr=False)
    expire_time: datetime | None
    refresh_token: str | None = field(repr=False)
    refresh_token_expire_time: datetime | None
    scope: str | None


@dataclass
class OAuthTokenAuth(FeishuAuth):
    """User access token auth hook"""

    feishu: "FeishuCore" = field(repr=False)
    strategy: "OAuthTokenAuthStrategy"

    token_types: ClassVar[tuple[TokenType, ...]] = ("user",)

    @property
    def refreshable(self) -> bool:
        return self.strategy.can_refresh

    @property
    def locks(self) -> Locks:
        return self.strategy._locks

    def token_flow(
        self, request: httpx2.Request, token_type: TokenType, *, refresh: bool
    ) -> TokenFlow:
        strategy = self.strategy
        if not refresh and strategy.is_usable():
            assert strategy.token is not None
            return strategy.token

        yield LockAcquire()
        # Refresh tokens work once. Whoever held the lock may have refreshed
        # already, and spending the new refresh token as well would log the user
        # out. Only the token this request actually sent counts as rejected.
        sent = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if strategy.is_usable() and (not refresh or strategy.token != sent):
            yield LockRelease()
            assert strategy.token is not None
            return strategy.token

        response = yield strategy.build_grant_request(self.feishu, request)
        data = parse_token_response(self.feishu, response, "user_access_token")
        issued = strategy.apply_grant(data)
        if strategy.on_refresh is not None:
            yield CallHook(strategy.on_refresh, issued)
        yield LockRelease()
        return issued.token


@dataclass
class OAuthTokenAuthStrategy(BaseAuthStrategy):
    """User access token, refreshed automatically when a refresh token is known.

    Refresh tokens are single use and the replacement is only returned once.
    Persist it through `on_refresh`, or the user has to authorize again after
    the process restarts. The callback may be a coroutine function when the
    client is used asynchronously.
    """

    app_id: str
    app_secret: str = field(repr=False)
    token: str | None = field(repr=False)
    expire_time: datetime | None = None
    refresh_token: str | None = field(default=None, repr=False)
    refresh_token_expire_time: datetime | None = None
    on_refresh: Callable[[OAuthToken], Any] | None = None

    _locks: Locks = field(default_factory=Locks, init=False, repr=False, compare=False)

    @property
    def can_refresh(self) -> bool:
        return self.refresh_token is not None

    def is_usable(self) -> bool:
        if self.token is None:
            return False
        return self.expire_time is None or (
            self.expire_time - EXPIRY_MARGIN > _utcnow()
        )

    def _grant_body(self) -> dict[str, str]:
        if self.refresh_token is None:
            raise AuthExpiredError(
                "user_access_token expired and no refresh_token is available"
            )
        if (
            self.refresh_token_expire_time is not None
            and self.refresh_token_expire_time <= _utcnow()
        ):
            raise AuthExpiredError("refresh_token expired, the user must authorize")
        return {"grant_type": "refresh_token", "refresh_token": self.refresh_token}

    def build_grant_request(
        self, feishu: "FeishuCore", request: httpx2.Request | None = None
    ) -> httpx2.Request:
        base_url = feishu.config.oauth_base_url
        if base_url is None:
            raise AuthCredentialError("`oauth_base_url` is not configured")
        return build_token_request(
            feishu,
            base_url.join(OAUTH_TOKEN_PATH),
            request=request,
            data={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                **self._grant_body(),
            },
        )

    def apply_grant(self, data: dict[str, Any]) -> OAuthToken:
        now = _utcnow()
        expires_in = data.get("expires_in")
        refresh_expires_in = data.get("refresh_token_expires_in")
        self.token = data["access_token"]
        self.expire_time = (
            now + timedelta(seconds=expires_in) if expires_in is not None else None
        )
        self.refresh_token = data.get("refresh_token")
        self.refresh_token_expire_time = (
            now + timedelta(seconds=refresh_expires_in)
            if refresh_expires_in is not None
            else None
        )
        return OAuthToken(
            data["access_token"],
            self.expire_time,
            self.refresh_token,
            self.refresh_token_expire_time,
            data.get("scope"),
        )

    def get_auth_flow(self, feishu: "FeishuCore") -> httpx2.Auth:
        return OAuthTokenAuth(feishu, self)


class OAuthWebAuthStrategy(OAuthTokenAuthStrategy):
    """User access token, obtained from an authorization code.

    The exchange happens on the first request, or explicitly through
    `exchange_token`. Codes are single use as well, so reuse this strategy
    object rather than building a new one from the same code.
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        code: str,
        *,
        redirect_uri: str | None = None,
        code_verifier: str | None = None,
        on_refresh: Callable[[OAuthToken], Any] | None = None,
    ) -> None:
        super().__init__(app_id, app_secret, None, on_refresh=on_refresh)
        self.code = code
        self.redirect_uri = redirect_uri
        self.code_verifier = code_verifier

    @property
    def can_refresh(self) -> bool:
        return self.token is None or super().can_refresh

    def _grant_body(self) -> dict[str, str]:
        if self.token is not None:
            return super()._grant_body()
        body = {"grant_type": "authorization_code", "code": self.code}
        if self.redirect_uri is not None:
            body["redirect_uri"] = self.redirect_uri
        if self.code_verifier is not None:
            body["code_verifier"] = self.code_verifier
        return body

    def exchange_token(self, feishu: "FeishuCore") -> OAuthTokenAuthStrategy:
        """Exchange the code now, and return the resulting token strategy."""
        with feishu.get_sync_client() as client:
            response = client.send(self.build_grant_request(feishu), auth=None)
            response.read()
        return self._exchanged(feishu, response)

    async def async_exchange_token(
        self, feishu: "FeishuCore"
    ) -> OAuthTokenAuthStrategy:
        """Exchange the code now, and return the resulting token strategy."""
        async with feishu.get_async_client() as client:
            response = await client.send(self.build_grant_request(feishu), auth=None)
            await response.aread()
        return self._exchanged(feishu, response)

    def _exchanged(
        self, feishu: "FeishuCore", response: httpx2.Response
    ) -> OAuthTokenAuthStrategy:
        data = parse_token_response(feishu, response, "user_access_token")
        self.apply_grant(data)
        return OAuthTokenAuthStrategy(
            self.app_id,
            self.app_secret,
            self.token,
            self.expire_time,
            self.refresh_token,
            self.refresh_token_expire_time,
            self.on_refresh,
        )
