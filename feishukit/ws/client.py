"""Long connection event subscription.

The application dials out, so no public address is needed, and deliveries are
neither encrypted nor signed: the connection itself is authenticated.

https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/request-url-configuration-case
"""

import base64
from dataclasses import dataclass
import json
import random
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

import anyio
import anyio.abc
import httpx2
from pydantic_core import to_jsonable_python

from feishukit.exception import AuthCredentialError, WebSocketError
from feishukit.log import logger
from feishukit.webhooks import EventDispatcher

from .frame import METHOD_CONTROL, METHOD_DATA, Frame

if TYPE_CHECKING:
    from httpx2.websockets import AsyncWebSocketSession

    from feishukit import FeishuCore

ENDPOINT_PATH = "callback/ws/endpoint"

HEADER_TYPE = "type"
HEADER_MESSAGE_ID = "message_id"
HEADER_SUM = "sum"
HEADER_SEQ = "seq"
HEADER_BIZ_RT = "biz_rt"
HEADER_HANDSHAKE_STATUS = "handshake-status"
HEADER_HANDSHAKE_MSG = "handshake-msg"
HEADER_HANDSHAKE_AUTH_ERROR = "handshake-autherrcode"

TYPE_EVENT = "event"
TYPE_PING = "ping"
TYPE_PONG = "pong"

CODE_OK = 0
CODE_SYSTEM_BUSY = 1
CODE_FORBIDDEN = 403
CODE_AUTH_FAILED = 514
CODE_INTERNAL_ERROR = 1000040343
CODE_EXCEED_CONN_LIMIT = 1000040350

# Parts of a split delivery are dropped if the rest does not arrive by then.
FRAGMENT_TTL = 5.0


@dataclass
class ClientConfig:
    """Connection parameters, set by the server and revised on each pong."""

    reconnect_count: int = -1
    reconnect_interval: int = 120
    reconnect_nonce: int = 30
    ping_interval: int = 120

    def update(self, data: dict[str, Any]) -> None:
        self.reconnect_count = data.get("ReconnectCount", self.reconnect_count)
        self.reconnect_interval = data.get("ReconnectInterval", self.reconnect_interval)
        self.reconnect_nonce = data.get("ReconnectNonce", self.reconnect_nonce)
        self.ping_interval = data.get("PingInterval", self.ping_interval)


@dataclass
class _Fragments:
    parts: list[bytes | None]
    expire_at: float


def _credentials(feishu: "FeishuCore") -> tuple[str, str]:
    app_id = getattr(feishu.auth, "app_id", None)
    app_secret = getattr(feishu.auth, "app_secret", None)
    if not app_id or not app_secret:
        raise AuthCredentialError(
            "The long connection needs an application identity, "
            "use AppAuthStrategy or IsvAppAuthStrategy"
        )
    return app_id, app_secret


class WSClient:
    """Receive events and callbacks over a long connection.

    ```python
    dispatcher = EventDispatcher()


    @dispatcher.on(ImMessageReceiveV1Event)
    def on_message(event: ImMessageReceiveV1Event) -> None:
        print(event.event.message.content)


    WSClient(feishu, dispatcher).run()
    ```
    """

    def __init__(
        self,
        feishu: "FeishuCore",
        dispatcher: EventDispatcher,
        *,
        auto_reconnect: bool = True,
    ) -> None:
        self.feishu = feishu
        self.dispatcher = dispatcher
        self.auto_reconnect = auto_reconnect
        self.config = ClientConfig()
        self._fragments: dict[str, _Fragments] = {}
        self._service_id = 0

    def run(self) -> None:
        """Connect and block forever."""
        anyio.run(self.arun)

    async def arun(self) -> None:
        """Connect, and reconnect for as long as the server allows it."""
        try:
            from httpx2.websockets import WebSocketUpgradeError
        except ImportError:
            raise WebSocketError(
                0,
                "The long connection needs `wsproto`, "
                "install it with `pip install feishu-kit[ws]`",
                retryable=False,
            ) from None

        failures = 0
        first_attempt = True
        while True:
            try:
                url = await self._fetch_endpoint()
                async with self.feishu.get_async_client() as client:
                    # Failures inside would surface as an ExceptionGroup from the
                    # context manager, so `_serve` reports them by return value.
                    async with client.websocket(
                        url,
                        auth=None,
                        keepalive_ping_interval_seconds=None,
                        keepalive_ping_timeout_seconds=None,
                    ) as session:
                        logger.info("long connection established")
                        failures = 0
                        first_attempt = False
                        await self._serve(session)
                logger.warning("long connection closed")
            except WebSocketUpgradeError as e:
                error = self._handshake_error(e.response)
                logger.error("long connection refused: %s", error)
                if not error.retryable:
                    raise error from None
                if not self.auto_reconnect:
                    raise error from None
            except WebSocketError as e:
                logger.error("long connection failed: %s", e)
                if not e.retryable or not self.auto_reconnect:
                    raise
            except (httpx2.TransportError, OSError) as e:
                logger.error("long connection failed: %s", e)
                if not self.auto_reconnect:
                    raise WebSocketError(0, str(e)) from e

            if not self.auto_reconnect:
                return

            config = self.config
            if 0 <= config.reconnect_count <= failures:
                raise WebSocketError(
                    0, f"server unreachable after {failures} attempts", retryable=False
                )
            failures += 1

            delay = float(config.reconnect_interval)
            if failures == 1 and not first_attempt:
                # Spread out clients reconnecting after a server restart.
                delay = random.random() * config.reconnect_nonce
            await anyio.sleep(delay)

    async def _fetch_endpoint(self) -> str:
        app_id, app_secret = _credentials(self.feishu)
        async with self.feishu.get_async_client() as client:
            request = client.build_request(
                "POST",
                ENDPOINT_PATH,
                json={"AppID": app_id, "AppSecret": app_secret},
                headers={"locale": "zh"},
            )
            response = await client.send(request, auth=None)

        if response.status_code != httpx2.codes.OK:
            raise WebSocketError(response.status_code, "system busy")
        body = response.json()
        code, msg = body.get("code"), body.get("msg") or ""
        if code == CODE_SYSTEM_BUSY:
            raise WebSocketError(code, "system busy")
        if code == CODE_INTERNAL_ERROR:
            raise WebSocketError(code, msg)
        if code != CODE_OK:
            raise WebSocketError(code, msg, retryable=False)

        data = body.get("data") or {}
        if client_config := data.get("ClientConfig"):
            self.config.update(client_config)

        url = data["URL"]
        self._service_id = int(parse_qs(urlsplit(url).query)["service_id"][0])
        return url

    @staticmethod
    def _handshake_error(response: httpx2.Response) -> WebSocketError:
        headers = response.headers
        status = headers.get(HEADER_HANDSHAKE_STATUS)
        msg = headers.get(HEADER_HANDSHAKE_MSG) or ""
        if status is None:
            return WebSocketError(response.status_code, "handshake failed")

        code = int(status)
        if code == CODE_AUTH_FAILED:
            auth_error = headers.get(HEADER_HANDSHAKE_AUTH_ERROR)
            exceeded = auth_error == str(CODE_EXCEED_CONN_LIMIT)
            return WebSocketError(code, msg, retryable=not exceeded)
        return WebSocketError(code, msg, retryable=code != CODE_FORBIDDEN)

    async def _serve(self, session: "AsyncWebSocketSession") -> None:
        """Work on one connection until it ends. Does not raise on disconnect."""
        from httpx2.websockets import HTTPXWSException
        from wsproto.utilities import ProtocolError

        # Sending can race with the connection closing, which wsproto reports
        # as a protocol error of its own rather than a disconnect.
        lost = (HTTPXWSException, ProtocolError)

        async def ping(tasks: anyio.abc.TaskGroup) -> None:
            frame = Frame(
                service=self._service_id,
                method=METHOD_CONTROL,
                headers=[(HEADER_TYPE, TYPE_PING)],
            )
            while True:
                try:
                    await session.send_bytes(frame.encode())
                except lost as e:
                    logger.warning("long connection lost: %r", e)
                    tasks.cancel_scope.cancel()
                    return
                await anyio.sleep(self.config.ping_interval)

        async def on_frame(frame: Frame) -> None:
            try:
                reply = await self._handle_data(frame)
                if reply is not None:
                    await session.send_bytes(reply.encode())
            except lost as e:
                logger.warning("could not answer delivery: %r", e)
            except Exception:
                logger.exception("could not process delivery")

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(ping, tasks)
            try:
                while True:
                    frame = Frame.decode(await session.receive_bytes())
                    if frame.method == METHOD_CONTROL:
                        self._handle_control(frame)
                    elif frame.method == METHOD_DATA:
                        # Handlers can be slow, and pings have to keep going.
                        tasks.start_soon(on_frame, frame)
            except lost as e:
                logger.warning("long connection lost: %r", e)
            except ValueError as e:
                logger.error("undecodable frame, reconnecting: %r", e)
            finally:
                tasks.cancel_scope.cancel()

    def _handle_control(self, frame: Frame) -> None:
        if frame.header(HEADER_TYPE) != TYPE_PONG or not frame.payload:
            return
        try:
            self.config.update(json.loads(frame.payload))
        except (ValueError, AttributeError):
            logger.warning("ignoring malformed pong: %r", frame.payload)

    def _reassemble(self, frame: Frame) -> bytes | None:
        """Join a delivery split over several frames, once all have arrived."""
        count = int(frame.header(HEADER_SUM) or 1)
        payload = frame.payload or b""
        if count <= 1:
            return payload

        now = time.monotonic()
        for key in [k for k, v in self._fragments.items() if v.expire_at < now]:
            del self._fragments[key]

        message_id = frame.header(HEADER_MESSAGE_ID) or ""
        fragments = self._fragments.setdefault(
            message_id, _Fragments([None] * count, now + FRAGMENT_TTL)
        )
        fragments.parts[int(frame.header(HEADER_SEQ) or 0)] = payload
        if any(part is None for part in fragments.parts):
            return None
        del self._fragments[message_id]
        return b"".join(p for p in fragments.parts if p is not None)

    async def _handle_data(self, frame: Frame) -> Frame | None:
        payload = self._reassemble(frame)
        if payload is None:
            return None
        # Other types, such as the legacy card one, are not answered.
        if frame.header(HEADER_TYPE) != TYPE_EVENT:
            return None

        started = time.monotonic()
        answer: dict[str, Any] = {"code": httpx2.codes.OK}
        try:
            result = await self.dispatcher.adispatch(json.loads(payload))
            if result is not None:
                encoded = json.dumps(to_jsonable_python(result), ensure_ascii=False)
                answer["data"] = base64.b64encode(encoded.encode()).decode()
        except Exception:
            logger.exception("event handler failed")
            answer = {"code": httpx2.codes.INTERNAL_SERVER_ERROR}

        elapsed = int((time.monotonic() - started) * 1000)
        frame.headers.append((HEADER_BIZ_RT, str(elapsed)))
        frame.payload = json.dumps(answer).encode()
        return frame
