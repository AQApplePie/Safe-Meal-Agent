# SafeMeal Agent 评测体系

本目录是当前模块化单体的离线评测实现。执行器直接调用
`AgentGraphRunnerService.process(..., include_trace=True)`，因此路由、模型调用、工具参数、
工具结果、耗时与 Token 都来自同一次真实 Agent 运行，不依赖额外的 Evaluation Service。

## 指标与门禁

默认绝对门禁与设计图一致：路由 Top-1 ≥ 90%、Hit@5 ≥ 90%、context recall ≥ 0.8、
faithfulness ≥ 0.9、answer correctness ≥ 0.8；另外记录工具决策、工具选择、参数 Schema
合法率、语义参数准确率、结果断言、工具结果利用率、误拒率、错答率、安全红线、P95、
Token 和按难度/路径分层的结果。没有适用样本的检索或 Judge 指标会标记为 skipped，
不会伪造为 0。正式门禁同时要求 Judge 覆盖率 ≥ 95%，因此 `--no-judge` 适合冒烟，
不能冒充完整质量验收。

答案正确性采用“确定性标签 + 独立 Judge”双轨：Judge 正常时使用结构化评分；Judge 调用
失败时保留错误并回退到确定性标签。faithfulness 只允许引用本次 Trace 中真实存在的
证据 ID，引用虚构 ID 会直接记 0。

## 评测集

`agent_eval_v3.jsonl` 含 58 条人工复核样本，覆盖 direct、kb_only、tool_only、kb_tool、
clarification、refusal 六种路径，以及 easy/medium/hard、自然表达/口语/错别字/歧义输入。
工具样本超过 30%，困难样本超过 30%。每条样本均包含稳定 ID、意图、标准答案、首选
路由、预期工具、参数语义断言、结果事实、检索证据、回答约束和标注来源。

冻结的 `retrieval_corpus.jsonl` 使用稳定 `document_id`。首次测 Milvus/LightRAG 前显式入库：

```bash
python -m back.evaluation prepare --target both
```

该命令会写外部索引；普通 `audit` 和 `run` 不会自动修改索引。

## 使用

```bash
# 只做静态审计，不调用模型或数据库
python -m back.evaluation audit

# 三条无 Judge 的链路冒烟
python -m back.evaluation run --limit 3 --no-judge \
  --output evaluation_results/smoke.json

# 完整评测并让质量门禁决定退出码
python -m back.evaluation run --enforce-gates \
  --output evaluation_results/latest.json

# 只跑当前已准备的 core + MySQL + Neo4j 样本
python -m back.evaluation run --available-feature mysql \
  --available-feature neo4j --no-judge

# 与基线比较；质量默认最多下降 2%，成本默认最多增加 10%
python -m back.evaluation regression \
  --baseline evaluation_results/baseline.json \
  --candidate evaluation_results/latest.json
```

完整评测需要 `.env` 中的模型凭据、MySQL 样例数据及相应的可选基础设施。配置文件和
数据集都会写入 SHA-256，报告可复现地记录模型、Prompt 版本、工具策略及选中样本数。
