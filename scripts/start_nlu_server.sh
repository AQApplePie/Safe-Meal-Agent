#!/bin/sh
# 启动 SafeMeal 微调意图模型；默认仅监听本机，供非 Docker 后端使用。
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
NLU_HOST=${NLU_HOST:-127.0.0.1}
NLU_PORT=${NLU_PORT:-18080}

cd "$PROJECT_DIR"
exec .venv-nlu/bin/mlx_lm.server \
  --model models/Qwen3-1.7B \
  --adapter-path artifacts/nlu-qwen3-1.7b-lora-final-v3 \
  --host "$NLU_HOST" \
  --port "$NLU_PORT" \
  --temp 0 \
  --max-tokens 420 \
  --chat-template-args '{"enable_thinking":false}' \
  --log-level INFO
