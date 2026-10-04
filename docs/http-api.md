# 聊天和文件知识库接口

业务接口默认前缀 `/api/v1`。注册、登录、刷新和退出之外的业务接口使用
`Authorization: Bearer <access_token>`。聊天身份完全来自访问令牌，客户端传入的
`user_id` 不参与资源归属；知识文件和入库任务按令牌中的 `tenant_id` 隔离。

## 身份

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/auth/register` | 邮箱和密码注册，并返回访问令牌与刷新令牌 |
| POST | `/auth/login` | 登录并返回令牌 |
| POST | `/auth/refresh` | 旋转刷新令牌并签发新的令牌对 |
| POST | `/auth/logout` | 撤销刷新令牌，可重复调用 |
| GET | `/auth/me` | 查询当前账号 |

访问令牌有效期由 `AUTH_ACCESS_TOKEN_MINUTES` 控制。刷新令牌只以 SHA-256 摘要入库，
每次刷新都会轮换；检测到旧刷新令牌被再次使用时，该账号的全部刷新令牌和现有访问
令牌都会失效。生产环境必须设置随机且保密的 `AUTH_JWT_SECRET`。

## 聊天

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/chat/` | 发送消息，首次请求自动创建会话 |
| POST | `/chat/stream` | 流式进度及审查后的回答 |
| GET | `/chat/history/{session_id}` | 分页读取消息历史 |
| GET | `/chat/sessions` | 列出会话 |
| GET/PATCH/DELETE | `/chat/sessions/{session_id}` | 查看、修改、删除会话 |
| DELETE | `/chat/sessions/{session_id}/messages` | 清空消息，保留会话 |
| GET | `/chat/memories` | 查看饮食记忆 |
| PATCH/DELETE | `/chat/memories/{memory_id}` | 明确纠正、归档记忆 |
| POST | `/chat/resume` | 批准或拒绝已暂停的操作，按令牌身份校验会话归属 |

旧的 DELETE `/chat/sessions/{session_id}` 清空行为改为 `/messages` 子资源；该旧路径现在表示删除整个会话。仓库内前端已同步修改，外部客户端必须迁移。独立 `/sessions`、`/memories`、`/agent` 接口删除，不保留兼容转发。用户通过聊天声明新的偏好，不再提供单独的记忆抽取 HTTP 接口。

## 文件知识库

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/knowledge/files` | multipart 上传文件并同步解析入库 |
| POST | `/knowledge/files/async` | multipart 上传并提交后台入库任务，需 Redis 队列 |
| GET | `/knowledge/ingestion-jobs/{job_id}` | 查询当前租户的入库任务 |
| GET | `/knowledge/files` | 查看当前租户的文件记录及处理状态 |
| GET | `/knowledge/files/{file_id}` | 查看文件元数据 |
| GET | `/knowledge/files/{file_id}/content` | 下载原始文件 |
| DELETE | `/knowledge/files/{file_id}` | 清理向量、全文索引，再删除文件和关联记录 |

每个新入库文件在上传目录 `.documents/` 保存关联记录：租户、文件 ID、document_id、保存位置及 processing/indexed/failed/deleting 状态。解析失败仍保留记录供查询和清理。索引删除失败不删除原文件，保留 deleting 状态供重试。正在入库的文件不能删除，避免后台任务在删除后重新写入索引。

升级前的上传文件没有这些归属记录，不会自动出现在新文件列表，也不会通过新下载接口暴露。旧文件和索引没有被自动删除；需要确认原 tenant_id 和 document_id 后迁移关联记录，或重新上传后由管理员清理旧数据。不要把未知归属文件统一归给默认租户。异常进程终止可能留下 processing 记录，需确认没有入库任务继续运行后由管理员恢复；当前没有自动恢复任务。

原 `/upload`、`/knowledge/recipes`、`/knowledge/search`、`/knowledge/stats`、`/knowledge/clear`、`/integrations/status` 删除。Agent 的内部知识检索能力保留，食谱 JSON 直接入库和通用文件上传接口删除。

基本 `/health`、`/livez`、`/readyz` 探针继续保留，不属于业务 router。
