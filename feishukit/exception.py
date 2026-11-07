from datetime import timedelta
from typing import TYPE_CHECKING, Generic, TypeVar

import httpx2

if TYPE_CHECKING:
    from .response import Response


E = TypeVar("E", bound=Exception)


class FeishuException(Exception): ...


class CacheUnsupportedError(FeishuException):
    """Unsupported Cache Usage Error"""


class AuthCredentialError(FeishuException):
    """Auth Credential Error"""


class AuthExpiredError(FeishuException):
    """Auth Expired Error"""


class RequestError(FeishuException, Generic[E]):
    """API request failed with unknown error"""

    def __init__(self, exc: E) -> None:
        super().__init__(str(exc))
        self.exc = exc

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(origin_exc={self.exc!r})"


class RequestTimeout(RequestError[httpx2.TimeoutException]):
    """API request timeout"""

    @property
    def request(self) -> httpx2.Request:
        return self.exc.request

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(method={self.request.method}, "
            f"url={self.request.url})"
        )


class RequestFailed(RequestError[httpx2.HTTPStatusError]):
    """API request rejected, by HTTP status or by a non-zero business `code`"""

    def __init__(self, response: "Response"):
        super().__init__(
            httpx2.HTTPStatusError(
                "Request failed",
                request=response.raw_request,
                response=response.raw_response,
            )
        )
        self.request = response.raw_request
        self.response = response

    @property
    def code(self) -> int | None:
        return self.response.code

    @property
    def msg(self) -> str | None:
        return self.response.msg

    @property
    def log_id(self) -> str | None:
        return self.response.log_id

    def _details(self) -> str:
        return (
            f"method={self.request.method}, url={self.request.url}, "
            f"status_code={self.response.status_code}, code={self.code}, "
            f"msg={self.msg!r}, log_id={self.log_id}"
        )

    def __str__(self) -> str:
        return self._details()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._details()})"


class RateLimitExceeded(RequestFailed):
    """API request rejected by the rate limiter"""

    def __init__(self, response: "Response", retry_after: timedelta):
        super().__init__(response)
        self.retry_after = retry_after

    def _details(self) -> str:
        return f"{super()._details()}, retry_after={self.retry_after}"


class PaginationError(FeishuException):
    """The paginated API returned a page that cannot be continued from"""


class WebhookError(FeishuException):
    """Event or callback delivery could not be processed"""


class WebhookVerificationFailed(WebhookError):
    """Event or callback failed the token or signature check"""


class WebhookTypeNotFound(WebhookError):
    """Event type has no known model"""

    def __init__(self, name: str):
        super().__init__(f"unknown event type: {name}")
        self.name = name


class WebSocketError(FeishuException):
    """Long connection failure"""

    def __init__(self, code: int, msg: str, *, retryable: bool = True) -> None:
        super().__init__(f"{code}: {msg}")
        self.code = code
        self.msg = msg
        self.retryable = retryable
