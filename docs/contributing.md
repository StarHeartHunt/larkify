# 贡献指南

## 开发环境

需要先安装 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --all-extras
```

## 项目结构

```text
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
docs/                      文档站
scripts/                   生成结果校验
schema/                    文档元数据快照（不入库）
```

## 代码生成

```bash
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

!!! warning

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

这些校验覆盖的内容见[覆盖范围](./coverage.md)。

## 文档

```bash
uv run --group docs mkdocs serve          # 本地预览
uv run --group docs mkdocs build --strict # 与 CI 相同的检查
```

推送到 `main` 后由 `.github/workflows/docs.yml` 构建并发布到 GitHub Pages。
