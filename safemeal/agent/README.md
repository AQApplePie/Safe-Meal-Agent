# Agent

职责：维护请求理解、会话上下文、外层控制流和内层决策循环。

- 允许依赖 `modules/*` 的应用服务与契约，以及自身的下层组件。
- 禁止被 `modules/*` 反向依赖；禁止持有 SQL、检索引擎或饮食领域规则实现。
- 外层入口为 `workflow/`，内层循环为 `runtime/orchestration/`，工具适配器位于 `runtime/tools/`。
- 对外执行入口位于 `gateway/`。
