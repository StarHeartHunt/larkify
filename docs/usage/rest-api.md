# 调用接口

调用路径是 `feishu.rest.<业务域>.<版本>.<资源>.<方法>`，每个方法都有同步和 `async_` 开头的异步两种形式。

## 传参

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

## 响应

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

## 分页

=== "同步"

    ```python
    for chat in feishu.rest.paginate(feishu.rest.im.v1.chat.list, page_size=50):
        print(chat.name)
    ```

=== "异步"

    ```python
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

## 上传与下载

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

## 未收录的接口

=== "同步"

    ```python
    resp = feishu.request(
        "GET",
        "/open-apis/unified_kms/v1/autonomous_keys",
        token_types=("tenant",),
    )
    print(resp.json())
    ```

=== "异步"

    ```python
    resp = await feishu.arequest(
        "GET",
        "/open-apis/unified_kms/v1/autonomous_keys",
        token_types=("tenant",),
    )
    print(resp.json())
    ```
