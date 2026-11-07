from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hmac
import inspect
import json
from typing import Any, ClassVar, TypeVar

import anyio.to_thread
from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from larkify.exception import WebhookError, WebhookVerificationFailed
from larkify.log import logger

from .crypto import decrypt, verify
from .models import EventV1, EventV2
from .parse import event_type_of, parse_obj

E = TypeVar("E", bound=EventV1 | EventV2)
Handler = TypeVar("Handler", bound=Callable[..., Any])

_URL_VERIFICATION = "url_verification"
_SUCCESS = {"msg": "success"}


@dataclass
class WebhookResponse:
    """What to answer the delivery with, independent of the web framework."""

    status_code: int
    body: bytes

    content_type: ClassVar[str] = "application/json; charset=utf-8"


def _respond(status_code: int, content: Any) -> WebhookResponse:
    if isinstance(content, BaseModel):
        content = content.model_dump(mode="json", by_alias=True, exclude_none=True)
    body = json.dumps(to_jsonable_python(content), ensure_ascii=False).encode()
    return WebhookResponse(status_code, body)


class EventDispatcher:
    """Route events and callbacks to handlers.

    ```python
    dispatcher = EventDispatcher(encrypt_key="...", verification_token="...")


    @dispatcher.on(ImMessageReceiveV1Event)
    async def on_message(event: ImMessageReceiveV1Event) -> None: ...


    # inside a web framework view
    result = await dispatcher.ahandle(await request.body(), request.headers)
    ```

    Deliveries are retried by Feishu if not answered in time, so long running
    work should be moved out of the handler. `header.event_id` identifies
    retries of the same event.

    `handle` and `ahandle` refuse to accept unauthenticated deliveries unless
    `insecure_no_verification=True`. The long connection authenticates itself,
    and needs no credentials here.

    To route deliveries some other way, override `dispatch` and `adispatch`. They
    receive the authenticated delivery as a dictionary, before any model is
    built, whichever way it came in. The return value is what the delivery is
    answered with, and `None` means a plain acknowledgement.
    """

    def __init__(
        self,
        *,
        encrypt_key: str | None = None,
        verification_token: str | None = None,
        insecure_no_verification: bool = False,
    ) -> None:
        self.encrypt_key = encrypt_key or None
        self.verification_token = verification_token or None
        self.insecure_no_verification = insecure_no_verification
        self._handlers: defaultdict[str, list[Callable[[Any], Any]]] = defaultdict(list)

    def on(self, event: str | type[EventV1 | EventV2]) -> Callable[[Handler], Handler]:
        """Register a handler, by event type name or by event model."""
        event_type = event if isinstance(event, str) else event.event_type
        if not event_type:
            raise ValueError(f"{event!r} does not identify an event type")

        def decorator(func: Handler) -> Handler:
            self._handlers[event_type].append(func)
            return func

        return decorator

    def _open(
        self, body: bytes, headers: Mapping[str, str]
    ) -> tuple[dict[str, Any], WebhookResponse | None]:
        """Authenticate a delivery. A response is returned if it ends here."""
        if not (
            self.encrypt_key or self.verification_token or self.insecure_no_verification
        ):
            raise WebhookError(
                "EventDispatcher has no credentials to verify deliveries with"
            )

        try:
            envelope = json.loads(body)
        except ValueError as e:
            raise WebhookError("delivery is not JSON") from e
        if not isinstance(envelope, dict):
            raise WebhookError("delivery is not a JSON object")

        data = envelope
        if encrypted := envelope.get("encrypt"):
            if self.encrypt_key is None:
                raise WebhookError("delivery is encrypted, set `encrypt_key`")
            try:
                data = json.loads(decrypt(self.encrypt_key, encrypted))
            except ValueError as e:
                raise WebhookVerificationFailed("cannot decrypt delivery") from e
            if not isinstance(data, dict):
                raise WebhookError("delivery is not a JSON object")

        header = data.get("header")
        token = header.get("token") if isinstance(header, dict) else data.get("token")
        is_challenge = data.get("type") == _URL_VERIFICATION

        # With an Encrypt Key the signature below proves authenticity, and some
        # deliveries have no token. The challenge is not signed.
        if self.verification_token is not None and (
            self.encrypt_key is None or is_challenge or token is not None
        ):
            if not isinstance(token, str) or not hmac.compare_digest(
                token.encode(), self.verification_token.encode()
            ):
                raise WebhookVerificationFailed("invalid verification token")

        if is_challenge:
            return data, _respond(200, {"challenge": data.get("challenge")})

        if self.encrypt_key is not None:
            lowered = {k.lower(): v for k, v in headers.items()}
            signature = lowered.get("x-lark-signature")
            timestamp = lowered.get("x-lark-request-timestamp")
            nonce = lowered.get("x-lark-request-nonce")
            if (
                signature is None
                or timestamp is None
                or nonce is None
                or not verify(self.encrypt_key, timestamp, nonce, body, signature)
            ):
                raise WebhookVerificationFailed("invalid signature")

        return data, None

    def _handlers_of(self, data: Mapping[str, Any]) -> list[Callable[[Any], Any]]:
        event_type = event_type_of(data)
        handlers = self._handlers.get(event_type, [])
        if not handlers:
            logger.debug("no handler registered for event %s", event_type)
        return handlers

    def dispatch(self, data: Mapping[str, Any]) -> Any:
        """Run the handlers of an authenticated delivery.

        Returns the last value a handler returned, which is what a callback
        answers with.
        """
        handlers = self._handlers_of(data)
        if not handlers:
            return None

        event = parse_obj(data)
        result = None
        for handler in handlers:
            if inspect.iscoroutinefunction(handler):
                raise WebhookError(
                    f"{handler.__name__} is async, use `ahandle` or the long connection"
                )
            if (value := handler(event)) is not None:
                result = value
        return result

    async def adispatch(self, data: Mapping[str, Any]) -> Any:
        """Run the handlers of an authenticated delivery.

        Sync handlers run in a worker thread, to keep the event loop responsive.
        """
        handlers = self._handlers_of(data)
        if not handlers:
            return None

        event = parse_obj(data)
        result = None
        for handler in handlers:
            if inspect.iscoroutinefunction(handler):
                value = await handler(event)
            else:
                value = await anyio.to_thread.run_sync(handler, event)
            if value is not None:
                result = value
        return result

    @staticmethod
    def _failure(exc: Exception) -> WebhookResponse:
        # The message goes to whoever sent the request, which is not yet known
        # to be Feishu, so handler errors stay in the log.
        if isinstance(exc, WebhookVerificationFailed):
            logger.warning("rejected delivery: %s", exc)
            return _respond(401, {"msg": str(exc)})
        if isinstance(exc, WebhookError):
            logger.warning("bad delivery: %s", exc)
            return _respond(400, {"msg": str(exc)})
        logger.exception("event handler failed", exc_info=exc)
        return _respond(500, {"msg": "internal error"})

    def handle(self, body: bytes, headers: Mapping[str, str]) -> WebhookResponse:
        """Process one delivery from a sync web framework."""
        try:
            data, response = self._open(body, headers)
            if response is not None:
                return response
            result = self.dispatch(data)
        except Exception as e:
            return self._failure(e)
        return _respond(200, _SUCCESS if result is None else result)

    async def ahandle(self, body: bytes, headers: Mapping[str, str]) -> WebhookResponse:
        """Process one delivery from an async web framework."""
        try:
            data, response = self._open(body, headers)
            if response is not None:
                return response
            result = await self.adispatch(data)
        except Exception as e:
            return self._failure(e)
        return _respond(200, _SUCCESS if result is None else result)
