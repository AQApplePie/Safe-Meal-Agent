"""Evidence-bounded LLM judge for correctness and faithfulness."""

from __future__ import annotations

import json
import os
from time import perf_counter
from typing import Protocol

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from safemeal.evaluation.evaluation_contracts import (
    CaseEvaluationResult,
    ClaimAssessment,
    EvaluationCase,
    JudgeProfile,
    JudgeResult,
)


class JudgePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_correctness: float = Field(ge=0, le=1)
    faithfulness: float = Field(ge=0, le=1)
    task_completed: bool
    rationale: str
    claims: list[ClaimAssessment] = Field(default_factory=list)


class AnswerJudge(Protocol):
    async def evaluate(
        self, case: EvaluationCase, result: CaseEvaluationResult
    ) -> JudgeResult: ...


def _credential(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _usage(raw: object) -> tuple[int, int, int, bool]:
    metadata = getattr(raw, "usage_metadata", None) or {}
    if not isinstance(metadata, dict):
        return 0, 0, 0, False
    input_tokens = int(metadata.get("input_tokens") or 0)
    output_tokens = int(metadata.get("output_tokens") or 0)
    total_tokens = int(metadata.get("total_tokens") or input_tokens + output_tokens)
    return input_tokens, output_tokens, total_tokens, bool(metadata)


def _evidence(
    result: CaseEvaluationResult, *, max_chars: int = 24_000
) -> tuple[str, set[str]]:
    records: list[dict[str, object]] = []
    identifiers: set[str] = set()
    calls = result.trace.get("tool_calls", [])
    if isinstance(calls, list):
        for index, call in enumerate(calls, start=1):
            if not isinstance(call, dict) or not call.get("ok"):
                continue
            evidence_id = str(call.get("call_id") or f"tools-{index}")
            identifiers.add(evidence_id)
            records.append(
                {
                    "evidence_id": evidence_id,
                    "tools": call.get("tool_name"),
                    "result": call.get("result"),
                }
            )
    text = json.dumps(records, ensure_ascii=False, default=str)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[证据已截断]"
    return text, identifiers


class OpenAICompatibleJudge:
    """A separate, deterministic judge prompt with evidence-ID validation."""

    def __init__(
        self,
        judge: JudgeProfile,
    ) -> None:
        self.model_name = judge.model
        api_key = _credential(judge.api_key_env)
        if not api_key:
            raise RuntimeError(f"评审模型缺少凭据：{judge.api_key_env}")
        self._model = ChatOpenAI(
            model=self.model_name,
            api_key=SecretStr(api_key),
            base_url=judge.base_url,
            temperature=judge.temperature,
            max_retries=2,
            timeout=90,
        )

    async def evaluate(
        self, case: EvaluationCase, result: CaseEvaluationResult
    ) -> JudgeResult:
        started = perf_counter()
        evidence, valid_ids = _evidence(result)
        prompt = f"""你是独立的 Agent 离线评测员。请严格输出 JSON，只根据题目、金标和编号证据评分。
不得用你自己的知识补充证据。correctness 衡量是否完成题目并与金标一致；
faithfulness 衡量所有需外部证据的事实是否能由编号证据支持。纯直接回答若无需
外部证据，faithfulness 记 1。claims 中的 evidence_ids 只能填写给出的编号。

题目：{case.question}
标准答案：{case.reference_answer}
必须覆盖的答案标签：{json.dumps(case.answer.model_dump(mode="json"), ensure_ascii=False)}
候选答案：{result.answer}
工具证据：{evidence or "（无外部证据）"}
"""
        try:
            envelope = await self._model.with_structured_output(
                JudgePayload, method="json_mode", include_raw=True
            ).ainvoke(
                [("system", "严格、可复核地评测中文 Agent 输出。"), ("user", prompt)]
            )
            parsed = envelope.get("parsed")
            if parsed is None:
                raise RuntimeError(
                    str(envelope.get("parsing_error") or "judge parse failed")
                )
            raw = envelope.get("raw")
            input_tokens, output_tokens, total_tokens, usage_available = _usage(raw)
            invalid_ids = {
                evidence_id
                for claim in parsed.claims
                for evidence_id in claim.evidence_ids
                if evidence_id not in valid_ids
            }
            faithfulness = parsed.faithfulness
            rationale = parsed.rationale
            if invalid_ids:
                faithfulness = 0.0
                rationale += f"；评审引用了不存在的证据编号：{sorted(invalid_ids)}"
            return JudgeResult(
                **parsed.model_dump(exclude={"faithfulness", "rationale"}),
                faithfulness=faithfulness,
                rationale=rationale,
                judge_model=self.model_name,
                latency_ms=round((perf_counter() - started) * 1000, 3),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                usage_available=usage_available,
            )
        except Exception as exc:
            return JudgeResult(
                answer_correctness=0,
                faithfulness=0,
                task_completed=False,
                rationale="评审模型调用失败，汇总时回退到确定性评分。",
                judge_model=self.model_name,
                latency_ms=round((perf_counter() - started) * 1000, 3),
                error=str(exc),
            )


__all__ = ["AnswerJudge", "OpenAICompatibleJudge"]
