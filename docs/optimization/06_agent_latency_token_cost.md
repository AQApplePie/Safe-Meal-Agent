# Agent 第二项：延迟、Token 与成本观测（第 7/9 份）

日期：2026-10-10。范围：完成本项后暂停，等待确认再开始审批界面与恢复流程。

## 结果

聊天与审批恢复响应的 `metadata.observability` 现在包含工作流耗时、模型调用次数、输入/输出/缓存 Token、用量完整性、费用完整性及各次模型调用的阶段、耗时和结果。无价格或不完整用量返回 `estimated_cost: null`，避免把未知费用当成零。没有模型调用时费用为零。价格单位是配置价格的单位，字段明确标为 `configured_price_unit`，不是默认人民币或美元。

结构化输出修复和供应商路由重试经过同一计量入口；分别记录成功、结构校验失败和调用错误。耗时包括该调用内的 SDK 重试，SDK 内部重试次数不能从这个边界精确获得。请求和模型耗时采用单调时钟。此版本没有宣称 HTTP 首 Token 延迟，也没有把模型调用计数当成供应商实际账单请求数。

## 修复的计量问题

- 只有 total_tokens 时继续累计 Token 预算，但不能计算输入/输出费用；不再误报已完整计费且费用为零。
- 兼容 LangChain `cache_read`、DeepSeek `prompt_cache_hit_tokens`、OpenAI 风格 `prompt_tokens_details.cached_tokens`；缓存命中使用独立价格。
- 显式的零输出 Token 是合法用量；输入加输出与总量不一致时标为不完整。
- 非法类型、负数、NaN 等供应商用量不再使正常回答因计量解析而报错。
- 启动配置与运行时价格解析均拒绝负价格、NaN、无穷值。
- 使用 ContextVar 隔离并发请求，在异常退出后恢复上下文；恢复审批产生独立观测，不混入原请求用量。

价格仍由 `MODEL_PRICING_JSON` 配置，每百万 Token 定价，例如：

```json
{"example-model":{"input_cost_per_million":2,"output_cost_per_million":4,"cached_input_cost_per_million":1}}
```

以上数字只是计量测试示例，不代表 DeepSeek 现价。当前配置模型未配置对应价格，因此真实知识问答的费用为未知。供应商价格必须核对模型版本、缓存和时段后配置；不能把其他模型价格直接套到当前别名。[DeepSeek 官方价格说明](https://api-docs.deepseek.com/quick_start/pricing/)。

## 真实验证

沿用上一项隔离评测，使用合成 SQL 食谱、临时账号、真实 JWT/HTTP/Agent 和既有模型凭证；未修改日常 .env 或数据库。选择 L01 推荐与 L08 知识问答，各重复三次，并运行单 Prompt、一次检索和生产 Agent 三套系统：18 条任务，21 次实际模型调用（基线 12 次、Agent 9 次）。18 条结构验收通过；结构通过不等于知识事实准确，上一项记录的知识事实风险仍需后续检索证据方案处理。

|生产 Agent 任务|样本|工作流 p50|工作流 p95|模型调用总数|输入/输出 Token 总数|缓存输入 Token|
|---|---:|---:|---:|---:|---:|---:|
|L01 两道鱼类推荐|3|19.652 ms|62.457 ms|0|0 / 0|0|
|L08 食品知识问答|3|6597.419 ms|7096.130 ms|9|21558 / 2709|19968|

两类请求的 HTTP p50 分别为 28.640 ms 和 6606.180 ms。工作流耗时不包含 HTTP 鉴权和响应后的会话持久化。每组只有三次采样，采用最近秩 p95，此时就是最大样本；这是功能诊断，不能作为并发负载性能承诺。知识任务的九次调用完整报告了 Token，但费用完整性为 false，估算费用为 null。

没有为了降低耗时移除安全复核或更改模型、回答温度和业务规则。后续优化可以依据逐次调用阶段定位耗时，但本项不声称已经降低模型延迟。没有实现跨请求费用账本、供应商对账、监控告警和硬性预付额度。现有费用预算在调用返回后检查，不能保证正在执行的调用不超限。请求理解发生在执行预算之外时，观测仍记录调用和 Token，但费用可能未知；预算不应被理解为完整 HTTP 账单。

## 测试与架构审阅

新增十二项观测测试，覆盖请求并发隔离、上下文恢复、正常/恢复工作流、缓存计价、零输出、总量缺明细、异常字段和非法价格。最终全量 471 项通过、25 项跳过（11.19 秒），结果见回归 XML；Ruff、Mypy 和 diff 空白检查通过。25 个已有跳过项不计为已验证的真实基础设施测试；真实模型验证单独执行。

职责划分：`agent/runtime/observability.py` 仅持有请求局部数据，不导入 SDK、HTTP 或数据库；`runtime/budget.py` 继续负责用量解析与费用预算；LLM 基础设施适配器记录模型阶段和耗时；工作流入口生成响应 metadata；配置层负责拒绝非法价格。传统后端的精简运行入口没有新增 Agent/SDK 依赖。

观测数据只包含模型名称、阶段、数值和结果类别，不记录 Prompt、凭证、用户标识或异常对象。真实评测报告仍按上一项机制保留合成输入输出，以便复核。运行时模型调用列表受现有循环、修复和路由重试上限约束。并行调用耗时可能重叠，不能简单相加当作请求总耗时。

## 文件与复现

- 实现：`safemeal/agent/runtime/observability.py`、`budget.py`、`safemeal/agent/workflow/runner.py`、`safemeal/infrastructure/llm/openai_language_model_gateway.py`、`safemeal/config/settings.py`。
- 测试：`tests/refactor/test_agent_observability.py`。
- 证据：`evaluation_results/agent_observability_live.json`、`agent_observability_summary.json`、`agent_observability_regression.xml`。
- 汇总工具：`scripts/summarize_agent_observability.py`。

```sh
PYTHONPATH=. python scripts/evaluate_agent_live.py --allow-provider-calls --case-ids L01 L08 --repeats 3 --output evaluation_results/agent_observability_live.json
python scripts/summarize_agent_observability.py evaluation_results/agent_observability_live.json --output evaluation_results/agent_observability_summary.json
```

真实模型命令会产生供应商用量；普通单元测试不调用模型。
