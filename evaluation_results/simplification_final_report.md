# SafeMeal 架构减法重构本次复核报告

状态：CORE_REFACTOR_VERIFIED / FULL_ACCEPTANCE_PENDING。未标记 COMPLETE：全项目既有格式检查尚未通过；真实模型/数据库 E2E 未执行。实质代码重构、核心回归、Ruff lint、mypy 类型检查、应用启动与关闭均通过。

## 基线与范围

HEAD：74ae66b4f6e23f5c99855c639bd735a304599333。任务开始时工作区已有未提交代码、审计与迭代日志；本次全部保留，没有 reset、提交、数据库操作或重训。此前报告归档到 simplification_previous_report.md，其数字属于前轮，不能算成本次新增成果。

## 删除了什么以及依据

| 删除项 | 依据 / 现有职责承担者 |
|---|---|
| _context_observations | 单消费者校验包装；Initializer 直接保留 Observation.model_validate |
| render_review_reply | 全源码和测试无消费者；Final Safety 已调用 render_conversational_review_reply |
| load_before_turn / load_active_menu_before_turn | 正式读取统一 load_context_before_turn 同事务快照；history-only 包装仅所有权测试调用，测试改用实际入口 |
| AgentContextBuilder._json_objects | 三个调用均只转调 to_json_object_list，直接调用现有转换 |
| resolve_constraints.history | 参数没有任何读取；历史测试数据移入 AgentContext，断言保留 |
| resume 独立结果、并发及超时实现 | 共用 process 原有规范化和运行边界，避免恢复遗漏菜单/完成度/降级 |
| Responder 的推荐完成度扫描 | 与 Reflector 同条件同转换，改用 recommendation_completion |
| assessment 的预过滤列表/集合 | 过滤名单与最终工具白名单不相交，输出不可能变化 |
| 第二份中文数量字典 | 同函数 number_values 已有相同一～十映射 |
| Initializer 静默空 requirements 分支 | Gateway 已覆盖独立入口解析；缺少已解析事实时明确拒绝 |

本轮未删除文件或状态字段；不以删除数量为目标。删除 5 个无独立逻辑的包装函数、1 个未使用参数；新建的 Gateway 私有函数由 process/resume 共同使用，承担实际共享行为，并非目录重包装。

## 责任与必要保护

Understand 解释任务、数量、目标和作用域，保留 NLU 不可用 fallback。PrepareContext 补全活动菜单引用/分类替换事实。DietarySafetyService 统一约束聚合；已有可信 requirements 直接消费，不再解析。Initializer 校验并准备状态；Planner 决定行动、共享预算更新；Executor 注入安全参数并执行；Observer 更新证据/进度；Reflector 评估完成度；Respond 组织证据；Safety 控制发布。

保留 requested_count、类别配额、硬过敏、UNKNOWN、去重和预算。保留 task_context/user_memory_context/dietary_context 模型证据，同时排除它们对真实工具失败/数量的干扰。ToolResult、Observation、tool_trace 生命周期不同。Checkpoint 历史路径兼容映射有真实恢复测试，不删除。菜单 allowed_names 的发布覆盖率与执行进度是不同阶段的同一配额算法。

独立 process 缺 requirements 时仍解析当前过敏/禁忌，不从原始历史重新挖约束；已解析输入不被重解释。直接绕过 Gateway 调用内图必须提供 requirements（可显式空契约），缺失将被拒绝。

## 验证

运行环境：/opt/homebrew/Caskroom/miniconda/base/envs/agent_env/bin/python，Python 3.12。默认 Python 3.13 缺 LangGraph、NLU venv 缺 pytest，均记录为 ENVIRONMENT_UNAVAILABLE，后续改用既有环境。

| 检查 | 基线 | 本轮结果 |
|---|---|---|
| pytest 全项目 | 245 passed, 1 skipped | 253 passed, 1 skipped |
| Ruff check safemeal tests | PASS | PASS |
| mypy safemeal | 临时恢复源码比对确认 31 项既有错误 | PASS，267 个源码文件无错误 |
| Ruff format 全项目 | 121 项既有格式债务（初查另含本轮新测试） | 121 项，新增差异全部修复；未全库格式化 |
| git diff --check | — | PASS |
| FastAPI lifespan + /health /livez /api /openapi.json | — | PASS，四接口 200，启动/关闭通过 |
| 真实外部模型/DB E2E | NOT EXECUTED | NOT EXECUTED；不能替代为 Mock 已通过 |

启动使用临时 MySQL 等价连接串与 /tmp Checkpoint/Upload 路径，只装配应用、测试非数据库接口，不连接或改动用户数据库。没有验证真实基础设施 readiness。

### 核心覆盖对应

| 验收行为 | 已运行覆盖 |
|---|---|
| 普通/精确食谱查询 | test_external_recipe_fallback、test_agent_graph |
| 推荐四道鱼 / 数量与类别 | test_count_contract；新增部分数量 Resume |
| 两荤两素一汤 / 复杂宴席 | test_agent_graph、test_request_frame_regressions、test_request_understanding_workflow |
| 重新推荐荤菜 / 第二道荤菜引用 | test_menu_context_modification、test_short_term_reference、test_context_and_agent_intent |
| 过敏原 / UNKNOWN / 否定偏好 | test_dietary_requirements、test_workflow、test_safety_memory_scope、test_control_plane_contracts |
| 历史约束不得错误继承 | 保留原历史数据和断言；test_raw_history_cannot_reactivate_a_previous_constraint |
| 工具失败 / 部分证据不足 | test_tool_status_contract、test_failure_report_fixes、test_external_recipe_fallback |
| Tool/Model Budget | test_loop_control_contract、test_runtime_budget、test_agent_control_boundaries |
| Human Approval / Resume / Timeout | test_agent_graph、test_checkpoint；新增 timeout/排队 timeout、菜单 metadata、PARTIAL 恢复 |
| HTTP/SSE 与 Persistence | test_stream、test_context_and_agent_intent、test_identity；TestClient 启动检查 |

所有失败、修复、环境检查保留在 simplification_iterations.md/json；没有仅保留最后成功运行。新增 8 项回归：独立 allergy、可信 requirements 不再解析、部分计数恢复、菜单 metadata、执行超时、排队超时、Frame allergy 共享解析、Initializer 缺契约拒绝。

## 实测简化指标（本轮开始工作区 → 本轮结束）

| 指标 | Before | After | Delta |
|---|---:|---:|---:|
| python_source_lines | 23496 | 23420 | -76 |
| initializer_lines | 147 | 140 | -7 |
| planner_lines | 661 | 658 | -3 |
| planner_if_branches | 29 | 30 | +1 |
| AgentState_fields | 29 | 29 | +0 |
| AgentContext_fields | 10 | 10 | +0 |
| WorkflowState_fields | 7 | 7 | +0 |

方法见 simplification_metrics.json：Python splitlines、类 AnnAssign 数、Planner 目录 ast.If 数。本轮源码减少 76 行，Initializer 减少 7 行，Planner 减少 3 行。Planner ast.If 增加 1，因为共用最终状态写回需要先判断是否调用模型；确定性路由集合没有变化，不能宣称分支数量减少。

权威语义正式入口本轮仍为 Outer Understand；低层无 Frame intent fallback 保留。约束规则实现收敛到同一个 service，调用场景仍有 Workflow 和独立 Gateway，两者不会在已解析输入时重复解释。原 29/10/7 状态字段全部有独立生命周期，保持。剩余未使用函数数量不能从词法扫描得出；初筛结果明确标 UNCERTAIN，不编造清零指标。

## 遗留问题与限制

- DEFERRED_ARCHITECTURE_DEBT：无 Frame 低层 IntentClassifier/规则兼容仍被独立调用使用，强删会失去模糊问题和生成/替换/记忆识别。
- DEFERRED_ARCHITECTURE_DEBT：外部 metadata reflect 双层摘要和长结果规范化有 API/SSE/历史持久化契约，未证明外部消费者可删除。
- 已修复基线 31 项类型错误：使用有限的 Literal/容器注解，消除循环变量类型冲突，明确 schema 验证边界；没有 mypy ignore、额外 Any 或禁用规则。初始失败和最终 PASS 输出均保留。
- PRE_EXISTING_FAILURE：121 个文件的既有格式差异。新增差异已修复；本次未进行无关的全项目格式重写。
- NOT EXECUTED：真实模型、实际 MySQL/Postgres、容器集成和完整生产 checkpoint 升级；不宣称真实模型 E2E 完成。
- 本轮仅校验当前/已有测试覆盖的历史模块 checkpoint 序列化，不能保证任意未被记录的旧 schema 可恢复。

以上限制使最终验收未达到 COMPLETE；核心行为、运行安全和本轮实质删除已经通过验证。

## 静态验收后续修复

类型修复额外涉及既有 NLU adapter、dietary resolver/preference_rules、RecipeService、composition 的类型推断；全部沿用原运行规则，原 253 项测试通过。不改 Prompt、模型输出 schema 或安全强度。因类型注解增加 17 行、格式修复调整行数，最终净减少以本报告实测表为准，不能沿用中间的 95 行。
