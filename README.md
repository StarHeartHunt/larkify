# larkify

[![license](https://img.shields.io/github/license/StarHeartHunt/larkify)](https://github.com/StarHeartHunt/larkify/blob/main/LICENSE)
[![pypi](https://img.shields.io/pypi/v/larkify?logo=python&logoColor=edb641)](https://pypi.org/project/larkify/)
![python](https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=edb641)
[![pyright](https://img.shields.io/badge/types-pyright-797952.svg?logo=python&logoColor=edb641)](https://github.com/microsoft/pyright)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

现代、完整类型标注的飞书 / Lark Python SDK

[**文档**](https://starhearthunt.github.io/larkify/) | [**反馈问题**](https://github.com/StarHeartHunt/larkify/issues) | [**飞书开放平台**](https://open.feishu.cn/document/)

- 同步 / 异步同一套 API，所有接口都有 `create` 与 `async_create` 两种形式
- 覆盖 1753 个服务端 API、205 个事件，代码由开放平台元数据生成
- 从参数到响应完整类型标注，`TypedDict` 校验入参字典，pydantic 校验请求体与响应
- token 自动获取、缓存、失效重取，`refresh_token` 轮换并发安全
- 限流与服务端错误自动重试，且不会重放非幂等请求
- 事件订阅支持 Webhook 和长连接，后者直接使用 httpx2 的 WebSocket，不依赖 protobuf
- 按需加载，`import larkify` 约 60ms

## 快速开始

更多内容见[文档](https://starhearthunt.github.io/larkify/)。

### 安装

需要 Python 3.11+（来自 httpx2 的要求）。

```bash
pip install larkify

pip install "larkify[crypto]"  # 解密加密事件
pip install "larkify[ws]"      # 长连接
pip install "larkify[redis]"   # 多进程共享 token 缓存
pip install "larkify[all]"
```

### 使用

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

## 开发

见[贡献指南](https://starhearthunt.github.io/larkify/contributing/)。

## License

[MIT](https://github.com/StarHeartHunt/larkify/blob/main/LICENSE)。部分代码源自 githubkit 和 oapi-sdk-python，其许可声明见 [NOTICE](https://github.com/StarHeartHunt/larkify/blob/main/NOTICE)。
