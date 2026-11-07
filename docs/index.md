# larkify

[![license](https://img.shields.io/github/license/StarHeartHunt/larkify)](https://github.com/StarHeartHunt/larkify/blob/main/LICENSE)
[![pypi](https://img.shields.io/pypi/v/larkify?logo=python&logoColor=edb641)](https://pypi.org/project/larkify/)
![python](https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=edb641)
[![pyright](https://img.shields.io/badge/types-pyright-797952.svg?logo=python&logoColor=edb641)](https://github.com/microsoft/pyright)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

现代、完整类型标注的飞书 / Lark Python SDK

- :material-sync: 同步 / 异步同一套 API，所有接口都有 `create` 与 `async_create` 两种形式
- :material-api: 覆盖 1753 个服务端 API、205 个事件，代码由开放平台元数据生成
- :material-check-circle: 从参数到响应完整类型标注，`TypedDict` 校验入参字典，pydantic 校验请求体与响应
- :material-account-key: token 自动获取、缓存、失效重取，`refresh_token` 轮换并发安全
- :material-refresh: 限流与服务端错误自动重试，且不会重放非幂等请求
- :material-webhook: 事件订阅支持 Webhook 和长连接，后者直接使用 httpx2 的 WebSocket，不依赖 protobuf
- :material-lightning-bolt: 按需加载，`import larkify` 约 60ms

## 下一步

<div class="grid cards" markdown>

- :octicons-file-code-16: [安装](./installation.md)

    ---

    安装 larkify 和可选依赖

- :octicons-file-code-16: [快速开始](./quickstart/index.md)

    ---

    按场景跑通第一个请求或第一个事件

- :octicons-file-code-16: [使用](./usage/getting-started/authentication.md)

    ---

    认证、配置、调用接口、事件订阅的完整说明

- :octicons-file-code-16: [覆盖范围](./coverage.md)

    ---

    已验证的内容和已知缺口

</div>

## License

[MIT](https://github.com/StarHeartHunt/larkify/blob/main/LICENSE)。部分代码源自 githubkit 和 oapi-sdk-python，其许可声明见 [NOTICE](https://github.com/StarHeartHunt/larkify/blob/main/NOTICE)。
