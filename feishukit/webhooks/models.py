from typing import Any, ClassVar

from pydantic import Field

from feishukit.model import FeishuModel


class EventHeader(FeishuModel):
    event_id: str | None = None
    """事件 ID，重复推送时不变，可用于去重"""
    event_type: str | None = None
    """事件类型"""
    create_time: str | None = None
    """事件创建时间戳，单位：毫秒"""
    token: str | None = None
    """Verification Token"""
    app_id: str | None = None
    """应用 ID"""
    tenant_key: str | None = None
    """租户 Key"""


class EventV2(FeishuModel):
    """Event in the 2.0 format, also used by callbacks."""

    event_type: ClassVar[str] = ""

    schema_: str | None = Field(default=None, alias="schema")
    """事件模式"""
    header: EventHeader | None = None
    """事件头"""
    event: Any = None
    """事件体"""


class EventV1(FeishuModel):
    """Event in the legacy 1.0 format."""

    event_type: ClassVar[str] = ""

    uuid: str | None = None
    """事件的唯一标识"""
    token: str | None = None
    """Verification Token"""
    ts: str | None = None
    """事件发送的时间"""
    type: str | None = None
    """此处始终为 event_callback"""
    event: Any = None
    """事件体"""
