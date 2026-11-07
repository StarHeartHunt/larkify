# 商店应用

商店应用需要保存飞书每小时推送的 `app_ticket`，然后用 `.as_tenant(tenant_key)` 绑定租户调用接口。

=== "同步"

    ```python
    from larkify import Feishu, IsvAppAuthStrategy
    from larkify.webhooks import EventDispatcher
    from larkify.webhooks.events.application import AppTicketEvent

    auth = IsvAppAuthStrategy("cli_xxx", "app_secret")
    feishu = Feishu(auth)
    dispatcher = EventDispatcher(verification_token="...")


    @dispatcher.on(AppTicketEvent)
    def on_ticket(event: AppTicketEvent) -> None:
        auth.save_app_ticket(feishu, event.event.app_ticket)


    feishu.with_auth(auth.as_tenant("tenant_key")).rest.contact.v3.user.get("ou_xxx")
    ```

=== "异步"

    ```python
    from larkify import Feishu, IsvAppAuthStrategy
    from larkify.webhooks import EventDispatcher
    from larkify.webhooks.events.application import AppTicketEvent

    auth = IsvAppAuthStrategy("cli_xxx", "app_secret")
    feishu = Feishu(auth)
    dispatcher = EventDispatcher(verification_token="...")


    @dispatcher.on(AppTicketEvent)
    async def on_ticket(event: AppTicketEvent) -> None:
        await auth.async_save_app_ticket(feishu, event.event.app_ticket)


    async def main() -> None:
        tenant = feishu.with_auth(auth.as_tenant("tenant_key"))
        await tenant.rest.contact.v3.user.async_get("ou_xxx")
    ```

`dispatcher` 还需要接入事件来源，见[长连接](./long-connection.md)或 [Webhook](./webhook.md)。
