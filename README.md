# larkify

现代、完整类型标注的飞书 / Lark Python SDK

- 同步 / 异步同一套 API，所有接口都有 `create` 与 `async_create` 两种形式
- 覆盖 1753 个服务端 API、205 个事件，代码由开放平台元数据生成
- 从参数到响应完整类型标注，`TypedDict` 校验入参字典，pydantic 校验请求体与响应
- token 自动获取、缓存、失效重取，`refresh_token` 轮换并发安全
- 限流与服务端错误自动重试，且不会重放非幂等请求
- 事件订阅支持 Webhook 和长连接，后者直接使用 httpx2 的 WebSocket，不依赖 protobuf
- 按需加载，`import larkify` 约 60ms

需要 Python 3.11+（来自 httpx2 的要求）。

```bash
pip install larkify

pip install "larkify[crypto]"  # 解密加密事件
pip install "larkify[ws]"      # 长连接
pip install "larkify[redis]"   # 多进程共享 token 缓存
pip install "larkify[all]"
```

## 快速开始

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

需要连续发多个请求时用上下文管理器复用连接，否则每次调用都会新建连接：

```python
with Feishu(AppAuthStrategy("cli_xxx", "app_secret")) as feishu:
    ...


async def main() -> None:
    async with Feishu(AppAuthStrategy("cli_xxx", "app_secret")) as feishu:
        ...
```

### 传参

路径参数按位置传，查询参数和请求体字段按关键字传。请求体也可以整个通过 `data` 传字典或模型：

```python
from larkify import AppAuthStrategy, Feishu
from larkify.models.im.v1.message import CreateMessageBody

feishu = Feishu(AppAuthStrategy("cli_xxx", "app_secret"))

feishu.rest.im.v1.message.get("om_xxx", user_id_type="open_id")

feishu.rest.im.v1.message.create(
    receive_id_type="open_id",
    data={"receive_id": "ou_xxx", "msg_type": "text", "content": "{}"},
)
feishu.rest.im.v1.message.create(
    receive_id_type="open_id",
    data=CreateMessageBody(receive_id="ou_xxx", msg_type="text", content="{}"),
)
```

请求体在发送前由 pydantic 校验，缺少必填字段会在本地报错。`Feishu(..., rest_api_validate_body=False)` 可以关闭校验。文档里没有的字段不会被拦截，会原样发送。

字段名和 Python 关键字或 pydantic 保留名冲突时加下划线，例如 `from_`；传字典时使用接口原本的字段名。极少数接口的请求体字段和查询参数同名（如 `drive.v1.permission_member` 的 `type`），这时请求体只能走 `data`。

### 响应

`Response` 包装了 `httpx2.Response`：

| 属性 | 说明 |
| --- | --- |
| `parsed_data` | 校验后的 `data`，下载接口为 `bytes` |
| `code` / `msg` | 业务状态码和信息 |
| `log_id` | 向飞书支持反馈问题时使用的日志 ID |
| `json()` | 原始 JSON，`parsed_data` 校验不过时的兜底 |
| `file_name` | 下载文件名 |
| `raw_request` / `raw_response` | 底层 httpx2 对象 |

响应模型的字段都是 `T | None`，文档没写的字段保留在 `model_extra` 里。

### 分页

```python
for chat in feishu.rest.paginate(feishu.rest.im.v1.chat.list, page_size=50):
    print(chat.name)


async def main() -> None:
    async for chat in feishu.rest.paginate(feishu.rest.im.v1.chat.async_list):
        print(chat.name)
```

元素类型会被推导出来。响应里有多个列表、无法确定取哪一个时，用 `paginate_with` 自行挑选，第二个参数之后是传给接口的参数：

```python
users = feishu.rest.paginate_with(
    feishu.rest.contact.v3.group_member.simplelist,
    lambda response: response.parsed_data.memberlist or [],
    "group_id",
)
```

### 上传与下载

```python
resp = feishu.rest.im.v1.image.create(
    image_type="message",
    image=("cat.png", open("cat.png", "rb"), "image/png"),
)
image_key = resp.parsed_data.image_key

resp = feishu.rest.im.v1.image.get(image_key)
content = resp.parsed_data

# 大文件用流式，不会读入内存
resp = feishu.rest.drive.v1.file.download("file_token", stream=True)
with open(resp.file_name or "download", "wb") as f:
    for chunk in resp.iter_bytes():
        f.write(chunk)
```

### 未收录的接口

```python
resp = feishu.request(
    "GET",
    "/open-apis/unified_kms/v1/autonomous_keys",
    token_types=("tenant",),
)
print(resp.json())
```

## 认证

| 策略 | 场景 |
| --- | --- |
| `AppAuthStrategy(app_id, app_secret)` | 自建应用，自动管理 tenant / app access token |
| `IsvAppAuthStrategy(app_id, app_secret, app_ticket=...)` | 商店应用，用 `.as_tenant(tenant_key)` 绑定租户 |
| `OAuthTokenAuthStrategy(...)` | 用户身份，可自动刷新 |
| `OAuthWebAuthStrategy(...)` | 用授权码换取用户身份 |
| `TokenAuthStrategy(token)` | 自行管理的固定 token，`Feishu("t-xxx")` 是它的简写 |
| `UnauthAuthStrategy()` | 不带 token |

每个接口接受哪些 token 类型由生成代码声明，SDK 自动选择。比如同时支持两种 token 的接口，应用身份用 `tenant_access_token`，用户身份用 `user_access_token`。

切换身份用 `with_auth`，配置和缓存共享：

```python
from larkify import AppAuthStrategy, Feishu, OAuthToken

auth = AppAuthStrategy("cli_xxx", "app_secret")
feishu = Feishu(auth)

# 把用户引导到授权页
url = auth.get_authorize_url(
    feishu, "https://example.com/callback", scope="offline_access"
)

# 用回调里的 code 换 token
user = auth.as_web_user("code", "https://example.com/callback").exchange_token(feishu)
print(user.token, user.refresh_token)


# 已有 token 时
def save(token: OAuthToken) -> None:
    """refresh_token 只能用一次，新值必须持久化。"""


user.on_refresh = save
feishu.with_auth(user).rest.authen.v1.user_info.get()
```

`refresh_token` 是一次性的，并发刷新时 SDK 保证只消耗一次；新值只会返回一次，所以务必通过 `on_refresh` 保存，异步场景下它可以是协程函数。

商店应用需要保存飞书每小时推送的 `app_ticket`：

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

### tenant_access_token 接口

文档已把 `/open-apis/auth/v3/tenant_access_token/internal` 标记为历史版本，推荐改用 `POST /oauth/v3/token`（`client_credentials`，返回最长约 4KB 的 JWT）。本 SDK 默认使用新接口，需要旧接口时：

```python
AppAuthStrategy("cli_xxx", "app_secret", tenant_token_api="legacy")
```

没有配置 `oauth_base_url` 的私有部署会自动使用旧接口。

## 错误与重试

```python
from larkify import AppAuthStrategy, Feishu
from larkify.exception import RateLimitExceeded, RequestFailed, RequestTimeout

feishu = Feishu(AppAuthStrategy("cli_xxx", "app_secret"))

try:
    feishu.rest.im.v1.message.get("om_xxx")
except RateLimitExceeded as e:
    print(e.retry_after)
except RequestFailed as e:
    print(e.code, e.msg, e.log_id, e.response.error.get("troubleshooter"))
except RequestTimeout:
    ...
```

飞书的业务错误常以 HTTP 200 返回，SDK 会检查 `code`，非 0 一律抛 `RequestFailed`。

默认重试策略：

- 限流最多重试 3 次，按 `x-ogw-ratelimit-reset` 等待，再追加不超过 1 秒的随机抖动。需要等待超过 60 秒时不重试，直接抛 `RateLimitExceeded`，由调用方根据 `retry_after` 决定，上限可以通过 `RetryRateLimit(max_wait=...)` 调整。
- 5xx 最多重试 3 次，退避带随机抖动，**只针对幂等方法**，因为 POST 失败不代表没有生效，重放 `im.v1.message.create` 可能发出重复消息。

```python
from datetime import timedelta

from larkify import AppAuthStrategy, Feishu
from larkify.retry import RetryChainDecision, RetryOption, RetryRateLimit, RetryServerError


def retry_timeouts(exc, retry_count):
    return RetryOption(retry_count < 2, timedelta(seconds=1))


Feishu(AppAuthStrategy("a", "b"), auto_retry=False)
Feishu(AppAuthStrategy("a", "b"), auto_retry=retry_timeouts)
Feishu(
    AppAuthStrategy("a", "b"),
    auto_retry=RetryChainDecision(
        RetryRateLimit(max_retry=5, max_wait=timedelta(minutes=5)),
        RetryServerError(1),
    ),
)
```

## 配置

```python
from larkify import LARK_BASE_URL, AppAuthStrategy, Feishu
from larkify.cache import RedisCacheStrategy
from larkify.throttling import LocalThrottler
from redis import Redis

feishu = Feishu(
    AppAuthStrategy("cli_xxx", "app_secret"),
    base_url=LARK_BASE_URL,  # 使用 Lark
    timeout=60,
    proxy="http://127.0.0.1:7890",
    cache_strategy=RedisCacheStrategy(Redis(), prefix="myapp"),  # 多进程共享 token
    throttler=LocalThrottler(20),  # 限制并发数
)
```

`base_url` 只接受 https（本机回环地址除外），且不能内嵌账号密码，因为应用密钥会发往这里。

## 事件订阅

### 长连接

不需要公网地址，也不需要处理加解密。

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


WSClient(feishu, dispatcher).run()
```

同步函数和协程函数都可以作为处理器，同步函数在工作线程中运行。异步程序里用 `await WSClient(...).arun()`。

### Webhook

`EventDispatcher` 不绑定 Web 框架。下面以 FastAPI 为例：

```python
from fastapi import FastAPI, Request, Response
from larkify.webhooks import EventDispatcher

app = FastAPI()
dispatcher = EventDispatcher(encrypt_key="...", verification_token="...")


@app.post("/feishu/events")
async def events(request: Request) -> Response:
    result = await dispatcher.ahandle(await request.body(), request.headers)
    return Response(result.body, result.status_code, media_type=result.content_type)
```

URL 校验、解密、验签由 `handle` / `ahandle` 完成。没有配置任何凭证时会拒绝请求，避免接受伪造事件；确实不需要时显式传 `insecure_no_verification=True`。

飞书在超时未响应时会重推事件，耗时的工作应放到处理器之外，并用 `event.header.event_id` 去重。

处理器也可以按名称注册，这对 SDK 还不认识的事件有用，此时收到的是通用的 `EventV2`，`event.event` 为字典：

```python
@dispatcher.on("some.new.event_v1")
def on_new(event) -> None:
    print(event.event)
```

### 回调

`card.action.trigger`、`url.preview.get` 这类回调的处理器返回值会回传给飞书：

```python
from larkify.webhooks import CardActionTriggerEvent, CardActionTriggerResponse


@dispatcher.on(CardActionTriggerEvent)
def on_click(event: CardActionTriggerEvent) -> CardActionTriggerResponse:
    return CardActionTriggerResponse.model_validate(
        {"toast": {"type": "success", "content": "已处理"}}
    )
```

## 项目结构

```
larkify/
├── feishu.py, core.py     客户端、请求、响应检查、重试循环
├── auth/                  认证策略
├── cache/                 token 缓存
├── response.py            响应包装
├── rest/
│   ├── paginator.py       分页
│   └── <项目>/<版本>/      [生成] 接口客户端
├── models/<项目>/<版本>/   [生成] pydantic 模型与 TypedDict
├── webhooks/
│   ├── dispatcher.py      事件路由、验签
│   ├── crypto.py          AES 解密、签名
│   ├── callbacks.py       卡片回调模型（文档目录未收录，手写）
│   └── events/            [生成] 事件模型
└── ws/                    长连接与帧编解码
codegen/                   代码生成器
scripts/                   生成结果校验
schema/                    文档元数据快照（不入库）
```

## 代码生成

```bash
uv sync --all-extras
uv run python -m codegen fetch   # 抓取元数据到 schema/，约 6 分钟，可断点续传
uv run python -m codegen build   # 生成代码
```

飞书没有公开的 OpenAPI 文件，数据来自开放平台文档站点使用的接口：

| 来源 | 内容 |
| --- | --- |
| `/api/tools/server-side-api/list` | 接口目录 |
| `/api_explorer/v1/api_definition` | 机器可读定义，**字段全集**、精确类型、token、上传下载标记 |
| `/document_portal/v1/document/get_detail` | 渲染后的文档，更可靠的 `required`、枚举、描述和示例 |
| `/api/tools/server-side-event/list` | 事件目录，事件结构从文档表格和示例中解析 |

这些是文档站内部接口，不是公开 API，结构可能变化，`fetch` 届时需要调整。

生成流程值得注意的几点：

- 接口路径取自 `definition.apiPath`。目录的 `url` 字段有 10 处错误，比如缺版本号或路径参数。
- `definition.pagination` 漏标约三分之一的分页接口，所以按结构判断：传入 `page_token` 且响应有后续标记。
- 文档把递归结构全部内联（docx 单个接口的元数据达 7MB），模型按「名称 + 结构签名」去重，1753 个接口收敛为 4846 个模型。
- 文档示例和声明类型冲突的字段放宽为 `Any`，避免一个字段让整个响应解析失败。当前共 11 处。

## 测试

```bash
uv run pytest
```

依赖 `schema/` 快照的校验脚本：

```bash
uv run python scripts/check_generated.py   # 构建全部模型
uv run python scripts/check_endpoints.py   # 调用全部接口，比对 method、路径、参数、token
PYTHONPATH=. uv run python scripts/check_examples.py  # 用文档示例回放接口模型
PYTHONPATH=. uv run python scripts/check_events.py    # 用文档示例回放事件模型
PYTHONPATH=. uv run python scripts/check_official_sdk.py /path/to/oapi-sdk-python
```

### 验证范围

已验证：

- 全部接口的 sync / async 调用都能发出与元数据一致的请求（mock transport）
- 文档示例：835 个请求体、1182 个响应、194 个事件全部通过（含上述 11 处放宽）
- 与官方 SDK 1.7.5 对比：覆盖其 1619 个接口中的 1604 个，并多出 149 个
- 帧编码与官方 protobuf 实现逐字节一致，解密与官方实现双向互通
- 长连接通过本地 socket 服务器端到端测试

### 已知缺口

- 113 个旧版接口（`Version=old`，如 `ccm_sheet`）文档没有结构化数据，生成的是无类型方法，位于 `feishu.rest.<项目>.legacy`
- 官方 SDK 有、公开文档目录没有的 15 个接口（`unified_kms`、`block/v2` 等）未生成，可用 `feishu.request` 调用
- 同样情况的 8 个事件（如 `vc.note.generated_v1`）没有类型化模型，可按名称注册
- 不支持旧版卡片回调（`CardActionHandler`），请使用 `card.action.trigger`
- 不支持官方 SDK 的 `client_assertion` 无密钥认证

## License

[MIT](https://github.com/StarHeartHunt/larkify/blob/main/LICENSE)。部分代码源自 githubkit 和 oapi-sdk-python，其许可声明见 [NOTICE](https://github.com/StarHeartHunt/larkify/blob/main/NOTICE)。
