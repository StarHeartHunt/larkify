# 用户身份授权

通过 OAuth 授权码流程获取用户身份，再用 `with_auth` 切换到该身份调用接口。

## 引导用户授权

```python
from larkify import AppAuthStrategy, Feishu

auth = AppAuthStrategy("cli_xxx", "app_secret")
feishu = Feishu(auth)

# 把用户引导到授权页
url = auth.get_authorize_url(
    feishu, "https://example.com/callback", scope="offline_access"
)
```

## 用 code 换 token

=== "同步"

    ```python
    # 用回调里的 code 换 token
    user = auth.as_web_user("code", "https://example.com/callback").exchange_token(feishu)
    print(user.token, user.refresh_token)
    ```

=== "异步"

    ```python
    # 用回调里的 code 换 token
    web_user = auth.as_web_user("code", "https://example.com/callback")
    user = await web_user.async_exchange_token(feishu)
    print(user.token, user.refresh_token)
    ```

## 保存 token 并调用接口

!!! warning

    `refresh_token` 是一次性的，新值只会返回一次，务必通过 `on_refresh` 保存。

=== "同步"

    ```python
    from larkify import OAuthToken


    def save(token: OAuthToken) -> None:
        """refresh_token 只能用一次，新值必须持久化。"""


    user.on_refresh = save
    feishu.with_auth(user).rest.authen.v1.user_info.get()
    ```

=== "异步"

    ```python
    from larkify import OAuthToken


    async def save(token: OAuthToken) -> None:
        """refresh_token 只能用一次，新值必须持久化。"""


    user.on_refresh = save
    await feishu.with_auth(user).rest.authen.v1.user_info.async_get()
    ```

更多认证方式见[认证](../usage/getting-started/authentication.md)。
