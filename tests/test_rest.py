from datetime import timedelta
import io
import json

import httpx2
from pydantic import ValidationError
import pytest

from larkify import UNSET
from larkify.exception import (
    PaginationError,
    RateLimitExceeded,
    RequestFailed,
)
from larkify.models.im.v1.message import CreateMessageBody
from larkify.retry import RetryRateLimit

from .conftest import ok


def send_text(feishu):
    return feishu.rest.im.v1.message.create(
        receive_id_type="open_id",
        receive_id="ou_1",
        msg_type="text",
        content='{"text":"hi"}',
    )


def test_keyword_arguments_build_the_request(make_client):
    feishu, server = make_client(lambda r: ok({"message_id": "om_1"}))

    response = send_text(feishu)

    request = server.requests[0]
    assert request.method == "POST"
    assert request.url.path == "/open-apis/im/v1/messages"
    assert request.url.params["receive_id_type"] == "open_id"
    assert request.headers["authorization"] == "Bearer tenant-1"
    assert server.last_json == {
        "receive_id": "ou_1",
        "msg_type": "text",
        "content": '{"text":"hi"}',
    }
    assert response.parsed_data.message_id == "om_1"
    assert response.code == 0


def test_data_accepts_dict_and_model(make_client):
    feishu, server = make_client(lambda r: ok())
    body = {"receive_id": "ou_1", "msg_type": "text", "content": "{}"}

    feishu.rest.im.v1.message.create(receive_id_type="open_id", data=body)
    assert server.last_json == body

    model = CreateMessageBody.model_validate(body)
    feishu.rest.im.v1.message.create(receive_id_type="open_id", data=model)
    assert server.last_json == body


def test_missing_required_field_is_rejected_before_sending(make_client):
    feishu, server = make_client(lambda r: ok())

    with pytest.raises(ValidationError):
        feishu.rest.im.v1.message.create(receive_id_type="open_id", receive_id="ou_1")

    assert server.requests == []


def test_validation_can_be_disabled(make_client):
    feishu, server = make_client(lambda r: ok(), rest_api_validate_body=False)

    feishu.rest.im.v1.message.create(receive_id_type="open_id", receive_id="ou_1")

    assert server.last_json == {"receive_id": "ou_1"}


def test_unknown_body_fields_pass_through(make_client):
    feishu, server = make_client(lambda r: ok())

    send = feishu.rest.im.v1.message.create
    send(
        receive_id_type="open_id",
        data={"receive_id": "a", "msg_type": "t", "content": "c", "brand_new": 1},
    )

    assert server.last_json["brand_new"] == 1


def test_optional_fields_left_out_are_not_sent_and_none_is(make_client):
    feishu, server = make_client(lambda r: ok())
    body = {"receive_id": "a", "msg_type": "t", "content": "c"}

    feishu.rest.im.v1.message.create(receive_id_type="open_id", **body, uuid=UNSET)
    assert "uuid" not in server.last_json

    feishu.rest.im.v1.message.create(receive_id_type="open_id", **body, uuid=None)
    assert server.last_json["uuid"] is None


def test_unset_query_parameters_are_omitted(make_client):
    feishu, server = make_client(lambda r: ok())

    feishu.rest.im.v1.message.get("om_1")
    assert "user_id_type" not in server.requests[-1].url.params

    feishu.rest.im.v1.message.get("om_1", user_id_type="open_id")
    assert server.requests[-1].url.params["user_id_type"] == "open_id"


@pytest.mark.parametrize(
    ("value", "encoded"),
    [("a/b", "a%2Fb"), ("../x", "..%2Fx"), ("a?b=c", "a%3Fb%3Dc")],
)
def test_path_parameters_cannot_alter_the_path(make_client, value, encoded):
    feishu, server = make_client(lambda r: ok())

    feishu.rest.im.v1.message.get(value)

    assert server.requests[0].url.raw_path == (
        f"/open-apis/im/v1/messages/{encoded}".encode()
    )


def test_empty_path_parameter_does_not_reach_another_endpoint(make_client):
    feishu, server = make_client(lambda r: ok())

    with pytest.raises(ValueError, match="must not be empty"):
        feishu.rest.im.v1.message.get("")

    assert server.requests == []


def test_business_error_on_http_200_raises(make_client):
    response = httpx2.Response(
        200,
        json={
            "code": 230002,
            "msg": "Bot is not in the chat",
            "error": {"log_id": "abc", "troubleshooter": "https://x"},
        },
    )
    feishu, _ = make_client(lambda r: response)

    with pytest.raises(RequestFailed) as info:
        send_text(feishu)

    assert info.value.code == 230002
    assert info.value.msg == "Bot is not in the chat"
    assert info.value.log_id == "abc"
    assert info.value.response.error["troubleshooter"] == "https://x"
    assert "230002" in str(info.value)


def test_http_error_without_json_raises(make_client):
    feishu, _ = make_client(lambda r: httpx2.Response(502, text="bad gateway"))

    with pytest.raises(RequestFailed) as info:
        send_text(feishu)

    assert info.value.response.status_code == 502
    assert info.value.code is None


def test_error_object_is_not_mistaken_for_the_message(make_client):
    feishu, _ = make_client(
        lambda r: httpx2.Response(200, json={"code": 1, "error": {"log_id": "x"}})
    )

    with pytest.raises(RequestFailed) as info:
        send_text(feishu)

    assert info.value.msg is None


def test_log_id_comes_from_the_header(make_client):
    feishu, _ = make_client(lambda r: ok(**{"X-Tt-Logid": "log-1"}))

    assert send_text(feishu).log_id == "log-1"


def test_response_tolerates_unknown_fields_and_nulls(make_client):
    feishu, _ = make_client(
        lambda r: ok({"message_id": "om_1", "root_id": None, "new_thing": [1]})
    )

    data = send_text(feishu).parsed_data

    assert data.root_id is None
    assert data.model_extra == {"new_thing": [1]}


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(
            429,
            json={"code": 99991400, "msg": "limit"},
            headers={"x-ogw-ratelimit-reset": "7"},
        ),
        # Older APIs signal the limit on a plain 400.
        httpx2.Response(
            400,
            json={"code": 99991400, "msg": "limit"},
            headers={"x-ogw-ratelimit-reset": "7"},
        ),
    ],
)
def test_rate_limit_is_recognised(make_client, response):
    feishu, _ = make_client(lambda r: response)

    with pytest.raises(RateLimitExceeded) as info:
        send_text(feishu)

    assert info.value.retry_after.total_seconds() == 7


def rate_limited(reset: str) -> httpx2.Response:
    return httpx2.Response(
        429,
        json={"code": 99991400, "msg": "limit"},
        headers={"x-ogw-ratelimit-reset": reset},
    )


def test_rate_limit_is_retried_even_for_post(make_client, monkeypatch):
    slept = []
    monkeypatch.setattr("time.sleep", slept.append)
    monkeypatch.setattr("random.uniform", lambda low, high: 0.25)
    answers = iter([rate_limited("3"), ok({"message_id": "om_1"})])
    feishu, server = make_client(lambda r: next(answers), auto_retry=True)

    assert send_text(feishu).parsed_data.message_id == "om_1"
    assert slept == [3.25]
    assert len(server.requests) == 2


@pytest.mark.parametrize(("pick", "expected"), [(min, 3), (max, 4)])
def test_rate_limit_jitter_only_adds_to_the_wait(
    make_client, monkeypatch, pick, expected
):
    # Retrying before the reset would only hit the limit again.
    slept = []
    monkeypatch.setattr("time.sleep", slept.append)
    monkeypatch.setattr("random.uniform", lambda low, high: pick(low, high))
    answers = iter([rate_limited("3"), ok({})])
    feishu, _ = make_client(lambda r: next(answers), auto_retry=True)

    send_text(feishu)

    assert slept == [expected]


def test_long_rate_limit_is_raised_instead_of_waited_for(make_client, monkeypatch):
    slept = []
    monkeypatch.setattr("time.sleep", slept.append)
    feishu, server = make_client(lambda r: rate_limited("3600"), auto_retry=True)

    with pytest.raises(RateLimitExceeded) as info:
        send_text(feishu)

    assert info.value.retry_after.total_seconds() == 3600
    assert slept == []
    assert len(server.requests) == 1


@pytest.mark.anyio
async def test_long_rate_limit_is_raised_instead_of_waited_for_async(
    make_client, monkeypatch
):
    slept = []

    async def sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr("anyio.sleep", sleep)
    feishu, server = make_client(lambda r: rate_limited("3600"), auto_retry=True)

    with pytest.raises(RateLimitExceeded):
        await feishu.rest.im.v1.message.async_get("om_1")

    assert slept == []
    assert len(server.requests) == 1


def test_rate_limit_at_the_cap_is_still_waited_for(make_client, monkeypatch):
    slept = []
    monkeypatch.setattr("time.sleep", slept.append)
    answers = iter([rate_limited("60"), ok({})])
    feishu, _ = make_client(lambda r: next(answers), auto_retry=True)

    send_text(feishu)

    assert len(slept) == 1
    assert slept[0] >= 60


def test_wait_cap_is_configurable(make_client, monkeypatch):
    slept = []
    monkeypatch.setattr("time.sleep", slept.append)
    answers = iter([rate_limited("3600"), ok({})])
    feishu, _ = make_client(
        lambda r: next(answers),
        auto_retry=RetryRateLimit(max_wait=timedelta(hours=2)),
    )

    send_text(feishu)

    assert len(slept) == 1
    assert slept[0] >= 3600


def test_server_error_on_post_is_not_replayed(make_client, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    feishu, server = make_client(lambda r: httpx2.Response(500), auto_retry=True)

    with pytest.raises(RequestFailed):
        send_text(feishu)

    assert len(server.requests) == 1


@pytest.mark.parametrize(("pick", "expected"), [(min, [0.5, 2, 4.5]), (max, [1, 4, 9])])
def test_server_error_backoff_is_jittered(make_client, monkeypatch, pick, expected):
    slept = []
    monkeypatch.setattr("time.sleep", slept.append)
    monkeypatch.setattr("random.uniform", lambda low, high: pick(low, high))
    feishu, server = make_client(lambda r: httpx2.Response(503), auto_retry=True)

    with pytest.raises(RequestFailed):
        feishu.rest.im.v1.message.get("om_1")

    assert slept == expected
    assert len(server.requests) == 4


def test_server_error_on_get_is_retried(make_client, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    answers = iter([httpx2.Response(503), ok({})])
    feishu, server = make_client(lambda r: next(answers), auto_retry=True)

    feishu.rest.im.v1.message.get("om_1")

    assert len(server.requests) == 2


def test_timeout_is_reported(make_client):
    def api(request):
        raise httpx2.ReadTimeout("slow", request=request)

    feishu, _ = make_client(api)

    from larkify.exception import RequestTimeout

    with pytest.raises(RequestTimeout):
        send_text(feishu)


def test_upload_sends_multipart(make_client):
    feishu, server = make_client(lambda r: ok({"image_key": "img_1"}))

    response = feishu.rest.im.v1.image.create(
        image_type="message", image=("a.png", io.BytesIO(b"PNGDATA"), "image/png")
    )

    request = server.requests[0]
    assert request.headers["content-type"].startswith("multipart/form-data")
    body = request.content
    assert b'name="image_type"' in body
    assert b"message" in body
    assert b'filename="a.png"' in body
    assert b"PNGDATA" in body
    assert response.parsed_data.image_key == "img_1"


def test_upload_survives_a_retry(make_client, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    bodies = []

    def api(request):
        bodies.append(request.read())
        if len(bodies) == 1:
            return httpx2.Response(429, json={"code": 99991400, "msg": "limit"})
        return ok({"image_key": "img_1"})

    feishu, _ = make_client(api, auto_retry=True)

    feishu.rest.im.v1.image.create(
        image_type="message", image=("a.png", io.BytesIO(b"PNGDATA"), "image/png")
    )

    assert b"PNGDATA" in bodies[0]
    assert b"PNGDATA" in bodies[1]


def test_upload_survives_a_token_replacement(make_client):
    bodies = []

    def api(request):
        bodies.append(request.read())
        if len(bodies) == 1:
            return httpx2.Response(400, json={"code": 99991663, "msg": "expired"})
        return ok({"image_key": "img_1"})

    feishu, _ = make_client(api)

    feishu.rest.im.v1.image.create(
        image_type="message", image=("a.png", io.BytesIO(b"PNGDATA"), "image/png")
    )

    assert b"PNGDATA" in bodies[1]


def test_upload_missing_a_required_file_is_rejected(make_client):
    feishu, server = make_client(lambda r: ok())

    with pytest.raises(ValidationError):
        feishu.rest.im.v1.image.create(image_type="message")

    assert server.requests == []


@pytest.mark.parametrize("validate", [True, False])
def test_keyword_named_fields_map_back_to_the_wire_name(make_client, validate):
    from pydantic import Field

    from larkify import FeishuModel

    class Body(FeishuModel):
        from_: str = Field(alias="from")

    feishu, _ = make_client(lambda r: ok(), rest_api_validate_body=validate)

    assert feishu.build_body(Body, UNSET, {"from_": "x"}) == {"from": "x"}


def test_nested_keyword_fields_are_sent_by_wire_name(make_client):
    feishu, server = make_client(lambda r: ok())

    feishu.rest.translation.v1.text.translate(
        source_language="en",
        text="hello",
        target_language="zh",
        glossary=[{"from": "a", "to": "b"}],
    )

    assert server.last_json["glossary"] == [{"from": "a", "to": "b"}]


def test_download_returns_bytes_and_name(make_client):
    feishu, _ = make_client(
        lambda r: httpx2.Response(
            200,
            content=b"\x89PNG",
            headers={
                "content-type": "image/png",
                "content-disposition": "attachment; filename*=UTF-8''%E5%9B%BE.png",
            },
        )
    )

    response = feishu.rest.im.v1.image.get("img_1")

    assert response.parsed_data == b"\x89PNG"
    assert response.file_name == "图.png"
    assert response.code is None


def test_streamed_download_is_not_buffered(make_client):
    class Chunks(httpx2.SyncByteStream):
        read = False

        def __iter__(self):
            Chunks.read = True
            yield from (b"ab", b"cd")

    feishu, _ = make_client(
        lambda r: httpx2.Response(
            200, stream=Chunks(), headers={"content-type": "application/octet-stream"}
        )
    )

    response = feishu.rest.im.v1.image.get("img_1", stream=True)

    assert Chunks.read is False
    assert b"".join(response.iter_bytes()) == b"abcd"


def test_failed_streamed_download_still_raises(make_client):
    feishu, _ = make_client(
        lambda r: httpx2.Response(200, json={"code": 234001, "msg": "bad"})
    )

    with pytest.raises(RequestFailed) as info:
        feishu.rest.im.v1.image.get("img_1", stream=True)

    assert info.value.code == 234001


def pages(answers):
    iterator = iter(answers)

    def api(request):
        return ok(next(iterator))

    return api


PAGES = [
    {"has_more": True, "page_token": "p2", "items": [{"chat_id": "1"}]},
    {"has_more": True, "page_token": "p3", "items": []},
    {"has_more": False, "page_token": "", "items": [{"chat_id": "2"}]},
]


def test_paginate_follows_page_tokens(make_client):
    feishu, server = make_client(pages(PAGES))

    chats = list(feishu.rest.paginate(feishu.rest.im.v1.chat.list, page_size=1))

    assert [c.chat_id for c in chats] == ["1", "2"]
    assert [r.url.params.get("page_token") for r in server.requests] == [
        None,
        "p2",
        "p3",
    ]
    assert all(r.url.params["page_size"] == "1" for r in server.requests)


@pytest.mark.anyio
async def test_async_paginate(make_client):
    feishu, _ = make_client(pages(PAGES))

    chats = [c async for c in feishu.rest.paginate(feishu.rest.im.v1.chat.async_list)]

    assert [c.chat_id for c in chats] == ["1", "2"]


def test_paginate_with_map_func(make_client):
    feishu, _ = make_client(pages(PAGES))

    ids = list(
        feishu.rest.paginate_with(
            feishu.rest.im.v1.chat.list,
            lambda response: [c.chat_id for c in response.parsed_data.items or []],
        )
    )

    assert ids == ["1", "2"]


def test_paginate_rejects_the_wrong_iteration_protocol(make_client):
    feishu, _ = make_client(pages(PAGES))

    with pytest.raises(TypeError):
        iter(feishu.rest.paginate(feishu.rest.im.v1.chat.async_list))


def test_paginate_detects_a_stuck_server(make_client):
    stuck = {"has_more": True, "page_token": "same", "items": [{"chat_id": "1"}]}
    feishu, _ = make_client(pages([stuck, stuck, stuck]))

    with pytest.raises(PaginationError):
        list(feishu.rest.paginate(feishu.rest.im.v1.chat.list))


def test_json_body_is_utf8(make_client):
    feishu, server = make_client(lambda r: ok())

    feishu.rest.im.v1.message.create(
        receive_id_type="open_id",
        receive_id="ou_1",
        msg_type="text",
        content=json.dumps({"text": "你好"}, ensure_ascii=False),
    )

    assert "你好" in server.requests[0].content.decode()
