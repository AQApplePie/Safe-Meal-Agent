# 离线评测

评测执行器直接调用真实 Agent，并从同一次运行的 Trace 计算工具选择、检索命中、答案正确性、忠实度、延迟和 Token 等指标。答案质量由确定性断言与独立 LLM Judge 共同衡量。

```bash
# 静态检查数据集
python -m safemeal.evaluation audit

# 将冻结语料写入 Milvus
python -m safemeal.evaluation prepare

# 小规模无 Judge 冒烟
python -m safemeal.evaluation run --limit 3 --no-judge

# 完整评测（默认启用 LLM Judge）
export DEEPSEEK_API_KEY="your-deepseek-api-key"
python -m safemeal.evaluation run --output evaluation_results/latest.json
```

完整评测使用独立的 `deepseek-v4-pro` Judge，并会调用候选模型、Embedding
与 Rerank API。`--no-judge` 只关闭 Judge，Agent 候选模型仍会产生 API 调用。
评测报告只描述本次结果，不再承担线上质量门禁、分片恢复或基线回归职责。
