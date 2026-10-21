"""C 段：生成模型 provider 对比（延迟为主，附带答案长度与拒答）。

用法：python -m scripts.bench_providers
输出：evidence/bench-providers.json + 控制台表
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from src.core import EVIDENCE, MODEL_MAIN  # noqa: E402
from src.rag import answer_once  # noqa: E402
from src.vector import Embedder, load_index  # noqa: E402

QUESTIONS = [
    "单笔采购金额500万元以上的采购项目，需要提交什么会议审议？",
    "中标供应商应在多少天内与公司签订书面合同？",
    "供应商等级会影响采购参与和评审吗？岗位竞聘面试又有哪些考官要求？",
    "员工的婚假有多少天？",
]

# (标签, 模型, reasoning_effort)
CANDIDATES = [
    ("luna-none", MODEL_MAIN, "none"),
    ("glm-low", "opencode-go/glm-5.3", "low"),
    ("deepseek-low", "opencode-go/deepseek-v4.1-flash", "low"),
    ("kimi-max", "opencode-go/kimi-k3", "max"),
    ("sol-none", "rocco/gpt-6-sol", "none"),
]


def main() -> int:
    index, embedder = load_index(), Embedder()
    record: dict = {"ran_at": datetime.now().astimezone().isoformat(timespec="seconds"), "cases": {}}

    for label, model, effort in CANDIDATES:
        rows = []
        for q in QUESTIONS:
            try:
                r = answer_once(q, index, embedder, model=model)
                rows.append(
                    {
                        "q": q[:40],
                        "ttft_ms": r.get("ttft_e2e_ms") or r.get("ttft_ms"),
                        "elapsed_ms": r.get("elapsed_ms"),
                        "chars": len(r.get("answer") or ""),
                        "refused": r.get("refused"),
                        "timed_out": r.get("timed_out"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                rows.append({"q": q[:40], "error": f"{type(exc).__name__}: {exc}"})
        ok = [x for x in rows if x.get("elapsed_ms")]
        lat = [x["elapsed_ms"] for x in ok]
        record["cases"][label] = {
            "model": model,
            "effort": effort,
            "rows": rows,
            "ok": len(ok),
            "total": len(rows),
            "p50_ms": round(statistics.median(lat), 1) if lat else None,
            "max_ms": max(lat) if lat else None,
        }
        print(
            f"{label:14s} {model:34s} effort={effort:5s} ok={len(ok)}/{len(rows)} "
            f"p50={record['cases'][label]['p50_ms']}ms"
        )

    EVIDENCE.mkdir(exist_ok=True)
    out = EVIDENCE / f"bench-providers-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[evidence] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
