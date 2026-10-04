# SafeMealAgent 六层 Agent 架构

本文描述 Agent 子系统的代码边界。Workflow 的业务顺序保持为“理解请求、准备上下文、解析约束、调用 Agent、最终安全复核、保存记忆”；六层只约束 Agent 内部如何消费上下文、决策、调用工具和汇聚结果。

## 1. 入口网关层 `agent/gateway`

入口层是 Workflow 调用 Agent 的唯一公共入口，不是 HTTP 网关。

- 接收消息、会话 ID 和 `AgentContext`；
- 执行越权请求的确定性拦截；
- 设置并发、超时、模型预算和 Checkpoint `thread_id`；
- 启动或恢复 Agent 图；
- 将内部 State 转换为 `AgentProcessResponse`。

禁止：直接查询数据库、实现食谱业务、创建模型 SDK 客户端。

## 2. 编排层 `agent/orchestration`

编排层负责“什么时候运行哪个能力”，不负责能力的具体实现。

```text
initialize → plan → approval → execute → observe → reflect
                                            ↑          │
                                            └──────────┤继续执行
                                  plan ←───────────────┤重新规划
                               aggregate ←─────────────┘完成
```

- Plan：根据目标、上下文、工具说明和既有证据生成下一步行动；
- Execute：执行通过策略和审批的类型化工具调用；
- Observe：把原始结果标准化为证据、错误和安全状态；
- Reflect：判断证据是否充分以及继续、重规划还是结束；
- Aggregate：组织可追溯的回答草稿，交给 Workflow 做最终复核。

禁止：导入 `infrastructure` 或在图装配文件中声明业务节点实现。

## 3. 模型层 `agent/model`

模型层直接定义 Agent 所需的 `AgentModelGateway` 与 `IntentClassifier` 协议，提供 `plan`、`reflect`、`answer` 和结构化食谱生成等语义能力；具体 DashScope/OpenAI 兼容客户端仍位于 `infrastructure/llm`。

- Planner、Reflector 使用 Pydantic Structured Output；
- Schema 修复次数受限且计入预算；
- 模型异常转换为应用异常；
- Provider、Prompt、Token 和成本由统一网关管理。

禁止：Node 直接创建云厂商客户端或维护第二套 JSON Schema。

## 4. 工具层 `agent/tools`

工具层治理工具，具体食谱和检索适配器仍位于 `application/tool`。

- Registry：注册工具并检查未知、重复名称；
- Specification：发布用途、适用场景、禁用场景、输入约束和副作用；
- Policy：执行前注入可信硬约束并拒绝非法参数；
- Runtime：Pydantic 校验、超时、并发和标准错误转换。

模型看到的参数 Schema 与 Runtime 校验的 Pydantic 模型同源生成。

## 5. 记忆/上下文层 `agent/memory`

Workflow 负责从 MySQL、历史记录或未来的向量记忆中加载数据；Agent 记忆层只消费已经传入的 `AgentContext`。

- 把结构化过敏、禁忌和偏好转换为安全 Observation；
- 硬约束完整保留，不受 Top-K 相关性截断；
- 根据白名单模板重建记忆文本，避免把任意存储文本提升成指令；
- 不直接访问 MySQL、Redis、Milvus 或其他基础设施。

## 6. 汇聚层 `agent/aggregation`

汇聚层只使用 Observation 和 Reflection 结果生成 Agent 草稿。

- 合并工具证据；
- 对来源去重和归因；
- 对精确菜名查询使用确定性材料列表；
- 证据不足时明确降级；
- 输出结构化 Evidence 供 Workflow 最终食品安全复核。

禁止：在汇聚阶段再次调用工具，或绕过 Workflow 的最终安全门禁。

## 依赖规则

```text
Workflow → Gateway → Orchestration
                       ├→ Model Protocol ← Infrastructure Adapter
                       ├→ Tools → Application Tool → Service/Port
                       ├→ Memory ← AgentContext
                       └→ Aggregation

所有层 → Contracts
```

生产装配必须通过 `protocol.py`、`orchestration` 和 `tools` 的公共入口。实现本体均位于六层目录中；不保留旧模块转发、类型别名或重复协议。历史 Checkpoint 的类路径兼容由专用反序列化映射负责，不能成为保留旧代码结构的理由。
