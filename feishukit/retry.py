from datetime import timedelta

from .exception import FeishuException, RateLimitExceeded, RequestFailed
from .log import logger
from .typing import RetryDecisionFunc as RetryDecisionFunc
from .typing import RetryOption as RetryOption

# Replaying these cannot produce a second effect. POST is excluded: a 5xx does
# not prove the request did nothing, and resending `im.v1.message.create` could
# deliver the message twice.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


class RetryRateLimit:
    """Retry decision function for rate limit exceeded.

    A rate limited request was rejected before doing anything, so this applies
    to every method.
    """

    __slots__ = ("max_retry",)

    def __init__(self, max_retry: int = 3) -> None:
        self.max_retry = max_retry

    def __call__(self, exc: FeishuException, retry_count: int) -> RetryOption:
        if retry_count < self.max_retry and isinstance(exc, RateLimitExceeded):
            logger.warning(
                f"{exc.__class__.__name__} for request "
                f"{exc.request.method} {exc.request.url}",
                exc_info=exc,
            )
            return RetryOption(True, exc.retry_after)

        return RetryOption(False)


RETRY_RATE_LIMIT = RetryRateLimit()


class RetryServerError:
    """Retry decision function for server error on idempotent requests."""

    __slots__ = ("max_retry",)

    def __init__(self, max_retry: int = 3) -> None:
        self.max_retry = max_retry

    def __call__(self, exc: FeishuException, retry_count: int) -> RetryOption:
        if (
            retry_count < self.max_retry
            and isinstance(exc, RequestFailed)
            and exc.response.status_code >= 500
            and exc.request.method in IDEMPOTENT_METHODS
        ):
            logger.warning(
                f"Server error encountered for request "
                f"{exc.request.method} {exc.request.url}",
                exc_info=exc,
            )
            return RetryOption(True, timedelta(seconds=(retry_count + 1) ** 2))

        return RetryOption(False)


RETRY_SERVER_ERROR = RetryServerError()


class RetryChainDecision:
    """Chain multiple retry decision functions."""

    __slots__ = ("decision_funcs",)

    def __init__(self, *decision_funcs: RetryDecisionFunc) -> None:
        self.decision_funcs = decision_funcs

    def __call__(self, exc: FeishuException, retry_count: int) -> RetryOption:
        for decision_func in self.decision_funcs:
            retry_option = decision_func(exc, retry_count)
            if retry_option.do_retry:
                return retry_option

        return RetryOption(False)


RETRY_DEFAULT = RetryChainDecision(RETRY_RATE_LIMIT, RETRY_SERVER_ERROR)
