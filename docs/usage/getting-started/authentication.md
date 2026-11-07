# 认证

## 认证策略

| 策略 | 场景 |
| --- | --- |
| `AppAuthStrategy(app_id, app_secret)` | 自建应用，自动管理 tenant / app access token |
| `IsvAppAuthStrategy(app_id, app_secret, app_ticket=...)` | 商店应用，用 `.as_tenant(tenant_key)` 绑定租户 |
| `OAuthTokenAuthStrategy(...)` | 用户身份，可自动刷新 |
| `OAuthWebAuthStrategy(...)` | 用授权码换取用户身份 |
| `TokenAuthStrategy(token)` | 自行管理的固定 token，`Feishu("t-xxx")` 是它的简写 |
| `UnauthAuthStrategy()` | 不带 token |

每个接口接受哪些 token 类型由生成代码声明，SDK 自动选择。比如同时支持两种 token 的接口，应用身份用 `tenant_access_token`，用户身份用 `user_access_token`。

## 切换身份

切换身份用 `with_auth`，配置和缓存共享：

```python
from larkify import AppAuthStrategy, Feishu, OAuthToken

auth = AppAuthStrategy("cli_xxx", "app_secret")
feishu = Feishu(auth)

# 把用户引导到授权页
url = auth.get_authorize_url(
    feishu, "https://example.com/callback", scope="offline_access"
)

# 用回调里的 code 换 token
user = auth.as_web_user("code", "https://example.com/callback").exchange_token(feishu)
print(user.token, user.refresh_token)


# 已有 token 时
def save(token: OAuthToken) -> None:
    """refresh_token 只能用一次，新值必须持久化。"""


user.on_refresh = save
feishu.with_auth(user).rest.authen.v1.user_info.get()
```

!!! warning

    `refresh_token` 是一次性的，并发刷新时 SDK 保证只消耗一次；新值只会返回一次，所以务必通过 `on_refresh` 保存，异步场景下它可以是协程函数。

## 商店应用

商店应用需要保存飞书每小时推送的 `app_ticket`，完整示例见[商店应用](../../quickstart/isv-app.md)。

## tenant_access_token 接口

文档已把 `/open-apis/auth/v3/tenant_access_token/internal` 标记为历史版本，推荐改用 `POST /oauth/v3/token`（`client_credentials`，返回最长约 4KB 的 JWT）。本 SDK 默认使用新接口，需要旧接口时：

```python
AppAuthStrategy("cli_xxx", "app_secret", tenant_token_api="legacy")
```

没有配置 `oauth_base_url` 的私有部署会自动使用旧接口。
