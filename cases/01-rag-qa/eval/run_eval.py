"""评测：一条命令产出六项指标 + 分桶 + 错误分类。

用法：
    python -m eval.run_eval                      # 全量（含 LLM judge）
    python -m eval.run_eval --limit 40 --no-judge # 快速冒烟（只测召回/拒答/延迟）
    python -m eval.run_eval --dataset eval/refusal_set.jsonl --refusal
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

from src.core import EVIDENCE, MIN_RERANK_SCORE, MODEL_JUDGE, MODEL_MAIN, REPORTS, now_iso, read_jsonl, write_json
from src.generate import judge
from src.rag import answer_once
from src.vector import Embedder, load_index

ROOT = Path(__file__).resolve().parents[1]


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def run(rows: list[dict], index, embedder, do_judge: bool, refusal_mode: bool) -> dict:
    results: list[dict] = []
    for n, row in enumerate(rows, start=1):
        q = row["question"]
        # 检索（只用 head，不含废止探针，避免用探针虚高召回）
        search = index.search(q, embedder, top_k=5)
        head_ids = [s["chunk"]["chunk_id"] for s in search["selected"]]
        gold = row.get("gold_chunk_ids") or []
        hit = bool(gold) and any(g in head_ids for g in gold)
        recall_strict = bool(gold) and all(g in head_ids for g in gold) if gold else None

        res = answer_once(q, index, embedder)
        answer = res.get("answer", "")
        refused = bool(res.get("refused"))
        item = {
            "qid": row.get("qid"),
            "split": row.get("split"),
            "answerable": row.get("answerable", True),
            "question": q,
            "gold_chunk_ids": gold,
            "retrieved": head_ids,
            "recall_hit": hit,
            "recall_all_hit": recall_strict,
            "answer": answer,
            "refused": refused,
            "ttft_ms": res.get("ttft_e2e_ms") or res.get("ttft_ms"),
            "elapsed_ms": res.get("elapsed_ms"),
            "invalid_citations": res.get("invalid_citations", []),
            "timed_out": res.get("timed_out", False),
        }

        if do_judge and not refusal_mode and row.get("answerable") and not refused:
            material = "\n\n".join(s["text"] for s in res.get("meta", {}).get("sources", []))
            j = judge(q, row.get("gold_answer") or "", material, answer)
            item["judge"] = {
                "verdict": j.get("verdict"),
                "covered_facts": j.get("covered_facts", []),
                "hallucinations": j.get("hallucinations", []),
                "reason": j.get("reason", ""),
                "judge_model": j.get("_judge_model", MODEL_JUDGE),
            }
            # F13：judge 失败不得算作忠实
            if j.get("verdict") in ("correct", "partial", "wrong", "unsupported"):
                item["faithful"] = len(j.get("hallucinations") or []) == 0
            else:
                item["judge_error"] = True

        results.append(item)
        if n % 10 == 0:
            print(f"  {n}/{len(rows)}")
            sys.stdout.flush()
    return aggregate(results, do_judge, refusal_mode)


def aggregate(results: list[dict], do_judge: bool, refusal_mode: bool) -> dict:
    answerable = [r for r in results if r["answerable"]]
    unanswerable = [r for r in results if not r["answerable"]]

    recall = [r for r in answerable if r["recall_hit"] is not None]
    recall_rate = (sum(1 for r in recall if r["recall_hit"]) / len(recall)) if recall else None
    recall_all = [r for r in recall if r["recall_all_hit"] is not None]
    recall_all_rate = (sum(1 for r in recall_all if r["recall_all_hit"]) / len(recall_all)) if recall_all else None

    refused_ans = [r for r in answerable if r["refused"]]
    misrefusal = len(refused_ans) / len(answerable) if answerable else None

    refused_un = [r for r in unanswerable if r["refused"]]
    refusal_rate = len(refused_un) / len(unanswerable) if unanswerable else None

    judged = [r for r in answerable if r.get("judge")]
    correct = [r for r in judged if r["judge"]["verdict"] == "correct"]
    partial = [r for r in judged if r["judge"]["verdict"] == "partial"]
    faith = [r for r in judged if r.get("faithful")]
    halluc = [r for r in judged if r.get("faithful") is False]

    answered = [r for r in results if not r["refused"] and r.get("elapsed_ms")]
    ttft = [r["ttft_ms"] for r in answered if r.get("ttft_ms")]
    elapsed = [r["elapsed_ms"] for r in answered if r.get("elapsed_ms")]
    cite_ok = [r for r in answered if not r["invalid_citations"]]

    def by_split(key: str) -> dict:
        out = {}
        for split in sorted({r["split"] for r in results}):
            sub = [r for r in results if r["split"] == split]
            out[split] = {
                "n": len(sub),
                "recall_hit": round(sum(1 for r in sub if r["recall_hit"]) / len([r for r in sub if r["recall_hit"] is not None]), 4)
                if any(r["recall_hit"] is not None for r in sub)
                else None,
                "refused": round(sum(1 for r in sub if r["refused"]) / len(sub), 4),
                "correct": round(sum(1 for r in sub if (r.get("judge") or {}).get("verdict") == "correct") / len([r for r in sub if r.get("judge")]), 4)
                if any(r.get("judge") for r in sub)
                else None,
            }
        return out

    return {
        "generated_at": now_iso(),
        "mode": {"judge": do_judge, "refusal_mode": refusal_mode, "model": MODEL_MAIN, "judge_model": MODEL_JUDGE},
        "n_total": len(results),
        "n_answerable": len(answerable),
        "n_unanswerable": len(unanswerable),
        "recall_at_5": round(recall_rate, 4) if recall_rate is not None else None,
        "recall_at_5_all_gold": round(recall_all_rate, 4) if recall_all_rate is not None else None,
        "accuracy_correct": round(len(correct) / len(judged), 4) if judged else None,
        # F12：以全部可回答题为分母（拒答计为未答对），避免靠拒答抬高正确率
        "accuracy_over_answerable": round(len(correct) / len(answerable), 4) if (answerable and judged) else None,
        "judged_count": len(judged),
        "judge_error_count": sum(1 for r in judged if r.get("judge_error")),
        "accuracy_partial": round(len(partial) / len(judged), 4) if judged else None,
        "faithfulness": round(len(faith) / len(judged), 4) if judged else None,
        "hallucination_rate": round(len(halluc) / len(judged), 4) if judged else None,
        "refusal_rate": round(refusal_rate, 4) if refusal_rate is not None else None,
        "misrefusal_rate": round(misrefusal, 4) if misrefusal is not None else None,
        "citation_ok_rate": round(len(cite_ok) / len(answered), 4) if answered else None,
        "ttft_p50_ms": round(pct(ttft, 0.5), 1) if ttft else None,
        "ttft_p95_ms": round(pct(ttft, 0.95), 1) if ttft else None,
        "elapsed_p50_ms": round(pct(elapsed, 0.5), 1) if elapsed else None,
        "elapsed_p95_ms": round(pct(elapsed, 0.95), 1) if elapsed else None,
        "n_latency_samples": len(elapsed),
        "by_split": by_split("split"),
        "errors": [
            {"qid": r["qid"], "question": r["question"], "verdict": r["judge"]["verdict"], "reason": r["judge"]["reason"]}
            for r in judged
            if r["judge"]["verdict"] in ("wrong", "partial", "unsupported")
        ][:30],
        "invalid_citation_examples": [
            {"qid": r["qid"], "invalid": r["invalid_citations"]} for r in answered if r["invalid_citations"]
        ][:10],
        "results": results,
    }


def to_markdown(agg: dict, gate: dict) -> str:
    def fmt(v, suffix="") -> str:
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:.2%}" if v <= 1.0 and suffix == "%" else f"{v}"
        return f"{v}{suffix}"

    lines = [
        "# 评测报告（EVAL-REPORT）",
        "",
        f"> 生成时间：{agg['generated_at']}　模型：`{agg['mode']['model']}`　judge：`{agg['mode']['judge_model']}`",
        "> 口径见 [docs/00-数据与口径.md](docs/00-数据与口径.md)；本报告由 `python -m eval.run_eval` 生成，不手工编辑。",
        "",
        "## 一、门禁结论",
        "",
        f"**{gate['verdict']}**",
        "",
        "| 指标 | 门禁 | 实测 | 判定 |",
        "|---|---|---|---|",
    ]
    for row in gate["rows"]:
        lines.append(f"| {row['metric']} | {row['threshold']} | {row['actual']} | {row['status']} |")
    lines += [
        "",
        "## 二、分桶",
        "",
        "| 分桶 | n | 召回 | 拒答率 | 正确率 |",
        "|---|---|---|---|---|",
    ]
    for split, s in agg["by_split"].items():
        lines.append(
            f"| {split} | {s['n']} | {fmt(s['recall_hit'], '%')} | {fmt(s['refused'], '%')} | {fmt(s['correct'], '%')} |"
        )
    lines += [
        "",
        "## 三、延迟与引用",
        "",
        f"- TTFT p50/p95：{agg['ttft_p50_ms']} / {agg['ttft_p95_ms']} ms（n={agg['n_latency_samples']}）",
        f"- 完成 p50/p95：{agg['elapsed_p50_ms']} / {agg['elapsed_p95_ms']} ms",
        f"- 引用可定位率：{fmt(agg['citation_ok_rate'], '%')}",
        f"- 无效引用样例：{json.dumps(agg['invalid_citation_examples'], ensure_ascii=False)}",
        "",
        "## 四、错误分类（前 30 条）",
        "",
    ]
    if agg["errors"]:
        for e in agg["errors"]:
            lines.append(f"- `{e['qid']}` [{e['verdict']}] {e['question'][:60]} —— {e['reason'][:80]}")
    else:
        lines.append("- 无（或未启用 judge）")
    lines += [
        "",
        "## 五、诚实边界",
        "",
        "- 单跳/多跳/无关题为 **LLM 生成**，仅 8 条冲突/时效题为人工手写；对外使用前需人工复核全量评测集。",
        "- 正确率与忠实性由**独立模型**判定（judge 与被测模型不同族），但仍属 LLM-as-Judge，存在误差；报告中保留 judge 的判定理由供人工抽检。",
        "- 延迟为单机单并发采样，非生产压测值。",
        "",
    ]
    return "\n".join(lines)


def build_gate(agg: dict) -> dict:
    def status(ok: bool | None) -> str:
        return "PASS" if ok else "FAIL"

    r = agg["recall_at_5"] or 0
    a = agg.get("accuracy_over_answerable")
    f = agg["faithfulness"]
    rf = agg["refusal_rate"]
    mr = agg["misrefusal_rate"]
    cr = agg["citation_ok_rate"] or 0
    ttft = agg["ttft_p95_ms"]
    elapsed = agg["elapsed_p95_ms"]

    rows = [
        {"metric": "Chunk-ID Recall@5", "threshold": "≥90%", "actual": f"{r:.2%}", "status": status(r >= 0.90)},
        {
            "metric": "答案正确率",
            "threshold": "≥85%",
            "actual": "—（未启用 judge）" if a is None else f"{a:.2%}",
            "status": "SKIP" if a is None else status(a >= 0.85),
        },
        {
            "metric": "Faithfulness（1−幻觉率）",
            "threshold": "≥90%",
            "actual": "—（未启用 judge）" if f is None else f"{f:.2%}",
            "status": "SKIP" if f is None else status(f >= 0.90),
        },
        {
            "metric": "应拒答率",
            "threshold": "≥90%",
            "actual": "—（本数据集无不可回答项）" if rf is None else f"{rf:.2%}",
            "status": "SKIP" if rf is None else status(rf >= 0.90),
        },
        {
            "metric": "误拒率",
            "threshold": "≤5%",
            "actual": "—" if mr is None else f"{mr:.2%}",
            "status": "SKIP" if mr is None else status(mr <= 0.05),
        },
        {"metric": "引用可定位率", "threshold": "≥95%", "actual": f"{cr:.2%}", "status": status(cr >= 0.95)},
        {
            "metric": "TTFT p95",
            "threshold": "≤1000ms",
            "actual": "—" if ttft is None else f"{ttft:.0f}ms",
            "status": "SKIP" if ttft is None else status(ttft <= 1000),
        },
        {
            "metric": "完成 p95",
            "threshold": "≤5000ms",
            "actual": "—" if elapsed is None else f"{elapsed:.0f}ms",
            "status": "SKIP" if elapsed is None else status(elapsed <= 5000),
        },
    ]
    fails = [x for x in rows if x["status"] == "FAIL"]
    skipped = [x for x in rows if x["status"] == "SKIP"]
    if fails:
        verdict = "FAIL —— 以下门禁未通过：" + "、".join(x["metric"] for x in fails)
    elif skipped:
        # F12：必需指标未测时不得输出 PASS
        verdict = "INCOMPLETE —— 以下必需项未测：" + "、".join(x["metric"] for x in skipped)
    else:
        verdict = "PASS"
    return {"verdict": verdict, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(ROOT / "eval" / "golden_set.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--refusal", action="store_true", help="该数据集全部视为不可回答")
    args = ap.parse_args()

    rows = read_jsonl(Path(args.dataset))
    if not rows:
        print("评测集为空：先运行 python -m scripts.make_golden_set")
        return 1
    if args.limit:
        rows = rows[: args.limit]
    if args.refusal:
        for r in rows:
            r["answerable"] = False

    index = load_index()
    embedder = Embedder()
    print(f"[eval] {len(rows)} 条，judge={not args.no_judge}")
    agg = run(rows, index, embedder, do_judge=not args.no_judge, refusal_mode=args.refusal)
    gate = build_gate(agg)
    agg["gate"] = gate

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    REPORTS.mkdir(parents=True, exist_ok=True)
    write_json(REPORTS / f"eval-{stamp}.json", agg)
    write_json(EVIDENCE / f"eval-{stamp}.json", agg)
    md = to_markdown(agg, gate)
    (REPORTS / "EVAL-REPORT.md").write_text(md, encoding="utf-8")
    (EVIDENCE / "EVAL-REPORT.md").write_text(md, encoding="utf-8")

    print("\n=== 门禁 ===")
    for row in gate["rows"]:
        print(f"  {row['metric']:24s} {row['threshold']:10s} {row['actual']:22s} {row['status']}")
    print(f"\n结论：{gate['verdict']}")
    print(f"报告：{REPORTS / 'EVAL-REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
