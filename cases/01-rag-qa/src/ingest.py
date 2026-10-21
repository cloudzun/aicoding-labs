"""离线建库：解析语料 → 切分 → 嵌入 → 落盘索引。

用法：
    python -m src.ingest            # 建库
    python -m src.ingest --dry-run  # 只解析切分，不调嵌入接口
"""

from __future__ import annotations

import argparse
import sys

from .core import INDEX, ensure_dirs, now_iso, write_json
from .corpus import build_chunks, corpus_fingerprint
from .vector import Embedder, EmbeddingError, Index


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只解析与切分，不调用嵌入接口")
    args = ap.parse_args()

    ensure_dirs()
    chunks = build_chunks()
    if not chunks:
        print("语料为空：请先放入 data/corpus/synthetic 或 data/corpus/public")
        return 1
    print(f"[1/3] 解析完成：{len(chunks)} 个 chunk，{len({c['doc_id'] for c in chunks})} 份文档")
    if args.dry_run:
        print("[dry-run] 跳过嵌入")
        return 0

    try:
        embedder = Embedder()
    except EmbeddingError as exc:
        print(f"[失败] {exc}")
        print("提示：检查 .env 中的 SILICONFLOW_KEY；当前环境断网时无法建库。")
        return 2

    print(f"[2/3] 嵌入中（模型 {embedder.model}，缓存命中后不重复计费）……")
    try:
        idx = Index.build(chunks, embedder)
    except EmbeddingError as exc:
        print(f"[失败] {exc}")
        print("已完成的批次已落盘缓存，修好网络后重跑即可续跑。")
        return 3

    meta = {
        "built_at": now_iso(),
        "chunk_count": len(chunks),
        "doc_count": len({c["doc_id"] for c in chunks}),
        "embed_model": idx.model,
        "embed_dim": int(idx.emb.shape[1]),
        "corpus_sha256": corpus_fingerprint(chunks),
        "chunker_version": "1.0",
    }
    write_json(INDEX / "meta.json", meta)
    print(f"[3/3] 索引已保存：{INDEX}")
    print(f"      chunks={meta['chunk_count']} docs={meta['doc_count']} dim={meta['embed_dim']}")
    print(f"      corpus_sha256={meta['corpus_sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
