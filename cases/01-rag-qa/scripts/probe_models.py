"""能力与延迟探测（可复现证据生成器）。

用途：每次模型/接口变更后重跑，产出一份带时间戳的 JSON 证据，作为 SPEC 与验收报告的依据。
运行：python scripts/probe_models.py
输出：evidence/probe-<timestamp>.json + 控制台摘要
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"


def load_env(path: Path) -> dict[str, str]:
    cfg: dict[str, str] = {}
    if not path.exists():
        return cfg
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip()
    return cfg


CFG = {**load_env(ROOT / ".env"), **os.environ}
MAGPIE = CFG.get("MAGPIE_BASE", "http://127.0.0.1:3425").rstrip("/")
SF = CFG.get("SILICONFLOW_BASE", "https://api.siliconflow.cn/v1").rstrip("/")
MAGPIE_KEY = CFG.get("MAGPIE_KEY", "magpie")
SF_KEY = CFG.get("SILICONFLOW_KEY", "")
EMBED_MODEL = CFG.get("EMBED_MODEL", "BAAI/bge-m3")
RERANK_MODEL = CFG.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

CTX = (
    "《明州数智服务有限公司采购管理办法》第十二条：单项合同金额超过500万元的，须提交总经理办公会审议。"
    "第十三条：采购合同应在中标通知书发出后30日内签订。"
)
QUESTION = "根据材料回答：500万元以上合同需要哪个层级审议？并注明依据条款。"
MESSAGES = [
    {"role": "system", "content": "只根据给定材料回答，无法回答时明确说「材料不足」。答案末尾用[条款号]标注依据。"},
    {"role": "user", "content": f"{CTX}\n\n问题：{QUESTION}"},
]

CHUNKS = [
    f"第{i}条：采购合同金额超过500万元的，须提交总经理办公会审议，并由采购部门在30日内完成签订。"
    + "制度条款示例内容" * 12
    for i in range(1, 11)
]

# (标签, 模型, reasoning_effort)。none 是唯一能关掉思维链的档位（只有 5 个模型支持）。
CHAT_CASES = [
    ("main", CFG.get("MODEL_MAIN", "opencode-go/gpt-6-luna"), "none"),
    ("alt", CFG.get("MODEL_ALT", "opencode-go/glm-5.3"), "low"),
    ("reasoner", CFG.get("MODEL_REASONER", "opencode-go/deepseek-v4.1-flash"), "low"),
]
RUNS = 5
# 单次调用超时。实测 glm-5.3 曾整组挂起到 180s，超时必须比预期慢很多，
# 但失败要单独记录而不是中断整组（见 main 里的 continue）。
CHAT_TIMEOUT = float(CFG.get("CHAT_TIMEOUT_S", "90"))


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def probe_models(client: httpx.Client) -> list[dict]:
    r = client.get(f"{MAGPIE}/v1/models")
    r.raise_for_status()
    out = []
    for m in r.json().get("data", []):
        out.append(
            {
                "id": m.get("id"),
                "owner": m.get("owned_by"),
                "context_length": m.get("context_length"),
                "input_modalities": (m.get("modalities") or {}).get("input"),
                "reasoning": m.get("reasoning"),
                "reasoning_levels": m.get("reasoning_levels"),
            }
        )
    return out


def probe_chat(client: httpx.Client, model: str, effort: str) -> dict:
    body = {
        "model": model,
        "messages": MESSAGES,
        "max_tokens": 1500,
        "reasoning_effort": effort,
        "stream": False,
    }
    t0 = time.perf_counter()
    r = client.post(f"{MAGPIE}/v1/chat/completions", json=body, timeout=CHAT_TIMEOUT)
    dt = time.perf_counter() - t0
    r.raise_for_status()
    j = r.json()
    msg = (j.get("choices") or [{}])[0].get("message", {}) or {}
    usage = j.get("usage") or {}
    return {
        "elapsed_s": round(dt, 4),
        "answer": (msg.get("content") or "").strip(),
        "answer_chars": len((msg.get("content") or "").strip()),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        "prompt_tokens": usage.get("prompt_tokens"),
    }


def probe_embed(client: httpx.Client, texts: list[str]) -> dict:
    body = {"model": EMBED_MODEL, "input": texts}
    t0 = time.perf_counter()
    r = client.post(
        f"{SF}/embeddings",
        json=body,
        headers={"Authorization": f"Bearer {SF_KEY}"},
        timeout=120,
    )
    dt = time.perf_counter() - t0
    r.raise_for_status()
    j = r.json()
    return {
        "elapsed_s": round(dt, 4),
        "count": len(j.get("data", [])),
        "dim": len((j.get("data") or [{}])[0].get("embedding") or []),
        "tokens": (j.get("usage") or {}).get("total_tokens"),
        "model": j.get("model"),
    }


def probe_rerank(client: httpx.Client, query: str, docs: list[str]) -> dict:
    body = {"model": RERANK_MODEL, "query": query, "documents": docs, "top_n": 5}
    t0 = time.perf_counter()
    r = client.post(
        f"{SF}/rerank",
        json=body,
        headers={"Authorization": f"Bearer {SF_KEY}"},
        timeout=120,
    )
    dt = time.perf_counter() - t0
    r.raise_for_status()
    j = r.json()
    results = j.get("results") or []
    return {
        "elapsed_s": round(dt, 4),
        "top1_index": results[0].get("index") if results else None,
        "top1_score": round(results[0].get("relevance_score", 0), 6) if results else None,
        "tokens": ((j.get("meta") or {}).get("tokens") or {}).get("input_tokens"),
        "model": j.get("id"),
    }


def main() -> int:
    stamp = datetime.now(timezone.utc).astimezone()
    record: dict = {
        "captured_at": stamp.isoformat(timespec="seconds"),
        "host": sys.platform,
        "python": sys.version.split()[0],
        "magpie_base": MAGPIE,
        "siliconflow_base": SF,
        "models": {},
        "chat": {},
        "embed": {},
        "rerank": {},
        "errors": [],
    }

    with httpx.Client() as client:
        try:
            models = probe_models(client)
            record["models"]["list"] = models
            record["models"]["none_level"] = [
                m["id"] for m in models if "none" in (m.get("reasoning_levels") or [])
            ]
        except Exception as exc:  # noqa: BLE001
            record["errors"].append(f"models: {exc}")

        for label, model, effort in CHAT_CASES:
            runs = []
            ok = 0
            for i in range(RUNS):
                try:
                    runs.append(probe_chat(client, model, effort))
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    record["errors"].append(f"chat {label} run{i + 1}: {exc}")
                    continue
            lat = [x["elapsed_s"] for x in runs]
            record["chat"][label] = {
                "model": model,
                "reasoning_effort": effort,
                "runs_requested": RUNS,
                "runs_ok": ok,
                "success_rate": round(ok / RUNS, 3),
                "runs": runs,
                "p50_s": round(statistics.median(lat), 4) if lat else None,
                "min_s": round(min(lat), 4) if lat else None,
                "max_s": round(max(lat), 4) if lat else None,
                "p95_s": round(_pct(lat, 0.95), 4) if lat else None,
            }

        if SF_KEY:
            try:
                record["embed"] = probe_embed(client, CHUNKS)
            except Exception as exc:  # noqa: BLE001
                record["errors"].append(f"embed: {exc}")
            try:
                record["rerank"] = probe_rerank(client, "500万元以上合同谁审议", CHUNKS)
            except Exception as exc:  # noqa: BLE001
                record["errors"].append(f"rerank: {exc}")
        else:
            record["errors"].append("embed/rerank skipped: SILICONFLOW_KEY 未配置")

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / f"probe-{stamp.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[evidence] {out}")
    print("\n== chat latency (n=%d) ==" % RUNS)
    for label, data in record["chat"].items():
        print(
            f"  {label:10s} {data['model']:34s} effort={data['reasoning_effort']:5s} "
            f"p50={data['p50_s']}s max={data['max_s']}s"
        )
        if data["runs"]:
            r0 = data["runs"][0]
            print(f"             answer={r0['answer_chars']}字 reasoning_tokens={r0['reasoning_tokens']}")
            print(f"             Q: {r0['answer'][:100]}")
    if record["embed"]:
        e = record["embed"]
        print(f"\n== embed: {e['count']} chunks in {e['elapsed_s']}s, dim={e['dim']}, tokens={e['tokens']}")
    if record["rerank"]:
        r = record["rerank"]
        print(f"== rerank: top1_index={r['top1_index']} score={r['top1_score']} in {r['elapsed_s']}s")
    if record["errors"]:
        print("\n== errors ==")
        for e in record["errors"]:
            print("  -", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
