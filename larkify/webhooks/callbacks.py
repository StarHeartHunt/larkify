"""Callbacks: events whose handler return value is sent back to the client.

Unlike ordinary events they are not listed in the event catalog, so these models
are written by hand.

https://open.feishu.cn/document/feishu-cards/card-callback-communication
"""

from typing import Any, ClassVar

from pydantic import Field

from larkify.model import FeishuModel

from .models import EventV2


class CallbackOperator(FeishuModel):
    tenant_key: str | None = None
    """回调触发者所在租户"""
    user_id: str | None = None
    """回调触发者的 user_id"""
    open_id: str | None = None
    """回调触发者的 open_id"""
    union_id: str | None = None
    """回调触发者的 union_id"""


class CallbackContext(FeishuModel):
    url: str | None = None
    """被预览的链接"""
    preview_token: str | None = None
    """链接预览 token"""
    open_message_id: str | None = None
    """卡片所在消息的 ID"""
    open_chat_id: str | None = None
    """卡片所在会话的 ID"""


class CallbackAction(FeishuModel):
    value: dict[str, Any] | str | None = None
    """交互组件绑定的开发者自定义回传数据"""
    tag: str | None = None
    """交互组件的标签"""
    option: str | None = None
    """下拉选择等组件选中的值"""
    timezone: str | None = None
    """用户时区"""
    name: str | None = None
    """组件的自定义唯一标识"""
    form_value: dict[str, Any] | None = None
    """表单提交的值"""
    input_value: str | None = None
    """输入框的值"""
    options: list[str] | None = None
    """多选组件选中的值"""
    checked: bool | None = None
    """勾选器的状态"""


class CardActionTriggerData(FeishuModel):
    operator: CallbackOperator | None = None
    """回调触发者"""
    token: str | None = None
    """更新卡片用的凭证"""
    action: CallbackAction | None = None
    """交互信息"""
    host: str | None = None
    """卡片展示场景"""
    delivery_type: str | None = None
    """卡片分发类型"""
    context: CallbackContext | None = None
    """卡片上下文"""


class CardActionTriggerEvent(EventV2):
    """卡片回传交互"""

    event_type: ClassVar[str] = "card.action.trigger"

    event: CardActionTriggerData | None = None
    """事件体"""


class UrlPreviewGetData(FeishuModel):
    operator: CallbackOperator | None = None
    """回调触发者"""
    host: str | None = None
    """链接展示场景"""
    context: CallbackContext | None = None
    """链接上下文"""


class UrlPreviewGetEvent(EventV2):
    """拉取链接预览数据"""

    event_type: ClassVar[str] = "url.preview.get"

    event: UrlPreviewGetData | None = None
    """事件体"""


class CallbackToast(FeishuModel):
    type: str | None = None
    """弹窗提示类型：info、success、error、warning"""
    content: str | None = None
    """提示内容"""
    i18n: dict[str, str] | None = None
    """多语言提示内容"""


class CallbackCard(FeishuModel):
    type: str | None = None
    """卡片类型：template 或 raw"""
    data: Any = None
    """卡片内容"""


class CardActionTriggerResponse(FeishuModel):
    """Return this from a `card.action.trigger` handler."""

    toast: CallbackToast | None = None
    """弹窗提示"""
    card: CallbackCard | None = None
    """更新后的卡片"""


class UrlPreviewInlineUrl(FeishuModel):
    copy_url: str | None = None
    """复制时使用的链接"""
    ios: str | None = None
    """iOS 端链接"""
    android: str | None = None
    """Android 端链接"""
    pc: str | None = None
    """PC 端链接"""
    web: str | None = None
    """Web 端链接"""


class UrlPreviewInline(FeishuModel):
    title: str | None = None
    """标题"""
    i18n_title: dict[str, str] | None = None
    """多语言标题"""
    image_key: str | None = None
    """图标的 image_key"""
    url: UrlPreviewInlineUrl | None = None
    """各端链接"""


class UrlPreviewGetResponse(FeishuModel):
    """Return this from a `url.preview.get` handler."""

    inline: UrlPreviewInline | None = Field(default=None)
    """内联预览"""
    card: CallbackCard | None = None
    """卡片预览"""
