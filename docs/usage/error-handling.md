# 错误处理

飞书的业务错误常以 HTTP 200 返回，SDK 会检查 `code`，非 0 一律抛 `RequestFailed`。

```python
from larkify import AppAuthStrategy, Feishu
from larkify.exception import RateLimitExceeded, RequestFailed, RequestTimeout

feishu = Feishu(AppAuthStrategy("cli_xxx", "app_secret"))

try:
    feishu.rest.im.v1.message.get("om_xxx")
except RateLimitExceeded as e:
    print(e.retry_after)
except RequestFailed as e:
    print(e.code, e.msg, e.log_id, e.response.error.get("troubleshooter"))
except RequestTimeout:
    ...
```

限流和 5xx 会先按[自动重试](./auto-retry.md)的策略处理，决定不再重试时才抛出。
