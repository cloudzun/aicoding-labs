"""模型调用：生成（magpie，流式/非流式）与评测判定（judge）。

设计要点：
- 生成默认 reasoning_effort=none（实测 glm/deepseek 保留思维链会把 max_tokens 吃光）。
- 流式解析 SSE；超时熔断后返回已生成部分并标记 timed_out（SPEC v1.1 / OB-01）。
- judge 固定用另一模型（默认 deepseek），避免与被测模型同族自评（D-10）。
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator

import httpx

from .core import (
    GEN_TIMEOUT_S,
    MAGPIE_BASE,
    MAGPIE_KEY,
    MODEL_JUDGE,
    MODEL_MAIN,
)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {MAGPIE_KEY}", "Content-Type": "application/json"}


def stream_chat(
    messages: list[dict],
    model: str = MODEL_MAIN,
    effort: str = "none",
    max_tokens: int = 1200,
    timeout_s: float = GEN_TIMEOUT_S,
) -> Iterator[dict]:
    """产出 {"type":"delta","text":...} / {"type":"done",...} / {"type":"error",...}"""
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "reasoning_effort": effort,
        "stream": True,
    }
    t0 = time.perf_counter()
    ttft: float | None = None
    answer: list[str] = []
    usage: dict = {}
    timed_out = False
    try:
        with httpx.stream(
            "POST",
            f"{MAGPIE_BASE}/v1/chat/completions",
            json=payload,
            headers=_headers(),
            timeout=timeout_s,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if obj.get("usage"):
                    usage = obj["usage"]
                for choice in obj.get("choices", []):
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        if ttft is None:
                            ttft = time.perf_counter() - t0
                        answer.append(piece)
                        yield {"type": "delta", "text": piece}
    except httpx.ReadTimeout:
        timed_out = True
    except Exception as exc:  # noqa: BLE001
        yield {"type": "error", "error": f"{type(exc).__name__}: {exc}"}
        return

    total = time.perf_counter() - t0
    yield {
        "type": "done",
        "answer": "".join(answer),
        "elapsed_ms": int(total * 1000),
        "ttft_ms": int(ttft * 1000) if ttft is not None else None,
        "timed_out": timed_out,
        "partial": timed_out,
        "model": model,
        "reasoning_effort": effort,
        "usage": usage,
    }


def chat(
    messages: list[dict],
    model: str = MODEL_MAIN,
    effort: str = "none",
    max_tokens: int = 1200,
    timeout_s: float = 90.0,
) -> dict:
    """非流式调用，供评测与 judge 使用。"""
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "reasoning_effort": effort,
        "stream": False,
    }
    t0 = time.perf_counter()
    r = httpx.post(
        f"{MAGPIE_BASE}/v1/chat/completions", json=payload, headers=_headers(), timeout=timeout_s
    )
    dt = time.perf_counter() - t0
    r.raise_for_status()
    j = r.json()
    msg = (j.get("choices") or [{}])[0].get("message") or {}
    return {
        "content": (msg.get("content") or "").strip(),
        "elapsed_ms": int(dt * 1000),
        "usage": j.get("usage") or {},
        "model": model,
    }


JUDGE_SYSTEM = (
    "你是严格的评测员。只依据给定材料与标准答案做判定，不臆测。"
    "必须输出 JSON，且只输出 JSON（不要解释、不要 markdown 代码块）。字段必须齐全："
    "verdict(只能是 correct|partial|wrong|refused|unsupported 之一)、"
    "covered_facts(字符串数组：答案命中标准答案中的哪些事实点)、"
    "missing_facts(字符串数组：标准答案中未被答案覆盖的事实点)、"
    "hallucinations(字符串数组：材料无法支持的断言原文片段，没有则空数组)、"
    "reason(一句话中文依据)。"
)


def judge(question: str, gold_answer: str, material: str, candidate: str) -> dict:
    """用独立模型判定答案正确性与忠实性。返回结构化结果，异常时返回 {"verdict":"error"}。"""
    user = (
        f"【问题】\n{question}\n\n"
        f"【标准答案】\n{gold_answer}\n\n"
        f"【检索材料】\n{material[:6000]}\n\n"
        f"【待判定答案】\n{candidate[:2000]}\n\n"
        "请判定：1) 是否覆盖标准答案的事实点；2) 是否存在材料不支持的断言。"
    )
    # F13/R-28：judge 失败重试。deepseek 在 effort=low 下偶发输出非 JSON 或超时，
    # 直接算作 error 会让正确率分母虚高、结论失真，因此重试并逐步提高 effort。
    last_err = ""
    for attempt, effort in enumerate(("low", "low", "high")):
        try:
            out = chat(
                [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}],
                model=MODEL_JUDGE,
                effort=effort,
                max_tokens=2500,  # 根因修复：800 会被思维链吃光导致 JSON 截断
                timeout_s=90,
            )
            break
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt == 2:
                return {"verdict": "error", "error": last_err, "_judge_model": MODEL_JUDGE}
    try:
        text = out["content"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        data = json.loads(text)
        if data.get("verdict") not in ("correct", "partial", "wrong", "unsupported"):
            raise ValueError(f"judge 返回非法 verdict: {data.get('verdict')}")
        data["_judge_model"] = MODEL_JUDGE
        return data
    except Exception as exc:  # noqa: BLE001
        # 解析失败也算 error，由评测侧排除出分母并单列（F13）
        return {"verdict": "error", "error": f"parse: {type(exc).__name__}: {exc}", "_judge_model": MODEL_JUDGE}
