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


MAGPIE_BASE = cfg("MAGPIE_BASE", "http://127.0.0.1:3425").rstrip("/")
MAGPIE_KEY = cfg("MAGPIE_KEY", "magpie")
SF_BASE = cfg("SILICONFLOW_BASE", "https://api.siliconflow.cn/v1").rstrip("/")
SF_KEY = cfg("SILICONFLOW_KEY", "")
MODEL_MAIN = cfg("MODEL_MAIN", "opencode-go/gpt-6-luna")
MODEL_JUDGE = cfg("MODEL_REASONER", "opencode-go/deepseek-v4.1-flash")
EMBED_MODEL = cfg("EMBED_MODEL", "BAAI/bge-m3")
RERANK_MODEL = cfg("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
TOP_K = int(cfg("TOP_K", "5"))

# 嵌入/重排端点可独立配置：默认沿用硅基流动直连；
# 若模型改为 magpie 上的 siliconflow/*，把 EMBED_BASE/RERANK_BASE 指向 magpie 即可统一入口。
EMBED_BASE = cfg("EMBED_BASE", SF_BASE).rstrip("/")
EMBED_KEY = cfg("EMBED_KEY", SF_KEY)
RERANK_BASE = cfg("RERANK_BASE", SF_BASE).rstrip("/")
RERANK_KEY = cfg("RERANK_KEY", SF_KEY)

DENSE_TOP_N = 30
SPARSE_TOP_N = 30
RERANK_TOP_N = 20
RRF_K = 60
MIN_RERANK_SCORE = 0.30
GEN_TIMEOUT_S = 15.0
CHUNKER_VERSION = "1.0"
PORT = int(cfg("PORT", "4180"))


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
