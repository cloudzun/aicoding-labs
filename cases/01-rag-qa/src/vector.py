"""向量化与混合检索。

替换点：若要换 pgvector / FAISS / Qdrant，只需重写 Index.dense 与 Index.load/save，
其余（RRF 融合、重排、检索日志）不受影响。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import jieba
import numpy as np
from rank_bm25 import BM25Okapi

from .core import (
    CACHE,
    DENSE_TOP_N,
    EMBED_BASE,
    EMBED_KEY,
    EMBED_MODEL,
    INDEX,
    RERANK_BASE,
    RERANK_KEY,
    RERANK_MODEL,
    RERANK_TOP_N,
    RRF_K,
    SPARSE_TOP_N,
    read_jsonl,
    sha1_text,
    write_jsonl,
)

EMBED_BATCH = 32
CACHE_FILE = CACHE / "embeddings.jsonl"


class EmbeddingError(RuntimeError):
    pass


class Embedder:
    def __init__(self, model: str = EMBED_MODEL, base: str = EMBED_BASE, key: str = EMBED_KEY):
        if not key:
            raise EmbeddingError("SILICONFLOW_KEY 未配置，无法调用嵌入接口")
        self.model = model
        self.base = base.rstrip("/")
        self.key = key
        self.cache: dict[str, list[float]] = {}
        if CACHE_FILE.exists():
            for row in read_jsonl(CACHE_FILE):
                self.cache[row["k"]] = row["v"]
        self._new_rows: list[dict] = []

    def _key(self, text: str) -> str:
        return sha1_text(self.model + "\x00" + text)

    def embed(self, texts: list[str], progress: bool = False) -> np.ndarray:
        vecs: list[np.ndarray | None] = [None] * len(texts)
        todo: list[tuple[int, str]] = []
        for i, t in enumerate(texts):
            k = self._key(t)
            if k in self.cache:
                vecs[i] = np.asarray(self.cache[k], dtype=np.float32)
            else:
                todo.append((i, t))

        total_batches = (len(todo) + EMBED_BATCH - 1) // EMBED_BATCH
        for bi in range(total_batches):
            batch = todo[bi * EMBED_BATCH : (bi + 1) * EMBED_BATCH]
            payload = {"model": self.model, "input": [t for _, t in batch]}
            last_err = ""
            for attempt in range(3):
                try:
                    r = httpx.post(
                        f"{self.base}/embeddings",
                        json=payload,
                        headers={"Authorization": f"Bearer {self.key}"},
                        timeout=120,
                    )
                    r.raise_for_status()
                    data = r.json()["data"]
                    # F10：数量不符必须报错，zip 会静默截断导致向量错位
                    if len(data) != len(batch):
                        raise EmbeddingError(f"嵌入返回数量不符：请求 {len(batch)}，返回 {len(data)}")
                    for (idx, text), item in zip(batch, data):
                        vecs[idx] = np.asarray(item["embedding"], dtype=np.float32)
                        k = self._key(text)
                        self.cache[k] = item["embedding"]
                        self._new_rows.append({"k": k, "v": item["embedding"]})
                    break
                except Exception as exc:  # noqa: BLE001
                    last_err = f"{type(exc).__name__}: {exc}"
                    if attempt < 2:
                        time.sleep(1.5 * (attempt + 1))
            else:
                done = bi * EMBED_BATCH
                raise EmbeddingError(
                    f"嵌入失败（已完成 {done}/{len(todo)} 条，批次 {bi + 1}/{total_batches}）：{last_err}"
                )
            if progress:
                print(f"  embed batch {bi + 1}/{total_batches}")

        missing = sum(1 for v in vecs if v is None)
        if missing:
            raise EmbeddingError(f"嵌入缺失 {missing} 条（共 {len(vecs)}），拒绝继续以免向量错位")
        self._flush_cache()
        return np.vstack(vecs)

    def _flush_cache(self) -> None:
        if not self._new_rows:
            return
        CACHE.mkdir(parents=True, exist_ok=True)
        with CACHE_FILE.open("a", encoding="utf-8", newline="\n") as fh:
            for row in self._new_rows:
                fh.write(json.dumps(row) + "\n")
        self._new_rows = []


def tokenize(text: str) -> list[str]:
    return [w for w in jieba.lcut(text) if w.strip()]


def _normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


class Index:
    def __init__(self, chunks: list[dict], emb: np.ndarray, model: str):
        self.chunks = chunks
        self.emb = _normalize(emb.astype(np.float32))
        self.model = model
        self.tokens = [tokenize(c["text"]) for c in chunks]
        self.bm25 = BM25Okapi(self.tokens) if self.tokens else None

    # ---- 构建与持久化 ----
    @classmethod
    def build(cls, chunks: list[dict], embedder: Embedder | None = None) -> "Index":
        emb = (embedder or Embedder()).embed([c["text"] for c in chunks], progress=True)
        idx = cls(chunks, emb, (embedder or Embedder()).model)
        idx.save()
        return idx

    def save(self) -> None:
        INDEX.mkdir(parents=True, exist_ok=True)
        np.save(INDEX / "emb.npy", self.emb)
        write_jsonl(INDEX / "chunks.jsonl", self.chunks)

    @classmethod
    def load(cls) -> "Index":
        chunks_path = INDEX / "chunks.jsonl"
        emb_path = INDEX / "emb.npy"
        if not chunks_path.exists() or not emb_path.exists():
            raise FileNotFoundError("索引不存在，请先运行 `python -m src.ingest`")
        chunks = read_jsonl(chunks_path)
        emb = np.load(emb_path)
        # F10：行数不一致说明索引损坏，宁可启动失败也不要检索错位
        if emb.shape[0] != len(chunks):
            raise RuntimeError(
                f"索引损坏：chunks={len(chunks)} 与 embedding 行数={emb.shape[0]} 不一致，请重新建库"
            )
        return cls(chunks, emb, EMBED_MODEL)

    # ---- 检索 ----
    def dense(self, qvec: np.ndarray, k: int = DENSE_TOP_N) -> list[tuple[int, float]]:
        q = qvec.astype(np.float32)
        q = q / (np.linalg.norm(q) or 1.0)
        scores = self.emb @ q
        top = np.argsort(-scores)[:k]
        return [(int(i), float(scores[i])) for i in top]

    def sparse(self, query: str, k: int = SPARSE_TOP_N) -> list[tuple[int, float]]:
        if self.bm25 is None:
            return []
        q_tokens = tokenize(query)
        if not q_tokens:  # F15：空 token 会让 BM25 返回全零分数，进而注入任意 chunk
            return []
        scores = self.bm25.get_scores(q_tokens)
        top = np.argsort(-scores)[:k]
        return [(int(i), float(scores[i])) for i in top]

    @staticmethod
    def rrf(a: list[tuple[int, float]], b: list[tuple[int, float]], k: int = RRF_K) -> list[tuple[int, float]]:
        fused: dict[int, float] = {}
        for rank, (i, _) in enumerate(a):
            fused[i] = fused.get(i, 0.0) + 1.0 / (k + rank + 1)
        for rank, (i, _) in enumerate(b):
            fused[i] = fused.get(i, 0.0) + 1.0 / (k + rank + 1)
        return sorted(fused.items(), key=lambda x: -x[1])

    def rerank(self, query: str, cands: list[tuple[int, float]], top_n: int = RERANK_TOP_N) -> list[tuple[int, float]]:
        if not cands:
            return []
        docs = [self.chunks[i]["text"] for i, _ in cands[:top_n]]
        idxs = [i for i, _ in cands[:top_n]]
        try:
            r = httpx.post(
                f"{RERANK_BASE}/rerank",
                json={"model": RERANK_MODEL, "query": query, "documents": docs, "top_n": len(docs)},
                headers={"Authorization": f"Bearer {RERANK_KEY}"},
                timeout=60,
            )
            r.raise_for_status()
            results = r.json()["results"]
            return [(idxs[item["index"]], float(item["relevance_score"])) for item in results]
        except Exception as exc:  # noqa: BLE001
            # F02：RRF 分数量纲与 rerank 不同（最大约 0.033），直接返回会让 0.30 阈值恒不通过、全部拒答。
            # 降级时把 RRF 归一化到 [0,1] 并乘 0.55，既保序又落在合理区间。
            print(f"  [warn] rerank 不可用（{type(exc).__name__}: {exc}），降级为归一化 RRF")
            top = cands[:top_n]
            if not top:
                return []
            mx = max(s for _, s in top) or 1.0
            return [(i, round(0.55 * (s / mx), 4)) for i, s in top]

    def supersede_probe(self, selected: list[dict], limit: int = 3) -> list[dict]:
        """废止/失效探针：把已选中文档里的"废止/失效/试行/过渡期"声明捞出来补进上下文。

        动机（实测）：A1 场景里"某条已被废止"的声明藏在另一份文件的附则，
        与用户问题语义距离远，纯向量/BM25 都召不回来，导致模型只能答旧数字而不说明版本关系。
        这是一个确定性补充（本地正则扫描，不额外调用模型/接口）。
        """
        import re as _re

        pattern = _re.compile(r"(同时废止|已被废止|废止|失效|试行期|过渡期|停止执行|不再执行)")
        doc_ids = {s["chunk"]["doc_id"] for s in selected}
        have = {s["chunk"]["chunk_id"] for s in selected}
        found: list[dict] = []
        for i, c in enumerate(self.chunks):
            if c["doc_id"] not in doc_ids or c["chunk_id"] in have:
                continue
            if pattern.search(c["text"]):
                found.append(
                    {
                        "chunk": c,
                        "score": 0.0,
                        "idx": "",
                        "probe": True,
                    }
                )
                if len(found) >= limit:
                    break
        return found

    def search(
        self, query: str, embedder: Embedder, top_k: int = 5, use_rerank: bool = True
    ) -> dict:
        """完整检索链：dense + sparse → RRF → rerank → top_k → 废止探针补充。"""
        qvec = embedder.embed([query])[0]
        dense = self.dense(qvec)
        sparse = self.sparse(query)
        fused = self.rrf(dense, sparse)
        reranked = self.rerank(query, fused, RERANK_TOP_N) if use_rerank else fused[:RERANK_TOP_N]
        selected = [
            {"chunk": self.chunks[i], "score": round(s, 4), "idx": f"c{n + 1:02d}"}
            for n, (i, s) in enumerate(reranked[:top_k])
        ]
        # 探针只作为候选返回，是否并入上下文由调用方按"是否决定作答"决定
        # （否则无答案问题也会被塞进一堆无关的"废止"条款，污染上下文）
        probes = self.supersede_probe(selected)
        return {
            "dense": [(self.chunks[i]["chunk_id"], round(s, 4)) for i, s in dense[:10]],
            "sparse": [(self.chunks[i]["chunk_id"], round(s, 4)) for i, s in sparse[:10]],
            "fused_count": len(fused),
            "reranked": [(self.chunks[i]["chunk_id"], round(s, 4)) for i, s in reranked],
            "selected": selected,
            "probes": probes,
        }

    def stats(self) -> dict:
        return {
            "chunk_count": len(self.chunks),
            "docs": len({c["doc_id"] for c in self.chunks}),
            "embed_model": self.model,
            "embed_dim": int(self.emb.shape[1]) if self.emb.size else 0,
        }


def load_index() -> Index:
    return Index.load()
