# SafeMeal Agent 闭环验收摘要（2026-07-16）

## 结论

- 评测集静态审计通过：58 条，工具用例占比 67.24%，困难用例占比 46.55%，无审计问题。
- 冻结检索语料已重新准备：Milvus 8/8 写入，LightRAG 8/8 processed，0 failed。
- 本轮候选报告已完成 58/58，Judge 覆盖率 100%，报告文件为 `post-fixes-20260716.json`。
- 质量门禁仍未通过：15 项中 6 项通过、9 项失败，不能声称 Top-1、Hit@5、工具选择、安全红线、P95 等指标已达标。
- 相对 `baseline-pre-closure.json`，多数指标改善；但回归门禁仍未通过，因为 faithfulness 从 97.37% 降至 94.05%，超过允许下降 2 个百分点。
- Token 成本控制已达标：平均 token/request 从 16,959.07 降至 10,858.36，低于 12,000 门槛。
- 错误率和错误答案率已达标：error rate 从 5.17% 降至 1.72%，wrong answer rate 从 36.21% 降至 18.97%。

## 候选质量门禁

| 指标 | 实测 | 门槛 | 结果 |
|---|---:|---:|---|
| Route Top-1 | 72.41% | >= 90% | 失败 |
| Retrieval Hit@5 | 45.45% | >= 90% | 失败 |
| Context recall | 69.12% | >= 80% | 失败 |
| Tool decision accuracy | 86.21% | >= 90% | 失败 |
| Tool selection accuracy | 55.17% | >= 85% | 失败 |
| Parameter accuracy | 83.67% | >= 90% | 失败 |
| Tool result utilization | 78.21% | >= 80% | 失败 |
| Answer correctness | 81.72% | >= 80% | 通过 |
| Faithfulness | 94.05% | >= 90% | 通过 |
| Judge coverage | 100% | >= 95% | 通过 |
| Error rate | 1.72% | <= 5% | 通过 |
| Wrong answer rate | 18.97% | <= 20% | 通过 |
| Safety violation rate | 27.27% | = 0 | 失败 |
| P95 latency | 45.48 s | <= 30 s | 失败 |
| Average tokens/request | 10,858.36 | <= 12,000 | 通过 |

## 基线对比

- Route Top-1：56.90% -> 72.41%（+15.52 个百分点）
- Retrieval Hit@5：9.09% -> 45.45%（+36.36 个百分点）
- Context recall：54.41% -> 69.12%（+14.71 个百分点）
- Tool selection accuracy：41.38% -> 55.17%（+13.79 个百分点）
- Parameter accuracy：75.51% -> 83.67%（+8.16 个百分点）
- Answer correctness：65.60% -> 81.72%（+16.12 个百分点，已过门禁）
- Task completion rate：41.38% -> 50.00%（+8.62 个百分点）
- Error rate：5.17% -> 1.72%（改善 3.45 个百分点，已过门禁）
- Wrong answer rate：36.21% -> 18.97%（改善 17.24 个百分点，已过门禁）
- P95 latency：73.28 s -> 45.48 s（改善 27.79 s，但仍未过门禁）
- Average tokens/request：16,959.07 -> 10,858.36（改善 6,100.71，已过门禁）
- Faithfulness：97.37% -> 94.05%（下降 3.32 个百分点，回归门禁失败）

## 已完成的修复效果

1. 已有正确证据不再被附加工具失败直接覆盖：`tool-001` 中 `search_recipes` 成功、`get_recipe` 失败时，最终保留可用答案并标记 degraded，而不是返回统一错误。
2. 目标饮食安全查询避免不必要的推荐工具：`tool-019` 只调用 `dietary_safe_recipe_query`，耗时 7.25 s、4,778 tokens，任务完成。
3. KB-only 路由显著提升：`kb_only` path 的 Route Top-1 从 0% 提升到 100%；Milvus/LightRAG 均被实际调用。
4. 结构化输出校验修复机制已实现并有单元测试覆盖；本轮真实评测未触发 repair 调用，但 `direct-007` 未再出现结构化解析崩溃。
5. 上下文和工具结果体积已限制：平均 token/request 从 16,959.07 降至 10,858.36。

## 仍未达标原因

1. KB-only 虽然路由正确，但答案完整性不足：`kb-001/002/005/006/007/008` 多数是检索命中后缺少金标关键词或未正确暴露 source，导致任务完成率仍低。
2. 路由守卫偏“召回优先”，对 direct/refusal/clarification 有误检索副作用：`direct-001/002/006/007`、`refuse-005`、`clarify-001/003/004` 等样本出现不必要工具调用，拉低 Top-1、工具选择并增加延迟。
3. 饮食安全红线仍未达标：安全类样本中仍有 false safety/usefulness 问题，safety violation rate 保持 27.27%，需要继续收紧安全判定和拒答模板。
4. 长尾延迟仍高：`tool-006` 两个工具均 60 s 超时，单条耗时 148.74 s；若不做工具级快速失败、并发隔离或候选裁剪，P95 难以低于 30 s。
5. Faithfulness 相对基线下降：虽然仍高于 90% 门禁，但比基线下降 3.32 个百分点，回归门禁未通过，需要检查被强制检索后的回答是否引入了过度归纳。

## 报告文件

- `baseline-pre-closure.json`：58 条变更前基线 Judge 报告。
- `post-fixes-20260716.json`：本轮 58 条候选 Judge 与质量门禁报告。
- `post-fixes-20260716.progress.jsonl`：本轮逐样本进度与 Trace。
- `regression-post-fixes-20260716.json`：本轮基线回归报告。
- `acceptance-summary.md`：本摘要。

## 验证记录

- 单元/定向测试：`26 passed`。
- 关键 Agent runtime 与模型韧性测试：`20 passed`。
- Ruff 检查：通过。
- 运行态服务：API、Milvus、Neo4j、Prometheus、Alertmanager、Grafana 均在 Docker 中运行。
- 完整评测：58/58 生成报告；质量门禁未通过，回归门禁未通过。
