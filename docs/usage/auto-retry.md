# 自动重试

默认重试策略：

- 限流最多重试 3 次，按 `x-ogw-ratelimit-reset` 等待，再追加不超过 1 秒的随机抖动。需要等待超过 60 秒时不重试，直接抛 `RateLimitExceeded`，由调用方根据 `retry_after` 决定，上限可以通过 `RetryRateLimit(max_wait=...)` 调整。
- 5xx 最多重试 3 次，退避带随机抖动，**只针对幂等方法**，因为 POST 失败不代表没有生效，重放 `im.v1.message.create` 可能发出重复消息。

通过 `auto_retry` 关闭或自定义：

```python
from datetime import timedelta

from larkify import AppAuthStrategy, Feishu
from larkify.retry import RetryChainDecision, RetryOption, RetryRateLimit, RetryServerError


def retry_timeouts(exc, retry_count):
    return RetryOption(retry_count < 2, timedelta(seconds=1))


Feishu(AppAuthStrategy("a", "b"), auto_retry=False)
Feishu(AppAuthStrategy("a", "b"), auto_retry=retry_timeouts)
Feishu(
    AppAuthStrategy("a", "b"),
    auto_retry=RetryChainDecision(
        RetryRateLimit(max_retry=5, max_wait=timedelta(minutes=5)),
        RetryServerError(1),
    ),
)
```
