"""C 段：嵌入 / 重排模型 A/B（用 20 条人工无偏问题，按"期望文档是否进 top5"评）。

不改主索引：全部在内存里算，跑完自动还原服务端不受影响。
用法：python -m scripts.bench_embeddings
输出：evidence/bench-embeddings.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core import EVIDENCE, SF_BASE, SF_KEY  # noqa: E402
from src.vector import Embedder, load_index, tokenize  # noqa: E402
from src.core import read_jsonl  # noqa: E402

HUMAN = ROOT / "eval" / "human_questions.jsonl"

EMBED_CASES = [
    ("Qwen3-Embedding-4B(magpie)", "siliconflow/Qwen/Qwen3-Embedding-4B", "http://127.0.0.1:3425/v1", "magpie"),
    ("Qwen3-Embedding-8B(magpie)", "siliconflow/Qwen/Qwen3-Embedding-8B", "http://127.0.0.1:3425/v1", "magpie"),
    ("bge-m3(硅基流动直连)", "BAAI/bge-m3", SF_BASE, SF_KEY),
]

RERANK_CASES = [
    ("Qwen3-Reranker-4B", "siliconflow/Qwen/Qwen3-Reranker-4B", "http://127.0.0.1:3425/v1", "magpie"),
    ("Qwen3-Reranker-8B", "siliconflow/Qwen/Qwen3-Reranker-8B", "http://127.0.0.1:3425/v1", "magpie"),
    ("bge-reranker-v2-m3", "BAAI/bge-reranker-v2-m3", SF_BASE, SF_KEY),
]


def main() -> int:
    index = load_index()
    chunks = index.chunks
    texts = [c["text"] for c in chunks]
    qa = read_jsonl(HUMAN)
    record: dict = {"ran_at": datetime.now().astimezone().isoformat(timespec="seconds"), "n_questions": len(qa), "embed": {}, "rerank": {}}

    # ---- 嵌入 A/B：dense top5 的 doc 召回 ----
    qsets = {}
    for label, model, base, key in EMBED_CASES:
        emb = Embedder(model=model, base=base, key=key)
        try:
            mat = emb.embed(texts)
            mat = mat / np.maximum(np.linalg.norm(mat, axis=1, keepdims=True), 1e-9)
            qmat = emb.embed([r["question"] for r in qa])
            qmat = qmat / np.maximum(np.linalg.norm(qmat, axis=1, keepdims=True), 1e-9)
        except Exception as exc:  # noqa: BLE001
            record["embed"][label] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"{label}: ERROR {exc}")
            continue
        hits = 0
        clause_hits = 0
        for i, row in enumerate(qa):
            scores = mat @ qmat[i]
            top = np.argsort(-scores)[:5]
            docs = [chunks[j]["doc_id"] for j in top]
            clauses = [chunks[j]["clause_no"] for j in top]
            if any(d in docs for d in row["gold_docs"]):
                hits += 1
            if row.get("gold_clauses") and any(c in clauses for c in row["gold_clauses"]):
                clause_hits += 1
        record["embed"][label] = {
            "dim": int(mat.shape[1]),
            "doc_recall_at_5": round(hits / len(qa), 4),
            "clause_hit_at_5": round(clause_hits / max(1, sum(1 for r in qa if r.get("gold_clauses"))), 4),
        }
        qsets[label] = qmat
        print(f"{label:32s} dim={mat.shape[1]:5d} doc_recall@5={record['embed'][label]['doc_recall_at_5']:.2%}")

    # ---- 重排 A/B：固定候选（Qwen3-4B dense top20 + BM25 前 20 并集）----
    base_label = EMBED_CASES[0][0]
    if base_label in qsets:
        import httpx

        cand_index: dict[int, list[int]] = {}
        qmat = qsets[base_label]
        for i, row in enumerate(qa):
            scores = index.emb @ qmat[i] if index.emb.shape[1] == qmat.shape[1] else None
            dense = list(np.argsort(-(index.emb @ qmat[i]))[:20]) if scores is not None else []
            bm = [j for j, _ in index.sparse(row["question"], k=20)]
            cand_index[i] = sorted(set(dense) | set(bm))

        for label, model, base, key in RERANK_CASES:
            hits = 0
            err = None
            for i, row in enumerate(qa):
                idxs = cand_index[i]
                if not idxs:
                    continue
                docs = [chunks[j]["text"][:1200] for j in idxs]
                try:
                    r = httpx.post(
                        f"{base.rstrip('/')}/rerank",
                        json={"model": model, "query": row["question"], "documents": docs, "top_n": 5},
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=60,
                    )
                    r.raise_for_status()
                    top = [idxs[x["index"]] for x in r.json()["results"][:5]]
                    if any(chunks[j]["doc_id"] in row["gold_docs"] for j in top):
                        hits += 1
                except Exception as exc:  # noqa: BLE001
                    err = f"{type(exc).__name__}: {exc}"
                    break
            record["rerank"][label] = {
                "doc_recall_at_5": None if err else round(hits / len(qa), 4),
                "error": err,
            }
            print(f"{label:32s} doc_recall@5={'ERROR' if err else record['rerank'][label]['doc_recall_at_5']}")

    EVIDENCE.mkdir(exist_ok=True)
    out = EVIDENCE / f"bench-embeddings-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[evidence] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
