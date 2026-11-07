import json

import pytest

from larkify.exception import WebhookVerificationFailed
from larkify.webhooks import (
    CardActionTriggerEvent,
    CardActionTriggerResponse,
    EventDispatcher,
    EventV2,
    decrypt,
    get_event_class,
    parse,
    parse_obj,
    sign,
    verify,
)
from larkify.webhooks.crypto import encrypt
from larkify.webhooks.events.application import AppTicketEvent
from larkify.webhooks.events.im import ImMessageReceiveV1Event

ENCRYPT_KEY = "my-encrypt-key"
TOKEN = "verification-token"

# Produced with the official SDK's AESCipher, see the interop notes in the README.
OFFICIAL_CIPHERTEXT = "MDEyMzQ1Njc4OWFiY2RlZtgjNrdr13hst6H3XbVDgL0bv3FS87ZnqWq1JWPraCsf"


def message_event(**header):
    return {
        "schema": "2.0",
        "header": {
            "event_id": "e1",
            "event_type": "im.message.receive_v1",
            "token": TOKEN,
            "create_time": "1608725989000",
            "app_id": "cli_1",
            "tenant_key": "t1",
            **header,
        },
        "event": {
            "sender": {"sender_id": {"open_id": "ou_1"}, "sender_type": "user"},
            "message": {"message_id": "om_1", "content": '{"text":"hi"}'},
        },
    }


def signed_headers(body: bytes, key: str = ENCRYPT_KEY) -> dict[str, str]:
    return {
        "X-Lark-Request-Timestamp": "1700000000",
        "X-Lark-Request-Nonce": "nonce",
        "X-Lark-Signature": sign(key, "1700000000", "nonce", body),
    }


def encrypted_delivery(payload: dict, key: str = ENCRYPT_KEY) -> bytes:
    plaintext = json.dumps(payload).encode()
    return json.dumps(
        {"encrypt": encrypt(key, plaintext, b"0123456789abcdef")}
    ).encode()


def test_decrypt_matches_the_official_implementation():
    assert decrypt(ENCRYPT_KEY, OFFICIAL_CIPHERTEXT).decode() == '{"text":"加密内容"}'


def test_signature_matches_the_documented_algorithm():
    import hashlib

    body = b'{"a":1}'
    expected = hashlib.sha256(b"1700000000nonce" + b"key" + body).hexdigest()

    assert sign("key", "1700000000", "nonce", body) == expected
    assert verify("key", "1700000000", "nonce", body, expected)
    assert not verify("key", "1700000000", "nonce", body, "0" * 64)


@pytest.mark.parametrize(
    "ciphertext", ["not base64!!", "c2hvcnQ=", OFFICIAL_CIPHERTEXT[:-4] + "AAAA"]
)
def test_malformed_ciphertext_is_rejected(ciphertext):
    with pytest.raises(WebhookVerificationFailed):
        decrypt(ENCRYPT_KEY, ciphertext)


def test_parse_builds_the_typed_event():
    event = parse(json.dumps(message_event()))

    assert isinstance(event, ImMessageReceiveV1Event)
    assert event.header.event_id == "e1"
    assert event.event.message.message_id == "om_1"
    assert event.event.sender.sender_id.open_id == "ou_1"


def test_parse_legacy_format():
    event = parse_obj(
        {
            "uuid": "u1",
            "token": TOKEN,
            "type": "event_callback",
            "event": {"type": "app_ticket", "app_id": "cli_1", "app_ticket": "tk"},
        }
    )

    assert isinstance(event, AppTicketEvent)
    assert event.event.app_ticket == "tk"


def test_unknown_event_types_are_still_usable():
    event = parse_obj(message_event(event_type="brand.new.event_v1"))

    assert type(event) is EventV2
    assert event.event["message"]["message_id"] == "om_1"


def test_event_models_load_on_demand():
    assert get_event_class("im.message.receive_v1") is ImMessageReceiveV1Event
    assert get_event_class("card.action.trigger") is CardActionTriggerEvent
    assert get_event_class("no.such.event") is None


def plain_dispatcher() -> EventDispatcher:
    return EventDispatcher(verification_token=TOKEN)


def test_url_verification_echoes_the_challenge():
    body = json.dumps(
        {"challenge": "abc", "token": TOKEN, "type": "url_verification"}
    ).encode()

    response = plain_dispatcher().handle(body, {})

    assert response.status_code == 200
    assert json.loads(response.body) == {"challenge": "abc"}


def test_url_verification_with_a_wrong_token_is_refused():
    body = json.dumps(
        {"challenge": "abc", "token": "wrong", "type": "url_verification"}
    ).encode()

    assert plain_dispatcher().handle(body, {}).status_code == 401


def test_challenge_cannot_inject_json():
    challenge = 'x","evil":"1'
    body = json.dumps(
        {"challenge": challenge, "token": TOKEN, "type": "url_verification"}
    ).encode()

    assert json.loads(plain_dispatcher().handle(body, {}).body) == {
        "challenge": challenge
    }


def test_encrypted_challenge():
    dispatcher = EventDispatcher(encrypt_key=ENCRYPT_KEY, verification_token=TOKEN)
    body = encrypted_delivery(
        {"challenge": "abc", "token": TOKEN, "type": "url_verification"}
    )

    assert json.loads(dispatcher.handle(body, {}).body) == {"challenge": "abc"}


def test_events_reach_handlers():
    dispatcher = plain_dispatcher()
    seen = []
    dispatcher.on(ImMessageReceiveV1Event)(seen.append)

    response = dispatcher.handle(json.dumps(message_event()).encode(), {})

    assert response.status_code == 200
    assert json.loads(response.body) == {"msg": "success"}
    assert isinstance(seen[0], ImMessageReceiveV1Event)


def test_base_classes_cannot_be_subscribed_to():
    with pytest.raises(ValueError):
        plain_dispatcher().on(EventV2)


def test_handlers_can_register_by_name():
    dispatcher = plain_dispatcher()
    seen = []
    dispatcher.on("im.message.receive_v1")(seen.append)

    dispatcher.handle(json.dumps(message_event()).encode(), {})

    assert len(seen) == 1


def test_forged_token_does_not_reach_handlers():
    dispatcher = plain_dispatcher()
    seen = []
    dispatcher.on(ImMessageReceiveV1Event)(seen.append)

    body = json.dumps(message_event(token="forged")).encode()

    assert dispatcher.handle(body, {}).status_code == 401
    assert seen == []


def test_missing_token_does_not_reach_handlers():
    dispatcher = plain_dispatcher()
    seen = []
    dispatcher.on(ImMessageReceiveV1Event)(seen.append)
    payload = message_event()
    del payload["header"]["token"]

    assert dispatcher.handle(json.dumps(payload).encode(), {}).status_code == 401
    assert seen == []


def test_signed_encrypted_event():
    dispatcher = EventDispatcher(encrypt_key=ENCRYPT_KEY, verification_token=TOKEN)
    seen = []
    dispatcher.on(ImMessageReceiveV1Event)(seen.append)
    body = encrypted_delivery(message_event())

    response = dispatcher.handle(body, signed_headers(body))

    assert response.status_code == 200
    assert seen[0].event.message.message_id == "om_1"


def test_headers_are_case_insensitive():
    dispatcher = EventDispatcher(encrypt_key=ENCRYPT_KEY)
    body = encrypted_delivery(message_event())
    headers = {k.lower(): v for k, v in signed_headers(body).items()}

    assert dispatcher.handle(body, headers).status_code == 200


@pytest.mark.parametrize(
    "tamper",
    [
        lambda h: h.pop("X-Lark-Signature"),
        lambda h: h.pop("X-Lark-Request-Nonce"),
        lambda h: h.update({"X-Lark-Signature": "0" * 64}),
        lambda h: h.update({"X-Lark-Request-Timestamp": "1"}),
    ],
)
def test_bad_signatures_do_not_reach_handlers(tamper):
    dispatcher = EventDispatcher(encrypt_key=ENCRYPT_KEY)
    seen = []
    dispatcher.on(ImMessageReceiveV1Event)(seen.append)
    body = encrypted_delivery(message_event())
    headers = signed_headers(body)
    tamper(headers)

    assert dispatcher.handle(body, headers).status_code == 401
    assert seen == []


def test_wrong_encrypt_key_is_refused():
    dispatcher = EventDispatcher(encrypt_key="other-key")
    body = encrypted_delivery(message_event())

    response = dispatcher.handle(body, signed_headers(body, "other-key"))

    assert response.status_code == 401


def test_encrypted_delivery_needs_a_key():
    body = encrypted_delivery(message_event())

    assert plain_dispatcher().handle(body, {}).status_code == 400


def test_dispatcher_without_credentials_fails_closed():
    dispatcher = EventDispatcher()
    seen = []
    dispatcher.on(ImMessageReceiveV1Event)(seen.append)

    response = dispatcher.handle(json.dumps(message_event()).encode(), {})

    assert response.status_code == 400
    assert seen == []


def test_verification_can_be_waived_explicitly():
    dispatcher = EventDispatcher(insecure_no_verification=True)
    seen = []
    dispatcher.on(ImMessageReceiveV1Event)(seen.append)

    dispatcher.handle(json.dumps(message_event()).encode(), {})

    assert len(seen) == 1


def test_events_without_handlers_are_acknowledged():
    response = plain_dispatcher().handle(json.dumps(message_event()).encode(), {})

    assert response.status_code == 200


def test_handler_failures_do_not_leak():
    dispatcher = plain_dispatcher()

    @dispatcher.on(ImMessageReceiveV1Event)
    def failing(event):
        raise RuntimeError("database password is hunter2")

    response = dispatcher.handle(json.dumps(message_event()).encode(), {})

    assert response.status_code == 500
    assert b"hunter2" not in response.body


def test_malformed_body_is_a_client_error():
    dispatcher = plain_dispatcher()

    assert dispatcher.handle(b"not json", {}).status_code == 400
    assert dispatcher.handle(b"[1,2]", {}).status_code == 400


def card_delivery():
    return {
        "schema": "2.0",
        "header": {"event_type": "card.action.trigger", "token": TOKEN},
        "event": {
            "operator": {"open_id": "ou_1"},
            "action": {"tag": "button", "value": {"k": "v"}},
        },
    }


def test_callback_answers_with_the_handler_result():
    dispatcher = plain_dispatcher()

    @dispatcher.on(CardActionTriggerEvent)
    def on_click(event):
        assert event.event.action.value == {"k": "v"}
        return CardActionTriggerResponse.model_validate(
            {"toast": {"type": "info", "content": "done"}}
        )

    response = dispatcher.handle(json.dumps(card_delivery()).encode(), {})

    assert json.loads(response.body) == {"toast": {"type": "info", "content": "done"}}


def test_callback_may_return_a_dict():
    dispatcher = plain_dispatcher()
    dispatcher.on(CardActionTriggerEvent)(lambda e: {"toast": {"content": "x"}})

    response = dispatcher.handle(json.dumps(card_delivery()).encode(), {})

    assert json.loads(response.body) == {"toast": {"content": "x"}}


@pytest.mark.anyio
async def test_ahandle_runs_sync_and_async_handlers():
    dispatcher = plain_dispatcher()
    seen = []

    @dispatcher.on(ImMessageReceiveV1Event)
    async def first(event):
        seen.append("async")

    @dispatcher.on(ImMessageReceiveV1Event)
    def second(event):
        seen.append("sync")

    await dispatcher.ahandle(json.dumps(message_event()).encode(), {})

    assert seen == ["async", "sync"]


def test_async_handler_in_sync_handle_is_reported():
    dispatcher = plain_dispatcher()

    @dispatcher.on(ImMessageReceiveV1Event)
    async def handler(event): ...

    response = dispatcher.handle(json.dumps(message_event()).encode(), {})

    assert response.status_code == 400
    assert b"ahandle" in response.body
