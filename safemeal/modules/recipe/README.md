# Recipe

职责：维护菜谱查询、分类和食材等可复用业务事实。

- 允许依赖本模块契约、端口和共享类型。
- 禁止依赖 `agent/`、LangGraph 或具体基础设施实现。
- 应用入口为 `application/recipe_service.py`，持久化与外部来源通过 `ports/` 抽象。
