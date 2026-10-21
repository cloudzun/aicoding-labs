"""magpie 调用（与 ② 同构）：非流式 chat + 严格错误映射。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def _env() -> dict[str, str]:
    cfg: dict[str, str] = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


CFG = {**_env(), **os.environ}
BASE = CFG.get("MAGPIE_BASE", "http://127.0.0.1:3425").rstrip("/")
KEY = CFG.get("MAGPIE_KEY", "magpie")
MODEL_MAIN = CFG.get("MODEL_MAIN", "opencode-go/gpt-6-luna")
MODEL_SEMANTIC = CFG.get("MODEL_SEMANTIC", "opencode-go/deepseek-v4.1-flash")


class LLMError(RuntimeError):
    pass


def chat(messages: list[dict], model: str | None = None, effort: str = "none",
         max_tokens: int = 1500, timeout_s: float = 60) -> dict:
    payload = {"model": model or MODEL_MAIN, "messages": messages,
               "max_tokens": max_tokens, "reasoning_effort": effort, "stream": False}
    try:
        r = httpx.post(f"{BASE}/v1/chat/completions", json=payload,
                       headers={"Authorization": f"Bearer {KEY}"}, timeout=timeout_s)
        r.raise_for_status()
        try:
            j = r.json()
            return {"content": ((j.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip(),
                    "usage": j.get("usage") or {}, "model": payload["model"]}
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"响应不可解析：{type(exc).__name__}") from exc
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc


def chat_json(messages: list[dict], model: str | None = None, effort: str = "none",
              max_tokens: int = 1500, timeout_s: float = 60) -> dict:
    """要求模型返回 JSON；失败按 BP-1 做一次"更严格"重试。"""
    for attempt in range(2):
        out = chat(messages, model=model, effort=effort, max_tokens=max_tokens, timeout_s=timeout_s)
        raw = out["content"]
        s, e = raw.find("{"), raw.rfind("}")
        if s >= 0 and e > s:
            try:
                return json.loads(raw[s : e + 1])
            except json.JSONDecodeError:
                pass
        arr_s, arr_e = raw.find("["), raw.rfind("]")
        if arr_s >= 0 and arr_e > arr_s:
            try:
                return {"items": json.loads(raw[arr_s : arr_e + 1])}
            except json.JSONDecodeError:
                pass
        if attempt == 0:
            messages = messages + [{"role": "user", "content": "只输出 JSON，不要任何解释文字。"}]
    raise LLMError("模型未返回可解析 JSON")
