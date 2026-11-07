from collections.abc import Mapping
import importlib
import json
from typing import Any

from feishukit.exception import WebhookError

from .callbacks import CardActionTriggerEvent, UrlPreviewGetEvent
from .events import EVENT_MODULES
from .models import EventV1, EventV2

CALLBACKS: dict[str, type[EventV2]] = {
    CardActionTriggerEvent.event_type: CardActionTriggerEvent,
    UrlPreviewGetEvent.event_type: UrlPreviewGetEvent,
}


def event_type_of(data: Mapping[str, Any]) -> str:
    """Read the event type from a delivery, in either format."""
    header = data.get("header")
    if isinstance(header, Mapping) and header.get("event_type"):
        return str(header["event_type"])

    event = data.get("event")
    if isinstance(event, Mapping) and event.get("type"):
        return str(event["type"])

    raise WebhookError("delivery does not name an event type")


def get_event_class(event_type: str) -> type[EventV1 | EventV2] | None:
    """Find the model of an event type. Modules are imported on demand."""
    if (callback := CALLBACKS.get(event_type)) is not None:
        return callback
    if (location := EVENT_MODULES.get(event_type)) is None:
        return None
    module, class_name = location
    return getattr(
        importlib.import_module(f"feishukit.webhooks.events.{module}"), class_name
    )


def parse_obj(data: Mapping[str, Any]) -> EventV1 | EventV2:
    """Build the event model from a decoded delivery.

    Types the SDK does not know about yet are still delivered, as the generic
    base model with the raw `event` dictionary.
    """
    event_class = get_event_class(event_type_of(data))
    if event_class is None:
        event_class = EventV2 if "header" in data else EventV1
    return event_class.model_validate(data)


def parse(payload: str | bytes) -> EventV1 | EventV2:
    """Build the event model from a decrypted delivery body."""
    try:
        data = json.loads(payload)
    except ValueError as e:
        raise WebhookError("delivery is not JSON") from e
    if not isinstance(data, dict):
        raise WebhookError("delivery is not a JSON object")
    return parse_obj(data)
