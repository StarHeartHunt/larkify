# 自建应用调用接口

用自建应用的 App ID 和 App Secret 创建 `Feishu` 实例，tenant / app access token 由 SDK 自动管理。

=== "同步"

    ```python
    from larkify import AppAuthStrategy, Feishu

    feishu = Feishu(AppAuthStrategy("cli_xxx", "app_secret"))

    resp = feishu.rest.im.v1.message.create(
        receive_id_type="open_id",
        receive_id="ou_xxx",
        msg_type="text",
        content='{"text": "你好"}',
    )
    print(resp.parsed_data.message_id)
    ```

=== "异步"

    ```python
    from larkify import AppAuthStrategy, Feishu

    feishu = Feishu(AppAuthStrategy("cli_xxx", "app_secret"))


    async def main() -> None:
        resp = await feishu.rest.im.v1.message.async_create(
            receive_id_type="open_id",
            receive_id="ou_xxx",
            msg_type="text",
            content='{"text": "你好"}',
        )
        print(resp.parsed_data.message_id)
    ```

调用路径是 `feishu.rest.<业务域>.<版本>.<资源>.<方法>`，与官方 SDK 的 `client.im.v1.message.create` 一一对应。

接下来可以看[调用接口](../usage/rest-api.md)，了解传参、响应、分页和上传下载。
