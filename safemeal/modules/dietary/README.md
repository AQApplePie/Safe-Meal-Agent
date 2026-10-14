# Dietary

职责：维护过敏、忌口、偏好和食材 taxonomy 的确定性业务规则。

- 允许被普通接口和 Agent 共同复用。
- 禁止依赖 `agent/`、Workflow 或具体数据库实现。
- 领域契约位于 `contracts/`，规则和应用服务位于 `application/`。
