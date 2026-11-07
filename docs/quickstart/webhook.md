# Webhook 接收事件

`EventDispatcher` 不绑定 Web 框架。下面以 FastAPI 为例：

```python
from fastapi import FastAPI, Request, Response
from larkify.webhooks import EventDispatcher
from larkify.webhooks.events.im import ImMessageReceiveV1Event

app = FastAPI()
dispatcher = EventDispatcher(encrypt_key="...", verification_token="...")


@dispatcher.on(ImMessageReceiveV1Event)
async def on_message(event: ImMessageReceiveV1Event) -> None:
    print(event.event.message.content)


@app.post("/feishu/events")
async def events(request: Request) -> Response:
    result = await dispatcher.ahandle(await request.body(), request.headers)
    return Response(result.body, result.status_code, media_type=result.content_type)
```

URL 校验、解密、验签由 `handle` / `ahandle` 完成。配置了 `encrypt_key` 时需要安装 `larkify[crypto]`。

更多内容见[事件订阅](../usage/events.md)。
