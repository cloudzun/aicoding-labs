"""公共配置与工具。

设计原则：所有路径、密钥、模型名都从 .env 读取，代码里不出现硬编码密钥。
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CORPUS = DATA / "corpus"
INDEX = DATA / "index"
CACHE = DATA / "cache"
TRACES = DATA / "traces"
WEB = ROOT / "web"
REPORTS = ROOT / "eval" / "reports"
EVIDENCE = ROOT / "evidence"


def _load_env() -> dict[str, str]:
    cfg: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


CFG: dict[str, str] = {**_load_env(), **os.environ}


def cfg(key: str, default: str = "") -> str:
    return CFG.get(key, default)


# ---- 供应商：siliconflow（公网，默认）| magpie（内网可选）----
PROVIDER = cfg("LLM_PROVIDER", "siliconflow").strip().lower()
MAGPIE_BASE = cfg("MAGPIE_BASE", "http://127.0.0.1:3425").rstrip("/")
MAGPIE_KEY = cfg("MAGPIE_KEY", "magpie")
SF_BASE = cfg("SILICONFLOW_BASE", "https://api.siliconflow.cn/v1").rstrip("/")
SF_KEY = cfg("SILICONFLOW_KEY", "")
CHAT_BASE = cfg("LLM_BASE", MAGPIE_BASE if PROVIDER == "magpie" else SF_BASE).rstrip("/")
CHAT_KEY = cfg("LLM_KEY", MAGPIE_KEY if PROVIDER == "magpie" else SF_KEY)


def _with_v1(base: str) -> str:
    """统一把 base 规范成 .../v1（chat / embeddings / rerank 都在其下）。"""
    base = (base or "").rstrip("/")
    return base if base.endswith("/v1") else base + "/v1"


CHAT_BASE = _with_v1(CHAT_BASE)

# 各供应商的默认模型：只切供应商、不改 .env 时，至少落到该供应商真实存在的模型上。
_DEFAULT_MODELS = {
    "siliconflow": {
        "main": "Qwen/Qwen2.5-72B-Instruct",
        "judge": "deepseek-ai/DeepSeek-V3",
        "embed": "Qwen/Qwen3-Embedding-4B",
        "rerank": "Qwen/Qwen3-Reranker-4B",
    },
    "magpie": {
        "main": "opencode-go/gpt-6-luna",
        "judge": "opencode-go/deepseek-v4.1-flash",
        "embed": "siliconflow/Qwen/Qwen3-Embedding-4B",
        "rerank": "siliconflow/Qwen/Qwen3-Reranker-4B",
    },
}
_D = _DEFAULT_MODELS.get(PROVIDER, _DEFAULT_MODELS["siliconflow"])
MODEL_MAIN = cfg("MODEL_MAIN", _D["main"])
MODEL_JUDGE = cfg("MODEL_REASONER", _D["judge"])
EMBED_MODEL = cfg("EMBED_MODEL", _D["embed"])
RERANK_MODEL = cfg("RERANK_MODEL", _D["rerank"])
TOP_K = int(cfg("TOP_K", "5"))

# 嵌入/重排端点可独立配置：默认沿用所选供应商；
# magpie 档下统一指向网关 /v1（模型名带 siliconflow/ 前缀）。
_EMBED_DEFAULT = MAGPIE_BASE if PROVIDER == "magpie" else SF_BASE
_EMBED_KEY_DEFAULT = MAGPIE_KEY if PROVIDER == "magpie" else SF_KEY
EMBED_BASE = _with_v1(cfg("EMBED_BASE", _EMBED_DEFAULT))
EMBED_KEY = cfg("EMBED_KEY", _EMBED_KEY_DEFAULT)
RERANK_BASE = _with_v1(cfg("RERANK_BASE", _EMBED_DEFAULT))
RERANK_KEY = cfg("RERANK_KEY", _EMBED_KEY_DEFAULT)

DENSE_TOP_N = 30
SPARSE_TOP_N = 30
RERANK_TOP_N = 20
RRF_K = 60
# 重排分数阈值：换重排模型/供应商后分布会变，用 .env 覆盖并重新校准（见 docs/11-操作手册.md）。
MIN_RERANK_SCORE = float(cfg("MIN_RERANK_SCORE", "0.30"))
GEN_TIMEOUT_S = 15.0
CHUNKER_VERSION = "1.0"
PORT = int(cfg("PORT", "4180"))


def chat_extra(effort: str = "none") -> dict:
    """magpie 专有的 reasoning_effort 只在 magpie 档发送。

    公网 OpenAI 兼容 API 对未知字段可能直接 400，因此非 magpie 档不发送该参数。
    """
    return {"reasoning_effort": effort} if PROVIDER == "magpie" else {}


def ensure_dirs() -> None:
    for p in (INDEX, CACHE, TRACES, REPORTS, EVIDENCE):
        p.mkdir(parents=True, exist_ok=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
