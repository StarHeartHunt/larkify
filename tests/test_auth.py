from datetime import UTC, datetime, timedelta
import threading

import anyio
import httpx2
import pytest

from feishukit import (
    AppAuthStrategy,
    Feishu,
    IsvAppAuthStrategy,
    OAuthTokenAuthStrategy,
    OAuthWebAuthStrategy,
    TokenAuthStrategy,
)
from feishukit.cache import MemCacheStrategy
from feishukit.exception import (
    AuthCredentialError,
    AuthExpiredError,
    RequestFailed,
)

from .conftest import OAUTH_TOKEN_URL, oauth_token, ok


def rejected(code: int = 99991663) -> httpx2.Response:
    return httpx2.Response(400, json={"code": code, "msg": "Invalid access token"})


def get_message(feishu):
    return feishu.rest.im.v1.message.get("om_1")


def test_tenant_token_comes_from_the_oauth_endpoint(make_client):
    feishu, server = make_client(lambda r: ok())

    get_message(feishu)

    assert dict(httpx2.QueryParams(server.token_requests[0].content.decode())) == {
        "grant_type": "client_credentials",
        "client_id": "cli_test",
        "client_secret": "secret",
    }
    assert server.requests[0].headers["authorization"] == "Bearer tenant-1"


def test_token_is_reused(make_client):
    feishu, server = make_client(lambda r: ok())

    get_message(feishu)
    get_message(feishu)

    assert len(server.token_requests) == 1


def test_token_is_shared_across_with_auth_copies(make_client):
    feishu, server = make_client(lambda r: ok())

    get_message(feishu)
    get_message(feishu.with_auth(AppAuthStrategy("cli_test", "secret")))

    assert len(server.token_requests) == 1


def test_short_lived_token_is_not_cached(make_client):
    class Short:
        calls = 0

        def __call__(self, request):
            if str(request.url) == OAUTH_TOKEN_URL:
                Short.calls += 1
                return oauth_token(expires_in=60)
            return ok()

    feishu = Feishu(
        AppAuthStrategy("cli_test", "secret"),
        transport=httpx2.MockTransport(Short()),
        cache_strategy=MemCacheStrategy(),
    )
    get_message(feishu)
    get_message(feishu)

    assert Short.calls == 2


def test_legacy_tenant_token_api():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx2.Response(
                200, json={"code": 0, "tenant_access_token": "t-1", "expire": 7200}
            )
        return ok()

    feishu = Feishu(
        AppAuthStrategy("cli_test", "secret", tenant_token_api="legacy"),
        transport=httpx2.MockTransport(handler),
        cache_strategy=MemCacheStrategy(),
    )
    get_message(feishu)

    assert seen[1].headers["authorization"] == "Bearer t-1"


def test_private_deployment_without_accounts_host_uses_the_legacy_api():
    seen = []

    def handler(request):
        seen.append(request)
        if "tenant_access_token" in request.url.path:
            return httpx2.Response(
                200, json={"code": 0, "tenant_access_token": "t-1", "expire": 7200}
            )
        return ok()

    feishu = Feishu(
        AppAuthStrategy("cli_test", "secret"),
        base_url="https://open.example.com",
        transport=httpx2.MockTransport(handler),
        cache_strategy=MemCacheStrategy(),
    )
    get_message(feishu)

    assert seen[0].url.host == "open.example.com"


def test_lark_uses_the_lark_accounts_host():
    from feishukit import LARK_BASE_URL

    feishu = Feishu("t-x", base_url=LARK_BASE_URL)

    assert feishu.config.oauth_base_url.host == "accounts.larksuite.com"


def test_app_token_used_where_only_app_is_accepted():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/app_access_token/internal"):
            return httpx2.Response(
                200, json={"code": 0, "app_access_token": "a-1", "expire": 7200}
            )
        return ok()

    feishu = Feishu(
        AppAuthStrategy("cli_test", "secret"),
        transport=httpx2.MockTransport(handler),
        cache_strategy=MemCacheStrategy(),
    )
    feishu.rest.authen.v1.oidc_refresh_access_token.create(
        grant_type="refresh_token", refresh_token="r"
    )

    assert seen[1].headers["authorization"] == "Bearer a-1"


def test_api_taking_no_token_gets_none(make_client):
    feishu, server = make_client(
        lambda r: httpx2.Response(
            200, json={"code": 0, "tenant_access_token": "t", "expire": 7200}
        )
    )

    feishu.rest.auth.v3.auth.tenant_access_token_internal(app_id="a", app_secret="b")

    assert "authorization" not in server.requests[0].headers
    assert server.token_requests == []


def test_user_only_api_needs_a_user_identity(make_client):
    feishu, server = make_client(lambda r: ok())

    with pytest.raises(AuthCredentialError, match="user"):
        feishu.rest.authen.v1.user_info.get()

    assert server.requests == []


def test_bad_credentials_are_reported(make_client):
    def handler(request):
        return httpx2.Response(
            400,
            json={
                "code": 20002,
                "error": "invalid_client",
                "error_description": "The client secret is invalid.",
            },
        )

    feishu = Feishu(
        AppAuthStrategy("cli_test", "wrong"),
        transport=httpx2.MockTransport(handler),
        cache_strategy=MemCacheStrategy(),
        auto_retry=False,
    )

    with pytest.raises(AuthCredentialError, match="client secret is invalid"):
        get_message(feishu)


def test_rejected_token_is_replaced_once(make_client):
    answers = iter([rejected(), ok({})])
    feishu, server = make_client(lambda r: next(answers))

    get_message(feishu)

    assert server.authorizations == ["Bearer tenant-1", "Bearer tenant-2"]


def test_token_rejected_twice_is_surfaced(make_client):
    feishu, server = make_client(lambda r: rejected())

    with pytest.raises(RequestFailed) as info:
        get_message(feishu)

    assert info.value.code == 99991663
    assert len(server.requests) == 2


def test_other_errors_do_not_replace_the_token(make_client):
    feishu, server = make_client(
        lambda r: httpx2.Response(400, json={"code": 230001, "msg": "bad"})
    )

    with pytest.raises(RequestFailed):
        get_message(feishu)

    assert len(server.token_requests) == 1
    assert len(server.requests) == 1


def test_fixed_token_is_sent_as_is_and_never_replaced(make_client):
    feishu, server = make_client(lambda r: rejected(), auth=TokenAuthStrategy("t-abc"))

    with pytest.raises(RequestFailed):
        get_message(feishu)

    assert server.requests[0].headers["authorization"] == "Bearer t-abc"
    assert len(server.requests) == 1


def test_string_auth_is_a_fixed_token():
    feishu = Feishu("u-abc")

    assert isinstance(feishu.auth, TokenAuthStrategy)
    assert feishu.auth.token_type == "user"


@pytest.mark.parametrize(
    "strategy",
    [
        AppAuthStrategy("cli_test", "very-secret"),
        IsvAppAuthStrategy("cli_test", "very-secret", app_ticket="very-secret"),
        OAuthTokenAuthStrategy("cli_test", "very-secret", "very-secret"),
        OAuthWebAuthStrategy("cli_test", "very-secret", "code"),
        TokenAuthStrategy("very-secret"),
    ],
)
def test_secrets_stay_out_of_repr(strategy):
    assert "very-secret" not in repr(strategy)


def oauth_server(*tokens):
    state = {"grants": [], "api": []}
    issued = iter(tokens)

    def handler(request):
        if str(request.url) == OAUTH_TOKEN_URL:
            state["grants"].append(dict(httpx2.QueryParams(request.content.decode())))
            token, refresh = next(issued)
            return httpx2.Response(
                200,
                json={
                    "code": 0,
                    "access_token": token,
                    "expires_in": 7200,
                    "refresh_token": refresh,
                    "refresh_token_expires_in": 604800,
                    "scope": "offline_access",
                },
            )
        state["api"].append(request)
        return ok({"name": "someone"})

    return handler, state


def client_for(strategy, handler):
    return Feishu(
        strategy,
        transport=httpx2.MockTransport(handler),
        async_transport=httpx2.MockTransport(handler),
        cache_strategy=MemCacheStrategy(),
        auto_retry=False,
    )


def expired_strategy(**options):
    return OAuthTokenAuthStrategy(
        "cli_test",
        "secret",
        "u-old",
        expire_time=datetime.now(UTC) - timedelta(minutes=5),
        refresh_token="r-1",
        **options,
    )


def test_expired_user_token_is_refreshed_and_rotated():
    handler, state = oauth_server(("u-new", "r-2"), ("u-newer", "r-3"))
    strategy = expired_strategy()
    feishu = client_for(strategy, handler)

    feishu.rest.authen.v1.user_info.get()

    assert state["grants"][0]["grant_type"] == "refresh_token"
    assert state["grants"][0]["refresh_token"] == "r-1"
    assert state["api"][0].headers["authorization"] == "Bearer u-new"
    assert strategy.refresh_token == "r-2"

    # A per-request client must not lose the rotated token.
    strategy.expire_time = datetime.now(UTC) - timedelta(minutes=5)
    feishu.rest.authen.v1.user_info.get()

    assert state["grants"][1]["refresh_token"] == "r-2"


def test_on_refresh_receives_the_new_tokens():
    handler, _ = oauth_server(("u-new", "r-2"))
    saved = []
    feishu = client_for(expired_strategy(on_refresh=saved.append), handler)

    feishu.rest.authen.v1.user_info.get()

    assert saved[0].token == "u-new"
    assert saved[0].refresh_token == "r-2"


@pytest.mark.anyio
async def test_async_on_refresh_is_awaited():
    handler, _ = oauth_server(("u-new", "r-2"))
    saved = []

    async def save(token):
        saved.append(token)

    feishu = client_for(expired_strategy(on_refresh=save), handler)

    await feishu.rest.authen.v1.user_info.async_get()

    assert saved[0].refresh_token == "r-2"


def test_concurrent_threads_spend_the_refresh_token_once():
    handler, state = oauth_server(("u-new", "r-2"), ("u-bad", "r-bad"))
    feishu = client_for(expired_strategy(), handler)

    threads = [
        threading.Thread(target=feishu.rest.authen.v1.user_info.get) for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(state["grants"]) == 1
    assert {r.headers["authorization"] for r in state["api"]} == {"Bearer u-new"}


@pytest.mark.anyio
async def test_concurrent_tasks_spend_the_refresh_token_once():
    handler, state = oauth_server(("u-new", "r-2"), ("u-bad", "r-bad"))
    feishu = client_for(expired_strategy(), handler)

    async with anyio.create_task_group() as tasks:
        for _ in range(8):
            tasks.start_soon(feishu.rest.authen.v1.user_info.async_get)

    assert len(state["grants"]) == 1


def test_user_token_rejected_by_the_server_is_refreshed():
    state = {"grants": 0, "seen": []}

    def handler(request):
        if str(request.url) == OAUTH_TOKEN_URL:
            state["grants"] += 1
            return httpx2.Response(
                200,
                json={
                    "code": 0,
                    "access_token": "u-new",
                    "expires_in": 7200,
                    "refresh_token": "r-2",
                },
            )
        state["seen"].append(request.headers["authorization"])
        if request.headers["authorization"] == "Bearer u-old":
            return rejected(99991677)
        return ok()

    strategy = OAuthTokenAuthStrategy(
        "cli_test", "secret", "u-old", refresh_token="r-1"
    )
    client_for(strategy, handler).rest.authen.v1.user_info.get()

    assert state == {"grants": 1, "seen": ["Bearer u-old", "Bearer u-new"]}


def test_user_token_without_refresh_token_fails_cleanly():
    strategy = OAuthTokenAuthStrategy(
        "cli_test",
        "secret",
        "u-old",
        expire_time=datetime.now(UTC) - timedelta(minutes=5),
    )
    handler, _ = oauth_server()

    with pytest.raises(AuthExpiredError):
        client_for(strategy, handler).rest.authen.v1.user_info.get()


def test_expired_refresh_token_fails_cleanly():
    strategy = expired_strategy()
    strategy.refresh_token_expire_time = datetime.now(UTC) - timedelta(days=1)
    handler, state = oauth_server()

    with pytest.raises(AuthExpiredError):
        client_for(strategy, handler).rest.authen.v1.user_info.get()

    assert state["grants"] == []


def test_failed_refresh_releases_the_lock():
    def handler(request):
        return httpx2.Response(
            400,
            json={"code": 20064, "error": "invalid_grant", "error_description": "no"},
        )

    strategy = expired_strategy()
    feishu = client_for(strategy, handler)

    for _ in range(2):
        with pytest.raises(AuthCredentialError):
            feishu.rest.authen.v1.user_info.get()

    assert not strategy._locks.sync.locked()


def test_authorization_code_is_exchanged_on_first_use():
    handler, state = oauth_server(("u-1", "r-1"))
    auth = AppAuthStrategy("cli_test", "secret").as_web_user(
        "the-code", "https://example.com/callback", code_verifier="verifier"
    )
    feishu = client_for(auth, handler)

    feishu.rest.authen.v1.user_info.get()
    feishu.rest.authen.v1.user_info.get()

    assert len(state["grants"]) == 1
    assert state["grants"][0] == {
        "client_id": "cli_test",
        "client_secret": "secret",
        "grant_type": "authorization_code",
        "code": "the-code",
        "redirect_uri": "https://example.com/callback",
        "code_verifier": "verifier",
    }


def test_explicit_exchange_returns_a_token_strategy():
    handler, _ = oauth_server(("u-1", "r-1"))
    auth = OAuthWebAuthStrategy("cli_test", "secret", "the-code")

    token = auth.exchange_token(client_for(auth, handler))

    assert isinstance(token, OAuthTokenAuthStrategy)
    assert (token.token, token.refresh_token) == ("u-1", "r-1")


@pytest.mark.anyio
async def test_async_explicit_exchange():
    handler, _ = oauth_server(("u-1", "r-1"))
    auth = OAuthWebAuthStrategy("cli_test", "secret", "the-code")

    token = await auth.async_exchange_token(client_for(auth, handler))

    assert token.token == "u-1"


def test_authorize_url():
    auth = AppAuthStrategy("cli_test", "secret")

    url = httpx2.URL(
        auth.get_authorize_url(
            Feishu(auth),
            "https://example.com/cb",
            scope="offline_access",
            state="xyz",
        )
    )

    assert url.host == "accounts.feishu.cn"
    assert url.path == "/open-apis/authen/v1/authorize"
    assert url.params["client_id"] == "cli_test"
    assert url.params["redirect_uri"] == "https://example.com/cb"


def isv_handler(state):
    def handler(request):
        state.append(request)
        path = request.url.path
        if path.endswith("/app_access_token"):
            return httpx2.Response(
                200, json={"code": 0, "app_access_token": "a-1", "expire": 7200}
            )
        if path.endswith("/tenant_access_token"):
            return httpx2.Response(
                200, json={"code": 0, "tenant_access_token": "t-1", "expire": 7200}
            )
        return ok()

    return handler


def test_isv_tenant_token_flow():
    import json

    seen = []
    auth = IsvAppAuthStrategy("cli_test", "secret", app_ticket="ticket")
    feishu = client_for(auth.as_tenant("tenant-1"), isv_handler(seen))

    get_message(feishu)

    assert json.loads(seen[0].content)["app_ticket"] == "ticket"
    assert json.loads(seen[1].content) == {
        "app_access_token": "a-1",
        "tenant_key": "tenant-1",
    }
    assert seen[2].headers["authorization"] == "Bearer t-1"


def test_isv_ticket_can_come_from_the_cache():
    seen = []
    auth = IsvAppAuthStrategy("cli_test", "secret", tenant_key="tenant-1")
    feishu = client_for(auth, isv_handler(seen))

    auth.save_app_ticket(feishu, "pushed-ticket")
    get_message(feishu)

    assert b"pushed-ticket" in seen[0].content


def test_isv_without_a_ticket_says_what_to_do():
    auth = IsvAppAuthStrategy("cli_test", "secret", tenant_key="tenant-1")
    feishu = client_for(auth, isv_handler([]))

    with pytest.raises(AuthCredentialError, match="app_ticket"):
        get_message(feishu)


def test_isv_without_a_tenant_cannot_call_tenant_only_apis():
    auth = IsvAppAuthStrategy("cli_test", "secret", app_ticket="ticket")
    feishu = client_for(auth, isv_handler([]))

    with pytest.raises(AuthCredentialError, match="as_tenant"):
        feishu.rest.contact.v3.user.get("ou_1")


@pytest.mark.parametrize(
    "url",
    ["http://open.feishu.cn", "https://user:pass@open.feishu.cn", "ftp://x.example"],
)
def test_credentials_are_not_sent_to_unsafe_urls(url):
    with pytest.raises(ValueError):
        Feishu("t-x", base_url=url)


def test_plain_http_is_fine_for_a_local_gateway():
    assert Feishu("t-x", base_url="http://127.0.0.1:8080").config.base_url
