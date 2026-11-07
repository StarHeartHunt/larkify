# 覆盖范围

## 验证范围

已验证：

- 全部接口的 sync / async 调用都能发出与元数据一致的请求（mock transport）
- 文档示例：835 个请求体、1182 个响应、194 个事件全部通过（含[生成时放宽的 11 处字段](./contributing.md#代码生成)）
- 与官方 SDK 1.7.5 对比：覆盖其 1619 个接口中的 1604 个，并多出 149 个
- 帧编码与官方 protobuf 实现逐字节一致，解密与官方实现双向互通
- 长连接通过本地 socket 服务器端到端测试

## 已知缺口

- 113 个旧版接口（`Version=old`，如 `ccm_sheet`）文档没有结构化数据，生成的是无类型方法，位于 `feishu.rest.<项目>.legacy`
- 官方 SDK 有、公开文档目录没有的 15 个接口（`unified_kms`、`block/v2` 等）未生成，可用 [`feishu.request`](./usage/rest-api.md#未收录的接口) 调用
- 同样情况的 8 个事件（如 `vc.note.generated_v1`）没有类型化模型，可[按名称注册](./usage/events.md#按名称注册)
- 不支持旧版卡片回调（`CardActionHandler`），请使用 [`card.action.trigger`](./usage/events.md#回调)
- 不支持官方 SDK 的 `client_assertion` 无密钥认证
