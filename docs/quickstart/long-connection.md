# 长连接接收事件

长连接不需要公网地址，也不需要处理加解密，需要安装 `larkify[ws]`。

=== "同步"

    ```python
    from larkify import AppAuthStrategy, Feishu
    from larkify.webhooks import EventDispatcher
    from larkify.webhooks.events.im import ImMessageReceiveV1Event
    from larkify.ws import WSClient

    feishu = Feishu(AppAuthStrategy("cli_xxx", "app_secret"))
    dispatcher = EventDispatcher()


    @dispatcher.on(ImMessageReceiveV1Event)
    def on_message(event: ImMessageReceiveV1Event) -> None:
        print(event.event.message.content)


    WSClient(feishu, dispatcher).run()
    ```

=== "异步"

    ```python
    from larkify import AppAuthStrategy, Feishu
    from larkify.webhooks import EventDispatcher
    from larkify.webhooks.events.im import ImMessageReceiveV1Event
    from larkify.ws import WSClient

    feishu = Feishu(AppAuthStrategy("cli_xxx", "app_secret"))
    dispatcher = EventDispatcher()


    @dispatcher.on(ImMessageReceiveV1Event)
    async def on_message(event: ImMessageReceiveV1Event) -> None:
        print(event.event.message.content)


    async def main() -> None:
        await WSClient(feishu, dispatcher).arun()
    ```

同步函数和协程函数都可以作为处理器，同步函数在工作线程中运行。

更多内容见[事件订阅](../usage/events.md)。
