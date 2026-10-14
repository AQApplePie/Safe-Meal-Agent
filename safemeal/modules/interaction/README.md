# Interaction

用户食谱行为的业务边界。当前提供点赞、收藏的目标状态设置与单个食谱状态读取，以及去重浏览上报、本人最近浏览游标列表和租户内食谱榜单。

- `contracts`：身份（tenant/subject 分列）、交互状态、行为类型、历史记录及分页位置。
- `application`：验证并调用持久化端口，不依赖 Agent、HTTP、SQL 或 Redis。
- `ports`：事务内设置状态/读取事实的仓储协议。

SQL 实现在 infrastructure，HTTP 适配在 interfaces，组合根负责装配。
浏览历史由独立 HistoryService / HistoryRepository 承载，与点赞收藏共用认证身份契约。
榜单由 RankingService / RankingRepository / RankingStore 承载，SQL 事实定时重建 Redis 快照；今日按独立浏览用户，最受欢迎按有效点赞+收藏计分。
个人收藏列表和最多 100 个食谱的批量交互状态查询沿用 InteractionService / ReactionRepository，一次业务 SQL 完成查询，身份只来自认证依赖。
MQ 行为事件留待用户确认第六项。
