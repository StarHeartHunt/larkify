from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, ClassVar, Literal
from urllib.parse import urlencode

import httpx2

from feishukit.exception import AuthCredentialError
from feishukit.typing import TokenType

from .base import (
    BaseAuthStrategy,
    CacheDelete,
    CacheGet,
    CacheSet,
    FeishuAuth,
    TokenFlow,
    build_token_request,
    parse_token_response,
)
from .oauth import OAUTH_TOKEN_PATH, OAuthTokenAuthStrategy, OAuthWebAuthStrategy

if TYPE_CHECKING:
    from feishukit import FeishuCore

# A token is replaced before it runs out, so that a request is never sent with a
# token that expires in flight.
EXPIRY_MARGIN = timedelta(minutes=10)

# Tickets are pushed hourly. A stale one is rejected with a clear error, so it is
# kept long enough to survive a missed delivery.
APP_TICKET_TTL = timedelta(hours=2)

TENANT_TOKEN_INTERNAL_PATH = "open-apis/auth/v3/tenant_access_token/internal"
TENANT_TOKEN_STORE_PATH = "open-apis/auth/v3/tenant_access_token"
APP_TOKEN_INTERNAL_PATH = "open-apis/auth/v3/app_access_token/internal"
APP_TOKEN_STORE_PATH = "open-apis/auth/v3/app_access_token"
APP_TICKET_RESEND_PATH = "open-apis/auth/v3/app_ticket/resend"
AUTHORIZE_PATH = "open-apis/authen/v1/authorize"


def _cache_ttl(expires_in: int) -> timedelta:
    return timedelta(seconds=expires_in) - EXPIRY_MARGIN


class _AppCredentialStrategy(BaseAuthStrategy):
    """User identity entry points shared by both application kinds."""

    app_id: str
    app_secret: str

    def as_oauth_token(
        self,
        token: str,
        *,
        expire_time: datetime | None = None,
        refresh_token: str | None = None,
        refresh_token_expire_time: datetime | None = None,
    ) -> OAuthTokenAuthStrategy:
        """Act as a user, from a stored `user_access_token`."""
        return OAuthTokenAuthStrategy(
            self.app_id,
            self.app_secret,
            token,
            expire_time=expire_time,
            refresh_token=refresh_token,
            refresh_token_expire_time=refresh_token_expire_time,
        )

    def as_web_user(
        self,
        code: str,
        redirect_uri: str | None = None,
        *,
        code_verifier: str | None = None,
    ) -> OAuthWebAuthStrategy:
        """Act as a user, from the code of the authorization redirect."""
        return OAuthWebAuthStrategy(
            self.app_id,
            self.app_secret,
            code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )

    def get_authorize_url(
        self,
        feishu: "FeishuCore",
        redirect_uri: str,
        *,
        scope: str | None = None,
        state: str | None = None,
        code_challenge: str | None = None,
        code_challenge_method: str | None = None,
    ) -> str:
        """Build the URL to send the user to, for the authorization code flow."""
        base_url = feishu.config.oauth_base_url
        if base_url is None:
            raise AuthCredentialError("`oauth_base_url` is not configured")
        params = {
            "client_id": self.app_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        }
        query = urlencode({k: v for k, v in params.items() if v is not None})
        return str(base_url.join(AUTHORIZE_PATH)) + "?" + query


@dataclass
class AppAuth(FeishuAuth):
    """Self-built application auth hook"""

    feishu: "FeishuCore" = field(repr=False)
    app_id: str
    app_secret: str = field(repr=False)
    tenant_token_api: Literal["oauth", "legacy"]

    token_types: ClassVar[tuple[TokenType, ...]] = ("tenant", "app")

    CACHE_KEY: ClassVar[str] = "feishukit:auth:app:{app_id}:{token_type}"

    def _build_oauth_tenant_token_request(
        self, request: httpx2.Request, base_url: httpx2.URL
    ) -> httpx2.Request:
        return build_token_request(
            self.feishu,
            base_url.join(OAUTH_TOKEN_PATH),
            request=request,
            data={
                "grant_type": "client_credentials",
                "client_id": self.app_id,
                "client_secret": self.app_secret,
            },
        )

    def _tenant_token_flow(self, request: httpx2.Request) -> TokenFlow:
        base_url = self.feishu.config.oauth_base_url
        # A private deployment without an accounts host has only the legacy API.
        if self.tenant_token_api == "oauth" and base_url is not None:
            response = yield self._build_oauth_tenant_token_request(request, base_url)
            data = parse_token_response(self.feishu, response, "tenant_access_token")
            yield from self._store("tenant", data["access_token"], data["expires_in"])
            return data["access_token"]

        response = yield build_token_request(
            self.feishu,
            self.feishu.config.base_url.join(TENANT_TOKEN_INTERNAL_PATH),
            request=request,
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        data = parse_token_response(self.feishu, response, "tenant_access_token")
        yield from self._store("tenant", data["tenant_access_token"], data["expire"])
        return data["tenant_access_token"]

    def _app_token_flow(self, request: httpx2.Request) -> TokenFlow:
        response = yield build_token_request(
            self.feishu,
            self.feishu.config.base_url.join(APP_TOKEN_INTERNAL_PATH),
            request=request,
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        data = parse_token_response(self.feishu, response, "app_access_token")
        yield from self._store("app", data["app_access_token"], data["expire"])
        return data["app_access_token"]

    def _cache_key(self, token_type: TokenType) -> str:
        return self.CACHE_KEY.format(app_id=self.app_id, token_type=token_type)

    def _store(self, token_type: TokenType, token: str, expires_in: int):
        if (ttl := _cache_ttl(expires_in)) > timedelta():
            yield CacheSet(self._cache_key(token_type), token, ttl)

    def token_flow(
        self, request: httpx2.Request, token_type: TokenType, *, refresh: bool
    ) -> TokenFlow:
        key = self._cache_key(token_type)
        if refresh:
            yield CacheDelete(key)
        elif token := (yield CacheGet(key)):
            return token

        if token_type == "tenant":
            return (yield from self._tenant_token_flow(request))
        return (yield from self._app_token_flow(request))


@dataclass
class AppAuthStrategy(_AppCredentialStrategy):
    """Self-built application: tenant and app access tokens are automatic.

    `tenant_token_api` selects how the tenant access token is obtained:
    `"oauth"` is the current `POST /oauth/v3/token` client credentials grant,
    which issues JWT tokens of up to about 4 KB. `"legacy"` is the older
    `/open-apis/auth/v3/tenant_access_token/internal`.
    """

    app_id: str
    app_secret: str = field(repr=False)
    tenant_token_api: Literal["oauth", "legacy"] = "oauth"

    def get_auth_flow(self, feishu: "FeishuCore") -> httpx2.Auth:
        return AppAuth(feishu, self.app_id, self.app_secret, self.tenant_token_api)


@dataclass
class IsvAppAuth(FeishuAuth):
    """Store application auth hook"""

    feishu: "FeishuCore" = field(repr=False)
    app_id: str
    app_secret: str = field(repr=False)
    app_ticket: str | None = field(repr=False)
    tenant_key: str | None

    token_types: ClassVar[tuple[TokenType, ...]] = ("tenant", "app")

    APP_KEY: ClassVar[str] = "feishukit:auth:isv:{app_id}:app"
    TENANT_KEY: ClassVar[str] = "feishukit:auth:isv:{app_id}:tenant:{tenant_key}"
    TICKET_KEY: ClassVar[str] = "feishukit:auth:isv:{app_id}:app_ticket"

    def select_token_type(
        self, allowed: tuple[TokenType, ...] | None
    ) -> TokenType | None:
        # Without a tenant, only the application itself can be authenticated.
        if self.tenant_key is None and (allowed is None or "tenant" in allowed):
            if allowed is None or "app" in allowed:
                return "app"
            raise AuthCredentialError(
                "This API needs a tenant, use `auth.as_tenant(tenant_key)`"
            )
        return super().select_token_type(allowed)

    def _app_token_flow(self, request: httpx2.Request, *, refresh: bool) -> TokenFlow:
        key = self.APP_KEY.format(app_id=self.app_id)
        if refresh:
            yield CacheDelete(key)
        elif token := (yield CacheGet(key)):
            return token

        ticket = self.app_ticket or (
            yield CacheGet(self.TICKET_KEY.format(app_id=self.app_id))
        )
        if not ticket:
            raise AuthCredentialError(
                "No app_ticket available. Feishu pushes it hourly as the "
                "`app_ticket` event, store it with `save_app_ticket`, or ask "
                "for one with `feishu.rest.auth.v3.auth.app_ticket_resend`."
            )

        response = yield build_token_request(
            self.feishu,
            self.feishu.config.base_url.join(APP_TOKEN_STORE_PATH),
            request=request,
            json={
                "app_id": self.app_id,
                "app_secret": self.app_secret,
                "app_ticket": ticket,
            },
        )
        data = parse_token_response(self.feishu, response, "app_access_token")
        token = data["app_access_token"]
        if (ttl := _cache_ttl(data["expire"])) > timedelta():
            yield CacheSet(key, token, ttl)
        return token

    def _tenant_token_flow(
        self, request: httpx2.Request, *, refresh: bool
    ) -> TokenFlow:
        key = self.TENANT_KEY.format(app_id=self.app_id, tenant_key=self.tenant_key)
        if refresh:
            yield CacheDelete(key)
        elif token := (yield CacheGet(key)):
            return token

        app_token = yield from self._app_token_flow(request, refresh=False)
        response = yield build_token_request(
            self.feishu,
            self.feishu.config.base_url.join(TENANT_TOKEN_STORE_PATH),
            request=request,
            json={"app_access_token": app_token, "tenant_key": self.tenant_key},
        )
        data = parse_token_response(self.feishu, response, "tenant_access_token")
        token = data["tenant_access_token"]
        if (ttl := _cache_ttl(data["expire"])) > timedelta():
            yield CacheSet(key, token, ttl)
        return token

    def token_flow(
        self, request: httpx2.Request, token_type: TokenType, *, refresh: bool
    ) -> TokenFlow:
        if token_type == "tenant":
            return (yield from self._tenant_token_flow(request, refresh=refresh))
        return (yield from self._app_token_flow(request, refresh=refresh))


@dataclass
class IsvAppAuthStrategy(_AppCredentialStrategy):
    """Store application: tokens are derived from the pushed `app_ticket`.

    Pass `app_ticket` directly, or persist each ticket with `save_app_ticket`
    from the `app_ticket` event handler. Bind a tenant with `as_tenant`.
    """

    app_id: str
    app_secret: str = field(repr=False)
    app_ticket: str | None = field(default=None, repr=False)
    tenant_key: str | None = None

    def as_tenant(self, tenant_key: str) -> "IsvAppAuthStrategy":
        """Act on behalf of the tenant that installed the application."""
        return IsvAppAuthStrategy(
            self.app_id, self.app_secret, self.app_ticket, tenant_key
        )

    def _ticket_key(self) -> str:
        return IsvAppAuth.TICKET_KEY.format(app_id=self.app_id)

    def save_app_ticket(self, feishu: "FeishuCore", app_ticket: str) -> None:
        cache = feishu.config.cache_strategy.get_cache_storage()
        cache.set(self._ticket_key(), app_ticket, APP_TICKET_TTL)

    async def async_save_app_ticket(
        self, feishu: "FeishuCore", app_ticket: str
    ) -> None:
        cache = await feishu.config.cache_strategy.get_async_cache_storage()
        await cache.aset(self._ticket_key(), app_ticket, APP_TICKET_TTL)

    def get_auth_flow(self, feishu: "FeishuCore") -> httpx2.Auth:
        return IsvAppAuth(
            feishu, self.app_id, self.app_secret, self.app_ticket, self.tenant_key
        )
