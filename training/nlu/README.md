# SafeMeal NLU 训练数据

本目录由 `scripts/generate_nlu_training_data.py` 生成，用于对 `Qwen/Qwen3-1.7B` 进行请求理解 LoRA 微调。

## 文件

- `data/train.jsonl`：4,800 条
- `data/valid.jsonl`：600 条
- `data/test.jsonl`：600 条
- `data/dataset_stats.json`：固定种子和类别统计
- `../external/crosswoz`：独立下载的辅助中文任务型对话数据，不直接混入核心数据

每条记录采用 MLX-LM chat JSONL 格式，并带有 `sample_id`、`category`、`group_id` 供审计；训练器会忽略这些额外字段。

## 重新生成

```bash
python3 scripts/generate_nlu_training_data.py
```

生成器使用固定种子 `20261002`，输出应稳定为 6,000 条。核心训练对全部唯一。食谱实体按 56/7/7 分配到 train/valid/test，三个 split 的食谱 ID 无交集，以避免菜名和纠错样本泄漏。

## 数据类别

- normal：1,500
- multi_constraint：1,000
- recipe_detail：800
- input_noise：1,000
- context_reference：800
- clarification：500
- out_of_scope：400

详细模型选择、训练、部署和 Agent 接入方式见 `docs/intent-understanding-small-model-guide.md`。

## 本机训练结果

- 基础模型：`models/Qwen3-1.7B`
- 微调方式：8 层 LoRA，rank 8，仅训练约 249 万参数（0.145%）
- 正式训练：1,200 步，并针对模糊推荐数量做 400 步低学习率增量训练
- 最终适配器：`artifacts/nlu-qwen3-1.7b-lora-final-v3`
- 测试集：loss 0.007，perplexity 1.008（抽取 100 个 batch）
- 独立行为验收：6/6 通过

适配器目录已加入 `.gitignore`，不会把约 39 MB 的本机训练产物误提交到 Git。

## 复现验收

在 Apple Silicon Mac 上激活安装了 `mlx-lm[train]` 的环境后运行：

```bash
.venv-nlu/bin/python scripts/evaluate_nlu_adapter.py \
  --adapter artifacts/nlu-qwen3-1.7b-lora-final-v3
```

验收覆盖菜名误触修复、礼貌语清洗、食材与规避约束、过敏记忆、上下文指代和缺少指代对象时的澄清。
