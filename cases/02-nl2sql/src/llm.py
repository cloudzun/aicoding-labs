"""模型调用（magpie 网关）。

只保留 NL2SQL 需要的两个原语：非流式 chat 与流式 chat。
超时与错误处理是硬要求：失败必须显式抛出，不能返回空字符串冒充答案。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> dict[str, str]:
    cfg: dict[str, str] = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


CFG = {**_load_env(), **os.environ}
# ---- 供应商：siliconflow（公网，默认）| magpie（内网可选）----
PROVIDER = str(CFG.get("LLM_PROVIDER", "siliconflow")).strip().lower()
_SF_BASE = str(CFG.get("SILICONFLOW_BASE", "https://api.siliconflow.cn/v1")).rstrip("/")
_SF_KEY = str(CFG.get("SILICONFLOW_KEY", ""))
_MAGPIE_BASE = str(CFG.get("MAGPIE_BASE", "http://127.0.0.1:3425")).rstrip("/")
_MAGPIE_KEY = str(CFG.get("MAGPIE_KEY", "magpie"))
_BASE = str(CFG.get("LLM_BASE", _MAGPIE_BASE if PROVIDER == "magpie" else _SF_BASE)).rstrip("/")
BASE = _BASE if _BASE.endswith("/v1") else _BASE + "/v1"
KEY = str(CFG.get("LLM_KEY", _MAGPIE_KEY if PROVIDER == "magpie" else _SF_KEY))
MODEL_MAIN = str(
    CFG.get("MODEL_MAIN", "opencode-go/gpt-6-luna" if PROVIDER == "magpie" else "Qwen/Qwen2.5-72B-Instruct")
)
GEN_TIMEOUT = float(CFG.get("GEN_TIMEOUT_S", "30"))


def chat_extra(effort: str = "none") -> dict:
    """magpie 专有的 reasoning_effort 只在 magpie 档发送；公网 API 可能拒绝未知字段。"""
    return {"reasoning_effort": effort} if PROVIDER == "magpie" else {}


class LLMError(RuntimeError):
    pass


def chat(messages: list[dict], model: str | None = None, effort: str = "none", max_tokens: int = 1200, timeout_s: float | None = None) -> dict:
    payload = {
        "model": model or MODEL_MAIN,
        "messages": messages,
        "max_tokens": max_tokens,
        **chat_extra(effort),
        "stream": False,
    }
    try:
        r = httpx.post(
            f"{BASE}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {KEY}"},
            timeout=timeout_s or GEN_TIMEOUT,
        )
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc
    try:
        j = r.json()
        msg = (j.get("choices") or [{}])[0].get("message") or {}
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"模型响应不可解析：{type(exc).__name__}") from exc
    return {
        "content": (msg.get("content") or "").strip(),
        "usage": j.get("usage") or {},
        "model": model or MODEL_MAIN,
    }


def extract_sql(text: str) -> str | None:
    """从模型输出中提取一条 SQL（优先 ```sql 代码块，其次首条 SELECT）。"""
    t = text.strip()
    if "```" in t:
        parts = t.split("```")
        for i in range(1, len(parts), 2):
            block = parts[i]
            block = block.split("\n", 1)[1] if "\n" in block else block
            if "select" in block.lower():
                return block.strip().rstrip(";").strip()
    low = t.lower()
    idx = low.find("select")
    if idx < 0:
        return None
    sql = t[idx:]
    # 截到第一个分号（多语句只取第一条，是否放行由安全闸决定）
    semi = sql.find(";")
    if semi >= 0:
        sql = sql[:semi]
    return " ".join(sql.split()).strip() or None
