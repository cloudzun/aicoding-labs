"""v0.2 口径评测：最小事实点覆盖 + 冲突题人工判定 + claim 支撑率 + judge 可信度门禁。

用法：
    python -m eval.run_eval_v2 --dataset eval/golden_set_v2.jsonl \
        --human-verdicts eval/human_verdicts.jsonl
与 v1 评测**不可跨口径比较**，报告中同时给出旧口径对照列。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core import EVIDENCE, MODEL_JUDGE, MODEL_MAIN, REPORTS, now_iso, read_jsonl, write_json  # noqa: E402
from src.generate import judge  # noqa: E402
from src.rag import answer_once  # noqa: E402
from src.vector import Embedder, load_index  # noqa: E402

JUDGE_FAIL_MAX = 0.02


def pct(v: list[float], q: float) -> float | None:
    if not v:
        return None
    s = sorted(v)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def derive_verdict(j: dict, facts: list[str]) -> str:
    """按 facts 覆盖情况推导 verdict（v0.2 口径）。"""
    covered = j.get("covered_facts") or []
    missing = j.get("missing_facts") or []
    if facts:
        if not missing:
            return "correct"
        if covered:
            return "partial"
        return "wrong"
    # 没有 facts 的题退回 judge 的原始 verdict
    return j.get("verdict") or "error"


def run(rows: list[dict], index, embedder, human_verdicts: dict[str, dict], do_judge: bool) -> dict:
    results = []
    for n, row in enumerate(rows, start=1):
        q = row["question"]
        search = index.search(q, embedder, top_k=5)
        head = [s["chunk"]["chunk_id"] for s in search["selected"]]
        gold = row.get("gold_chunk_ids") or []
        res = answer_once(q, index, embedder)
        answer = res.get("answer", "")

        item = {
            "qid": row.get("qid"),
            "split": row.get("split"),
            "question": q,
            "facts": row.get("facts") or [],
            "facts_source": row.get("facts_source"),
            "retrieved": head,
            "recall_hit": bool(gold) and any(g in head for g in gold),
            "recall_all_hit": (all(g in head for g in gold) if gold else None),
            "answer": answer,
            "refused": res.get("refused"),
            "ttft_ms": res.get("ttft_e2e_ms") or res.get("ttft_ms"),
            "elapsed_ms": res.get("elapsed_ms"),
            "invalid_citations": res.get("invalid_citations") or [],
            "claim_support_rate": res.get("claim_support_rate"),
            "unsupported_claims": res.get("unsupported_claims") or [],
            "timed_out": res.get("timed_out"),
        }

        hv = human_verdicts.get(row.get("qid") or "")
        if hv:
            item["verdict"] = hv["verdict"]
            item["verdict_source"] = "human"
            item["verdict_reason"] = hv.get("reason", "")
        elif do_judge and row.get("answerable", True) and not res.get("refused"):
            material = "\n\n".join(s["text"] for s in res.get("meta", {}).get("sources", []))
            j = judge(q, row.get("gold_answer") or "", material, answer)
            if j.get("verdict") == "error":
                item["verdict"] = "judge_error"
                item["judge_error"] = j.get("error")
            else:
                item["verdict"] = derive_verdict(j, item["facts"])
                item["judge"] = {
                    "raw_verdict": j.get("verdict"),
                    "covered_facts": j.get("covered_facts") or [],
                    "missing_facts": j.get("missing_facts") or [],
                    "hallucinations": j.get("hallucinations") or [],
                    "reason": j.get("reason", ""),
                    "judge_model": j.get("_judge_model"),
                }
            item["verdict_source"] = "judge"
        else:
            item["verdict"] = "not_judged"
            item["verdict_source"] = "none"

        results.append(item)
        if n % 10 == 0:
            print(f"  {n}/{len(rows)}")
            sys.stdout.flush()
    return aggregate(results)


def aggregate(results: list[dict]) -> dict:
    ans = [r for r in results if r.get("split") != "unanswerable"]
    judged = [r for r in ans if r["verdict"] in ("correct", "partial", "wrong") and not r.get("refused")]
    refused_ans = [r for r in ans if r.get("refused")]
    judge_errors = [r for r in ans if r["verdict"] == "judge_error"]
    correct = [r for r in judged if r["verdict"] == "correct"]
    partial = [r for r in judged if r["verdict"] == "partial"]
    wrong = [r for r in judged if r["verdict"] == "wrong"]

    answered = [r for r in results if not r.get("refused") and r.get("elapsed_ms")]
    ttft = [r["ttft_ms"] for r in answered if r.get("ttft_ms")]
    elapsed = [r["elapsed_ms"] for r in answered if r.get("elapsed_ms")]
    claim_rates = [r["claim_support_rate"] for r in answered if r.get("claim_support_rate") is not None]
    recall_pool = [r for r in ans if r["recall_hit"] is not None]

    judge_denom = max(1, len(judged) + len(judge_errors))
    return {
        "generated_at": now_iso(),
        "metric_version": "v0.2",
        "model": MODEL_MAIN,
        "judge_model": MODEL_JUDGE,
        "n_total": len(results),
        "n_answered": len(answered),
        "n_judged_valid": len(judged),
        "n_judge_error": len(judge_errors),
        "judge_fail_rate": round(len(judge_errors) / judge_denom, 4),
        "accuracy_v2": round(len(correct) / len(judged), 4) if judged else None,
        "partial_rate": round(len(partial) / len(judged), 4) if judged else None,
        "wrong_rate": round(len(wrong) / len(judged), 4) if judged else None,
        "refusal_rate_on_answerable": round(len(refused_ans) / len(ans), 4) if ans else None,
        "recall_at_5": round(sum(1 for r in recall_pool if r["recall_hit"]) / len(recall_pool), 4) if recall_pool else None,
        "claim_support_rate": round(sum(claim_rates) / len(claim_rates), 4) if claim_rates else None,
        "ttft_p50_ms": round(pct(ttft, 0.5), 1) if ttft else None,
        "ttft_p95_ms": round(pct(ttft, 0.95), 1) if ttft else None,
        "elapsed_p50_ms": round(pct(elapsed, 0.5), 1) if elapsed else None,
        "elapsed_p95_ms": round(pct(elapsed, 0.95), 1) if elapsed else None,
        "by_split": {
            s: {
                "n": len([r for r in results if r["split"] == s]),
                "correct": sum(1 for r in results if r["split"] == s and r["verdict"] == "correct"),
                "partial": sum(1 for r in results if r["split"] == s and r["verdict"] == "partial"),
                "judge_error": sum(1 for r in results if r["split"] == s and r["verdict"] == "judge_error"),
            }
            for s in sorted({r["split"] for r in results})
        },
        "failures": [
            {
                "qid": r["qid"],
                "split": r["split"],
                "verdict": r["verdict"],
                "missing_facts": (r.get("judge") or {}).get("missing_facts"),
                "hallucinations": (r.get("judge") or {}).get("hallucinations"),
                "reason": (r.get("judge") or {}).get("reason") or r.get("verdict_reason"),
            }
            for r in results
            if r["verdict"] in ("partial", "wrong")
        ][:40],
        "results": results,
    }


def build_gate(a: dict) -> dict:
    rows = []

    def add(name, threshold, value, ok, fmt="pct"):
        shown = "—" if value is None else (f"{value:.2%}" if fmt == "pct" else f"{value}")
        rows.append({"metric": name, "threshold": threshold, "actual": shown,
                     "status": "SKIP" if value is None else ("PASS" if ok else "FAIL")})

    add("AC-02 答案正确率（facts 口径）", "≥85%", a["accuracy_v2"], (a["accuracy_v2"] or 0) >= 0.85)
    add("AC-11 claim 支撑率", "≥90%", a["claim_support_rate"], (a["claim_support_rate"] or 0) >= 0.90)
    add("AC-12 judge 失败率", "≤2%", a["judge_fail_rate"], a["judge_fail_rate"] <= JUDGE_FAIL_MAX)
    add("AC-01 Chunk-ID Recall@5", "≥90%", a["recall_at_5"], (a["recall_at_5"] or 0) >= 0.90)
    add("AC-05 误拒率", "≤5%", a["refusal_rate_on_answerable"], (a["refusal_rate_on_answerable"] or 0) <= 0.05)
    add("AC-07 TTFT p95", "≤1000ms", a["ttft_p95_ms"], (a["ttft_p95_ms"] or 0) <= 1000, fmt="ms")
    add("AC-08 完成 p95", "≤5000ms", a["elapsed_p95_ms"], (a["elapsed_p95_ms"] or 0) <= 5000, fmt="ms")

    fails = [x for x in rows if x["status"] == "FAIL"]
    skips = [x for x in rows if x["status"] == "SKIP"]
    if a["judge_fail_rate"] > JUDGE_FAIL_MAX:
        verdict = f"INCOMPLETE —— judge 失败率 {a['judge_fail_rate']:.2%} 超过 {JUDGE_FAIL_MAX:.0%}，正确率不可读"
    elif fails:
        verdict = "FAIL —— " + "、".join(x["metric"] for x in fails)
    elif skips:
        verdict = "INCOMPLETE —— 未测：" + "、".join(x["metric"] for x in skips)
    else:
        verdict = "PASS"
    return {"verdict": verdict, "rows": rows}


def to_md(a: dict, gate: dict) -> str:
    lines = [
        "# 评测报告 v0.2（facts 口径）",
        "",
        f"> 生成时间：{a['generated_at']}　模型：`{a['model']}`　judge：`{a['judge_model']}`",
        "> **本报告与 v1 报告不可跨口径比较。** 口径定义见 [docs/07-SPEC-v0.2增量.md](../docs/07-SPEC-v0.2增量.md)。",
        "",
        "## 一、门禁结论",
        "",
        f"**{gate['verdict']}**",
        "",
        "| 指标 | 门槛 | 实测 | 判定 |",
        "|---|---|---|---|",
    ]
    for r in gate["rows"]:
        lines.append(f"| {r['metric']} | {r['threshold']} | {r['actual']} | {r['status']} |")
    lines += [
        "",
        "## 二、分桶（verdict 分布）",
        "",
        "| 分桶 | n | correct | partial | judge_error |",
        "|---|---|---|---|---|",
    ]
    for s, v in a["by_split"].items():
        lines.append(f"| {s} | {v['n']} | {v['correct']} | {v['partial']} | {v['judge_error']} |")
    lines += [
        "",
        f"- 有效判定 {a['n_judged_valid']} 条，judge 失败 {a['n_judge_error']} 条（失败率 {a['judge_fail_rate']:.2%}）",
        f"- 拒答率（可回答题上）：{a['refusal_rate_on_answerable']:.2%}" if a["refusal_rate_on_answerable"] is not None else "",
        f"- claim 支撑率：{a['claim_support_rate']:.2%}" if a["claim_support_rate"] is not None else "- claim 支撑率：—",
        f"- TTFT p50/p95：{a['ttft_p50_ms']} / {a['ttft_p95_ms']} ms",
        f"- 完成 p50/p95：{a['elapsed_p50_ms']} / {a['elapsed_p95_ms']} ms",
        "",
        "## 三、失败样本（前 40）",
        "",
    ]
    for f in a["failures"]:
        lines.append(f"- `{f['qid']}` [{f['verdict']}] 缺：{f.get('missing_facts')} ｜ 无依据：{f.get('hallucinations')} ｜ {f.get('reason','')[:80]}")
    lines += [
        "",
        "## 四、诚实边界",
        "",
        "- `facts` 由 LLM 抽取（8 条冲突/时效题为人工手写），已按会审 E1-01 抽检 20%。",
        "- 冲突/时效题为**人工判定**，判定人 Lead，客户抽检 20% 尚未进行。",
        "- claim 支撑率为 **3-gram 下限指标**，不能证明语义支撑。",
        "- 延迟为单机单并发采样。",
        "",
    ]
    return "\n".join(x for x in lines if x is not None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(ROOT / "eval" / "golden_set_v2.jsonl"))
    ap.add_argument("--human-verdicts", default=str(ROOT / "eval" / "human_verdicts.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-judge", action="store_true")
    args = ap.parse_args()

    rows = read_jsonl(Path(args.dataset))
    if not rows:
        print("数据集为空：先运行 python -m scripts.make_gold_facts")
        return 1
    if args.limit:
        rows = rows[: args.limit]
    hv = {r["qid"]: r for r in read_jsonl(Path(args.human_verdicts))} if Path(args.human_verdicts).exists() else {}

    index, embedder = load_index(), Embedder()
    print(f"[eval-v2] {len(rows)} 条，judge={not args.no_judge}，人工判定 {len(hv)} 条")
    agg = run(rows, index, embedder, hv, do_judge=not args.no_judge)
    gate = build_gate(agg)
    agg["gate"] = gate

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    REPORTS.mkdir(parents=True, exist_ok=True)
    write_json(REPORTS / f"eval-v2-{stamp}.json", agg)
    write_json(EVIDENCE / f"eval-v2-{stamp}.json", agg)
    md = to_md(agg, gate)
    (REPORTS / "EVAL-REPORT-v0.2.md").write_text(md, encoding="utf-8")
    (EVIDENCE / "EVAL-REPORT-v0.2.md").write_text(md, encoding="utf-8")

    print("\n=== 门禁 v0.2 ===")
    for r in gate["rows"]:
        print(f"  {r['metric']:34s} {r['threshold']:10s} {r['actual']:>10s} {r['status']}")
    print(f"\n结论：{gate['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
