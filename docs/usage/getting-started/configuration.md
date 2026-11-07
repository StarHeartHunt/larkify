# 配置

配置通过关键字参数传给 `Feishu`：

```python
from larkify import LARK_BASE_URL, AppAuthStrategy, Feishu
from larkify.cache import RedisCacheStrategy
from larkify.throttling import LocalThrottler
from redis import Redis

feishu = Feishu(
    AppAuthStrategy("cli_xxx", "app_secret"),
    base_url=LARK_BASE_URL,  # 使用 Lark
    timeout=60,
    proxy="http://127.0.0.1:7890",
    cache_strategy=RedisCacheStrategy(Redis(), prefix="myapp"),  # 多进程共享 token
    throttler=LocalThrottler(20),  # 限制并发数
)
```

## 配置项

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `base_url` | `FEISHU_BASE_URL` | 开放平台地址，Lark 用 `LARK_BASE_URL` |
| `oauth_base_url` | 由 `base_url` 决定 | OAuth 地址，私有部署无法推断，需要自行配置 |
| `user_agent` | `larkify/Python` | 请求的 `User-Agent` |
| `follow_redirects` | `True` | 是否跟随重定向 |
| `timeout` | 30 秒 | 秒数或 `httpx2.Timeout` |
| `ssl_verify` | `True` | 是否校验证书，也可以传 `ssl.SSLContext` |
| `trust_env` | `True` | 是否读取环境变量中的代理和证书配置 |
| `proxy` | `None` | 代理地址 |
| `transport` / `async_transport` | `None` | 自定义 httpx2 transport |
| `event_hooks` / `async_event_hooks` | `None` | httpx2 事件钩子 |
| `cache_strategy` | 内存缓存 | token 缓存，多进程共享时用 `RedisCacheStrategy` |
| `throttler` | `LocalThrottler(100)` | 并发限制 |
| `auto_retry` | `True` | 见[自动重试](../auto-retry.md) |
| `rest_api_validate_body` | `True` | 发送前校验请求体，见[传参](../rest-api.md#传参) |
| `insecure_allow_http` | `False` | 允许 `base_url` 和 `oauth_base_url` 使用 http，仅用于内网的私有部署 |

!!! warning

    `base_url` 只接受 https（本机回环地址除外），且不能内嵌账号密码，因为应用密钥会发往这里。开启 `insecure_allow_http` 后 http 也可用，但应用密钥和 token 都会明文传输。
