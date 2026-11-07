"""The long connection, against a real socket server speaking the same protocol."""

import asyncio
import base64
import json

import anyio
import pytest
import wsproto
from wsproto.events import (
    AcceptConnection,
    BytesMessage,
    CloseConnection,
    Request,
)

from larkify import AppAuthStrategy, Feishu
from larkify.cache import MemCacheStrategy
from larkify.exception import AuthCredentialError, WebSocketError
from larkify.webhooks import CardActionTriggerEvent, EventDispatcher
from larkify.webhooks.events.im import ImMessageReceiveV1Event
from larkify.ws import Frame, WSClient
from larkify.ws.frame import METHOD_CONTROL, METHOD_DATA

# Serialized by the official SDK's protobuf module.
OFFICIAL_FRAME = bytes.fromhex(
    "0894b4e4f4cb031007182a20012a0d0a047479706512056576656e742a130a0a6d657373"
    "6167655f696412056d73672d3132057574662d383a046a736f6e42117b2274657874223a"
    "22e4bda0e5a5bd227d4a076c6f672d6e6577"
)
OFFICIAL_PING = bytes.fromhex("08001000186320002a0c0a0474797065120470696e67")
OFFICIAL_NEGATIVE = bytes.fromhex("0801100218fbffffffffffffffff012000")


def test_frame_decodes_official_bytes():
    frame = Frame.decode(OFFICIAL_FRAME)

    assert frame.seq_id == 123456789012
    assert frame.log_id == 7
    assert frame.service == 42
    assert frame.method == METHOD_DATA
    assert frame.headers == [("type", "event"), ("message_id", "msg-1")]
    assert frame.payload_encoding == "utf-8"
    assert frame.payload_type == "json"
    assert frame.payload == '{"text":"你好"}'.encode()
    assert frame.log_id_new == "log-new"


def test_frame_encodes_official_bytes():
    assert Frame.decode(OFFICIAL_FRAME).encode() == OFFICIAL_FRAME
    assert Frame(service=99, headers=[("type", "ping")]).encode() == OFFICIAL_PING
    assert Frame(seq_id=1, log_id=2, service=-5).encode() == OFFICIAL_NEGATIVE
    assert Frame.decode(OFFICIAL_NEGATIVE).service == -5


@pytest.mark.parametrize(
    "data",
    [
        b"\xff" * 11,  # varint that never ends
        b"\x2a\xff\x01",  # length past the end
        b"\x28\x01",  # headers as a number instead of a message
        b"\x0a\x01a",  # sequence id as text
    ],
)
def test_frame_rejects_garbage(data):
    with pytest.raises(ValueError):
        Frame.decode(data)


class FakeServer:
    """Answers the endpoint request and the WebSocket upgrade on one port."""

    def __init__(self) -> None:
        self.port = 0
        self.endpoint_requests: list[dict] = []
        self.received: asyncio.Queue[Frame] = asyncio.Queue()
        self.frames_on_connect: list[list[bytes]] = []
        self.connections = 0
        self.endpoint_body: dict | None = None
        self.close_after_send = False
        self.client_config = {
            "ReconnectCount": -1,
            "ReconnectInterval": 0,
            "ReconnectNonce": 0,
            "PingInterval": 60,
        }
        self.refuse_with: dict[str, str] | None = None

    async def serve(self, reader, writer) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            if head.startswith(b"POST"):
                await self._endpoint(head, reader, writer)
            else:
                await self._websocket(head, reader, writer)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    async def _endpoint(self, head, reader, writer) -> None:
        length = 0
        for line in head.decode().split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":")[1])
        self.endpoint_requests.append(json.loads(await reader.readexactly(length)))
        body = self.endpoint_body or {
            "code": 0,
            "msg": "ok",
            "data": {
                "URL": f"ws://127.0.0.1:{self.port}/ws?device_id=d1&service_id=77",
                "ClientConfig": self.client_config,
            },
        }
        raw = json.dumps(body).encode()
        writer.write(
            b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n"
            + f"content-length: {len(raw)}\r\nconnection: close\r\n\r\n".encode()
            + raw
        )
        await writer.drain()

    async def _websocket(self, head, reader, writer) -> None:
        if self.refuse_with is not None:
            headers = "".join(f"{k}: {v}\r\n" for k, v in self.refuse_with.items())
            writer.write(
                f"HTTP/1.1 400 Bad Request\r\n{headers}content-length: 0\r\n\r\n".encode()
            )
            await writer.drain()
            return

        connection = wsproto.WSConnection(wsproto.ConnectionType.SERVER)
        connection.receive_data(head)
        for event in connection.events():
            if isinstance(event, Request):
                writer.write(connection.send(AcceptConnection()))
        await writer.drain()

        scripted = self.frames_on_connect.pop(0) if self.frames_on_connect else []
        self.connections += 1
        for data in scripted:
            writer.write(connection.send(BytesMessage(data=data)))
        await writer.drain()

        if self.close_after_send:
            writer.write(connection.send(CloseConnection(code=1000)))
            await writer.drain()
            return

        while True:
            data = await reader.read(65536)
            if not data:
                return
            connection.receive_data(data)
            for event in connection.events():
                if isinstance(event, BytesMessage):
                    await self.received.put(Frame.decode(bytes(event.data)))
                elif isinstance(event, CloseConnection):
                    return

    async def next_frame(self, method: int) -> Frame:
        while True:
            frame = await asyncio.wait_for(self.received.get(), 5)
            if frame.method == method:
                return frame


@pytest.fixture
async def server():
    fake = FakeServer()
    listener = await asyncio.start_server(fake.serve, "127.0.0.1", 0)
    fake.port = listener.sockets[0].getsockname()[1]
    async with listener:
        yield fake


def client_for(server: FakeServer) -> Feishu:
    return Feishu(
        AppAuthStrategy("cli_test", "secret"),
        base_url=f"http://127.0.0.1:{server.port}",
        cache_strategy=MemCacheStrategy(),
        trust_env=False,
    )


def event_frame(payload: dict, *, message_id="m1", sum_=1, seq=0) -> Frame:
    return Frame(
        seq_id=5,
        log_id=6,
        service=77,
        method=METHOD_DATA,
        headers=[
            ("type", "event"),
            ("message_id", message_id),
            ("sum", str(sum_)),
            ("seq", str(seq)),
            ("trace_id", "t1"),
        ],
        payload=json.dumps(payload).encode(),
    )


MESSAGE = {
    "schema": "2.0",
    "header": {"event_type": "im.message.receive_v1", "event_id": "e1"},
    "event": {"message": {"message_id": "om_1"}},
}


@pytest.mark.anyio
async def test_events_are_delivered_and_acknowledged(server):
    dispatcher = EventDispatcher()
    received = anyio.Event()
    seen = []

    @dispatcher.on(ImMessageReceiveV1Event)
    async def handler(event):
        seen.append(event)
        received.set()

    server.frames_on_connect.append([event_frame(MESSAGE).encode()])
    client = WSClient(client_for(server), dispatcher)

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(client.arun)
        with anyio.fail_after(5):
            await received.wait()
            reply = await server.next_frame(METHOD_DATA)
        tasks.cancel_scope.cancel()

    assert seen[0].event.message.message_id == "om_1"
    assert server.endpoint_requests == [{"AppID": "cli_test", "AppSecret": "secret"}]
    assert json.loads(reply.payload) == {"code": 200}
    assert reply.seq_id == 5
    assert reply.header("biz_rt") is not None


@pytest.mark.anyio
async def test_pings_carry_the_service_id(server):
    client = WSClient(client_for(server), EventDispatcher())

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(client.arun)
        ping = await server.next_frame(METHOD_CONTROL)
        tasks.cancel_scope.cancel()

    assert ping.service == 77
    assert ping.header("type") == "ping"


@pytest.mark.anyio
async def test_pong_updates_the_configuration(server):
    pong = Frame(
        service=77,
        method=METHOD_CONTROL,
        headers=[("type", "pong")],
        payload=json.dumps({"PingInterval": 5, "ReconnectCount": 3}).encode(),
    )
    server.frames_on_connect.append([pong.encode()])
    client = WSClient(client_for(server), EventDispatcher())

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(client.arun)
        with anyio.fail_after(5):
            while client.config.ping_interval != 5:
                await anyio.sleep(0.01)
        tasks.cancel_scope.cancel()

    assert client.config.reconnect_count == 3


@pytest.mark.anyio
async def test_malformed_pong_does_not_end_the_connection(server):
    pong = Frame(
        service=77, method=METHOD_CONTROL, headers=[("type", "pong")], payload=b"{oops"
    )
    server.client_config["PingInterval"] = 0.01
    server.frames_on_connect.append([pong.encode()])
    client = WSClient(client_for(server), EventDispatcher())

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(client.arun)
        for _ in range(3):
            await server.next_frame(METHOD_CONTROL)
        tasks.cancel_scope.cancel()

    assert server.connections == 1


@pytest.mark.anyio
async def test_callback_results_are_sent_back(server):
    dispatcher = EventDispatcher()
    dispatcher.on(CardActionTriggerEvent)(lambda e: {"toast": {"content": "ok"}})
    delivery = {
        "schema": "2.0",
        "header": {"event_type": "card.action.trigger"},
        "event": {},
    }
    server.frames_on_connect.append([event_frame(delivery).encode()])
    client = WSClient(client_for(server), dispatcher)

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(client.arun)
        reply = await server.next_frame(METHOD_DATA)
        tasks.cancel_scope.cancel()

    answer = json.loads(reply.payload)
    assert json.loads(base64.b64decode(answer["data"])) == {"toast": {"content": "ok"}}


@pytest.mark.anyio
async def test_split_deliveries_are_reassembled(server):
    dispatcher = EventDispatcher()
    done = anyio.Event()
    seen = []

    @dispatcher.on(ImMessageReceiveV1Event)
    def handler(event):
        seen.append(event)
        done.set()

    whole = json.dumps(MESSAGE).encode()
    first = event_frame(MESSAGE, sum_=2, seq=1)
    first.payload = whole[20:]
    second = event_frame(MESSAGE, sum_=2, seq=0)
    second.payload = whole[:20]
    server.frames_on_connect.append([first.encode(), second.encode()])
    client = WSClient(client_for(server), dispatcher)

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(client.arun)
        with anyio.fail_after(5):
            await done.wait()
        tasks.cancel_scope.cancel()

    assert len(seen) == 1


@pytest.mark.anyio
async def test_handler_failure_is_reported_and_connection_survives(server):
    dispatcher = EventDispatcher()

    @dispatcher.on(ImMessageReceiveV1Event)
    def handler(event):
        raise RuntimeError("boom")

    server.client_config["PingInterval"] = 0.01
    server.frames_on_connect.append([event_frame(MESSAGE).encode()])
    client = WSClient(client_for(server), dispatcher)

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(client.arun)
        reply = await server.next_frame(METHOD_DATA)
        ping = await server.next_frame(METHOD_CONTROL)
        tasks.cancel_scope.cancel()

    assert json.loads(reply.payload) == {"code": 500}
    assert ping.header("type") == "ping"


@pytest.mark.anyio
async def test_reconnects_after_the_server_closes(server):
    server.close_after_send = True
    server.frames_on_connect.extend([[], []])
    client = WSClient(client_for(server), EventDispatcher())

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(client.arun)
        with anyio.fail_after(5):
            while server.connections < 2:
                await anyio.sleep(0.01)
        tasks.cancel_scope.cancel()

    assert len(server.endpoint_requests) >= 2


@pytest.mark.anyio
async def test_run_ends_when_reconnection_is_disabled(server):
    server.close_after_send = True
    client = WSClient(client_for(server), EventDispatcher(), auto_reconnect=False)

    with anyio.fail_after(5):
        await client.arun()


@pytest.mark.anyio
async def test_bad_credentials_stop_the_client(server):
    server.endpoint_body = {"code": 1000040344, "msg": "invalid credential"}
    client = WSClient(client_for(server), EventDispatcher())

    with pytest.raises(WebSocketError) as info, anyio.fail_after(5):
        await client.arun()

    assert info.value.code == 1000040344
    assert info.value.retryable is False


@pytest.mark.anyio
async def test_connection_limit_stops_the_client(server):
    server.refuse_with = {
        "handshake-status": "514",
        "handshake-msg": "too many connections",
        "handshake-autherrcode": "1000040350",
    }
    client = WSClient(client_for(server), EventDispatcher())

    with pytest.raises(WebSocketError) as info, anyio.fail_after(5):
        await client.arun()

    assert info.value.code == 514


@pytest.mark.anyio
async def test_transient_handshake_failure_is_retried(server):
    server.refuse_with = {"handshake-status": "500", "handshake-msg": "busy"}
    client = WSClient(client_for(server), EventDispatcher())

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(client.arun)
        with anyio.fail_after(5):
            while len(server.endpoint_requests) < 2:
                await anyio.sleep(0.01)
        tasks.cancel_scope.cancel()


@pytest.mark.anyio
async def test_needs_application_credentials():
    client = WSClient(Feishu("t-token"), EventDispatcher())

    with pytest.raises(AuthCredentialError):
        await client.arun()
