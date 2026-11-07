# 事件订阅

事件由 `EventDispatcher` 路由到处理器，事件来源可以是长连接或 Webhook，两者的完整示例见[长连接接收事件](../quickstart/long-connection.md)和 [Webhook 接收事件](../quickstart/webhook.md)。

## 长连接

不需要公网地址，也不需要处理加解密。同步函数和协程函数都可以作为处理器，同步函数在工作线程中运行。异步程序里用 `await WSClient(...).arun()`。

## Webhook

`EventDispatcher` 不绑定 Web 框架，把原始请求体和请求头交给 `handle` / `ahandle`，再把返回结果写回响应即可。URL 校验、解密、验签都由这两个方法完成。

没有配置任何凭证时会拒绝请求，避免接受伪造事件；确实不需要时显式传 `insecure_no_verification=True`。

!!! warning

    飞书在超时未响应时会重推事件，耗时的工作应放到处理器之外，并用 `event.header.event_id` 去重。

## 按名称注册

处理器也可以按名称注册，这对 SDK 还不认识的事件有用，此时收到的是通用的 `EventV2`，`event.event` 为字典：

```python
@dispatcher.on("some.new.event_v1")
def on_new(event) -> None:
    print(event.event)
```

## 回调

`card.action.trigger`、`url.preview.get` 这类回调的处理器返回值会回传给飞书：

```python
from larkify.webhooks import CardActionTriggerEvent, CardActionTriggerResponse


@dispatcher.on(CardActionTriggerEvent)
def on_click(event: CardActionTriggerEvent) -> CardActionTriggerResponse:
    return CardActionTriggerResponse.model_validate(
        {"toast": {"type": "success", "content": "已处理"}}
    )
```
