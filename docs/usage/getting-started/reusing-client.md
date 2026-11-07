# 复用客户端

需要连续发多个请求时用上下文管理器复用连接，否则每次调用都会新建连接：

=== "同步"

    ```python
    from larkify import AppAuthStrategy, Feishu

    with Feishu(AppAuthStrategy("cli_xxx", "app_secret")) as feishu:
        ...
    ```

=== "异步"

    ```python
    from larkify import AppAuthStrategy, Feishu


    async def main() -> None:
        async with Feishu(AppAuthStrategy("cli_xxx", "app_secret")) as feishu:
            ...
    ```
