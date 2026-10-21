"""EX 全自动评测（零 judge 依赖）。

标准结果集在评测时用 gold SQL 现场执行取得（库有固定 sha256，结果确定）。

用法：
    python -m eval.run_eval --limit 5      # 冒烟
    python -m eval.run_eval                # 主集 150
    python -m eval.run_eval --anchors      # 锚点集 20
    python -m eval.run_eval --ambiguity    # 歧义集 15
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline import ask  # noqa: E402

DB = ROOT / "data" / "aicoding.db"
GOLDEN = ROOT / "eval" / "golden_set.jsonl"
ANCHORS = ROOT / "eval" / "anchor_set.jsonl"
AMBIG = ROOT / "eval" / "ambiguity_set.jsonl"
REPORTS = ROOT / "eval" / "reports"
EVIDENCE = ROOT / "evidence"

TOL = 0.011
AC = {"ex": 0.85, "executable": 0.95, "single_hop": 0.90, "join": 0.80, "other": 0.80}


def pct(v: list[float], q: float):
    if not v:
        return None
    s = sorted(v)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


def kind(v):
    if isinstance(v, bool):
        return "b"
    if isinstance(v, (int, float)):
        return "n"
    if v is None:
        return "x"
    return "s"


def cell_eq(a, b) -> bool:
    if kind(a) == "n" and kind(b) == "n":
        return abs(float(a) - float(b)) <= TOL
    # 先处理 NULL 与数值（允许 "57" 与 57 等价，但 NULL 只与 NULL 等）
    if a is None or b is None:
        return a is None and b is None
    if kind(a) == "n" or kind(b) == "n":
        try:
            return abs(float(a) - float(b)) <= TOL
        except (TypeError, ValueError):
            return False
    # 标签类比较忽略分隔符与大小写（季度标签 2026-Q1 / 2026Q1 视为相同）
    def norm_label(v) -> str:
        return "".join(ch for ch in str(v).strip().lower() if ch not in "-_/ ")

    return norm_label(a) == norm_label(b)


def run_sql(sql: str) -> tuple[list[str], list[list]]:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description]
        return cols, [list(r) for r in cur.fetchall()]
    finally:
        conn.close()


def compare(gold_cols, gold_rows, out_cols, out_rows, ordered: bool) -> tuple[bool, str]:
    if len(gold_cols) != len(out_cols):
        return False, f"列数不同（gold {len(gold_cols)} / out {len(out_cols)}）"
    if len(gold_rows) != len(out_rows):
        return False, f"行数不同（gold {len(gold_rows)} / out {len(out_rows)}）"
    if len(gold_rows) == 1 and len(gold_cols) == 1:
        return (True, "") if cell_eq(gold_rows[0][0], out_rows[0][0]) else (
            False,
            f"值不同（{gold_rows[0][0]} vs {out_rows[0][0]}）",
        )
    if ordered:
        ok = all(cell_eq(a, b) for gr, orow in zip(gold_rows, out_rows) for a, b in zip(gr, orow))
        return (True, "") if ok else (False, "顺序或内容不一致")
    # 行多重集比较：列序无关、经 cell_eq（容差 + 标签归一化）
    used = [False] * len(out_rows)
    for gr in gold_rows:
        found = False
        for i, orow in enumerate(out_rows):
            if used[i]:
                continue
            if all(cell_eq(a, b) for a, b in zip(gr, orow)):
                used[i] = True
                found = True
                break
        if not found:
            return False, "结果集不一致"
    return True, ""


def evaluate(rows: list[dict], label: str, stamp: str) -> dict:
    results = []
    for i, row in enumerate(rows, start=1):
        gold_sql = row["sql"]
        try:
            gold_cols, gold_rows = run_sql(gold_sql)
        except Exception as exc:  # noqa: BLE001
            results.append({"qid": row["qid"], "split": row.get("split", "?"), "question": row["question"],
                            "gold_sql": gold_sql, "out_sql": None, "clarification": None, "rejected": None,
                            "attempts": 0, "row_count": 0, "gold_row_count": 0, "elapsed_ms": None,
                            "generate_ms": None, "blocked": False, "advisory": False, "executed": False,
                            "ex": False, "reason": f"gold SQL 执行失败：{type(exc).__name__}"})
            continue
        # 只有题面明确要求排序（最高/前N/降序/排名）时才校验行顺序；
        # 否则 gold 模板自带的 ORDER BY 不代表题面要求，按集合比。
        ORDER_WORDS = ("最高", "最低", "最多", "最少", "前", "Top", "降序", "升序", "排名", "从高到低", "从低到高", "最近")
        ordered = "order by" in gold_sql.lower() and any(w in row["question"] for w in ORDER_WORDS)

        r = ask(row["question"], clarify=True)
        rec = {
            "qid": row["qid"],
            "split": row.get("split", "anchor"),
            "question": row["question"],
            "gold_sql": gold_sql,
            "out_sql": r["sql"],
            "clarification": r["clarification"],
            "rejected": r["rejected"],
            "attempts": r["attempts"],
            "row_count": r["row_count"],
            "gold_row_count": len(gold_rows),
            "elapsed_ms": r["timings_ms"].get("total"),
            "generate_ms": r["timings_ms"].get("generate"),
            "blocked": bool((r["clarification"] or {}).get("blocking")),
            "advisory": bool(r["clarification"]) and not (r["clarification"] or {}).get("blocking"),
            "executed": bool(r["sql"]) and not r["rejected"] and not (r["clarification"] or {}).get("blocking"),
            "ex": False,
            "reason": "",
        }
        if rec["blocked"]:
            rec["reason"] = "触发了阻塞式反问，未作答"
        elif rec["rejected"]:
            rec["reason"] = "被拒：" + str(r["rejected"].get("reason"))[:100]
        elif not r["sql"]:
            rec["reason"] = "未生成 SQL"
        else:
            # 用完整结果比较（rows_full），避免展示层 200 行截断污染 EX（codex 评审 #1）
            ok, why = compare(gold_cols, gold_rows, r["columns"], r.get("rows_full", r["rows"]), ordered)
            rec["ex"] = ok
            rec["reason"] = why
            if not ok:
                rec["gold_preview"] = gold_rows[:3]
                rec["out_preview"] = r["rows"][:3]
        results.append(rec)
        if i % 10 == 0:
            print(f"  {i}/{len(rows)}  EX={sum(1 for x in results if x['ex'])}")
            sys.stdout.flush()

    n = len(results)
    ex_n = sum(1 for x in results if x["ex"])
    exec_n = sum(1 for x in results if x["executed"])
    clar_n = sum(1 for x in results if x.get("blocked"))
    adv_n = sum(1 for x in results if x.get("advisory"))
    splits = sorted({x["split"] for x in results})
    by_split = {
        s: {
            "n": sum(1 for x in results if x["split"] == s),
            "ex": sum(1 for x in results if x["split"] == s and x["ex"]),
            "rate": round(
                sum(1 for x in results if x["split"] == s and x["ex"])
                / max(1, sum(1 for x in results if x["split"] == s)),
                4,
            ),
        }
        for s in splits
    }
    lat = [x["elapsed_ms"] for x in results if x["elapsed_ms"]]
    agg = {
        "label": label,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "n": n,
        "ex_n": ex_n,
        "ex": round(ex_n / n, 4) if n else None,
        "executable_rate": round(exec_n / n, 4) if n else None,
        "clarification_rate": round(clar_n / n, 4) if n else None,
        "advisory_rate": round(adv_n / n, 4) if n else None,
        "by_split": by_split,
        "attempts_mean": round(sum(x["attempts"] for x in results) / n, 2) if n else None,
        "latency_p50_ms": pct(lat, 0.5),
        "latency_p95_ms": pct(lat, 0.95),
        "failures": [x for x in results if not x["ex"]][:40],
        "results": results,
    }
    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE / f"eval-{label}-{stamp}.json").write_text(json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")
    return agg


def gate(a: dict) -> dict:
    rows = []

    def add(name, thr, val, ok, fmt="pct"):
        shown = "—" if val is None else (f"{val:.2%}" if fmt == "pct" else f"{val}")
        rows.append({"metric": name, "threshold": thr, "actual": shown, "status": "SKIP" if val is None else ("PASS" if ok else "FAIL")})

    add("AC-01 EX（主集）", "≥85%", a["ex"], (a["ex"] or 0) >= AC["ex"])
    add("AC-02 可执行率", "≥95%", a["executable_rate"], (a["executable_rate"] or 0) >= AC["executable"])
    if "single_hop" in a["by_split"]:
        v = a["by_split"]["single_hop"]["rate"]
        add("AC-03 单表桶 EX", "≥90%", v, v >= AC["single_hop"])
    jn = [a["by_split"].get(k, {}).get("n", 0) for k in ("two_join", "three_join")]
    jx = [a["by_split"].get(k, {}).get("ex", 0) for k in ("two_join", "three_join")]
    if sum(jn):
        v = sum(jx) / sum(jn)
        add("AC-04 JOIN 桶 EX", "≥80%", v, v >= AC["join"])
    for k, label in (("aggregate", "AC-05 聚合桶"), ("time_window", "AC-05 时间桶"), ("negation_null", "AC-05 空值桶")):
        if k in a["by_split"]:
            v = a["by_split"][k]["rate"]
            add(f"{label} EX", "≥80%", v, v >= AC["other"])
    add("反问率（主集，应接近 0）", "≤5%", a["clarification_rate"], (a["clarification_rate"] or 0) <= 0.05)
    add("AC-08 延迟 p50", "≤2000ms", a["latency_p50_ms"], (a["latency_p50_ms"] or 0) <= 2000, fmt="ms")
    add("AC-08 延迟 p95", "≤4000ms", a["latency_p95_ms"], (a["latency_p95_ms"] or 0) <= 4000, fmt="ms")

    fails = [x for x in rows if x["status"] == "FAIL"]
    if (a["executable_rate"] or 0) < 0.90:
        conclusion = f"INCOMPLETE —— 可执行率仅 {a['executable_rate']:.1%}，EX 不可读"
    elif fails:
        conclusion = "FAIL —— " + "、".join(x["metric"] for x in fails)
    else:
        conclusion = "PASS"
    return {"conclusion": conclusion, "rows": rows}


def to_md(a: dict, g: dict) -> str:
    lines = [
        f"# EX 评测报告 · {a['label']}",
        "",
        f"> 生成时间：{a['generated_at']}　题数：{a['n']}　判定：**EX 全自动（零 judge）**",
        "> 比对规则见 [docs/00-数据与口径.md](../docs/00-数据与口径.md) §5.2。",
        "",
        "## 一、门禁",
        "",
        f"**{g['conclusion']}**",
        "",
        "| 指标 | 阈值 | 实测 | 判定 |",
        "|---|---|---|---|",
    ]
    for r in g["rows"]:
        lines.append(f"| {r['metric']} | {r['threshold']} | {r['actual']} | {r['status']} |")
    lines += [
        "",
        f"- 通过 **{a['ex_n']}/{a['n']}**　可执行率 **{a['executable_rate']:.2%}**　平均尝试 **{a['attempts_mean']}** 次",
        f"- 延迟 p50/p95：**{a['latency_p50_ms']} / {a['latency_p95_ms']} ms**（AC-08 阈值 2000/4000）",
        "",
        "## 二、分桶",
        "",
        "| 分桶 | n | EX 命中 | 一致率 |",
        "|---|---|---|---|",
    ]
    for s, v in a["by_split"].items():
        lines.append(f"| {s} | {v['n']} | {v['ex']} | {v['rate']:.2%} |")
    lines += ["", "## 三、失败样本（前 40）", ""]
    for f in a["failures"]:
        lines.append(f"- `{f['qid']}` [{f['split']}] {f['reason']}")
        if f.get("out_sql"):
            lines.append(f"  - out: `{f['out_sql'][:180]}`")
        if f.get("gold_preview") is not None:
            lines.append(
                f"  - gold: `{json.dumps(f['gold_preview'], ensure_ascii=False)[:120]}` / out: `{json.dumps(f.get('out_preview'), ensure_ascii=False)[:120]}`"
            )
    lines += [
        "",
        "## 四、诚实边界",
        "",
        "- 主集问句由 LLM 从 gold SQL 反写，**与 SQL 结构同源**，真实自由提问会更难；锚点集用于校准这一偏差。",
        "- 延迟为单机单并发采样，受网关排队影响。",
        "- 未达标项一律保留 FAIL，未下调阈值。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--anchors", action="store_true")
    ap.add_argument("--ambiguity", action="store_true")
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    REPORTS.mkdir(parents=True, exist_ok=True)

    if args.ambiguity:
        rows = [json.loads(x) for x in AMBIG.read_text(encoding="utf-8").splitlines() if x.strip()]
        if args.limit:
            rows = rows[: args.limit]
        out, asked, correct = [], 0, 0
        for row in rows:
            r = ask(row["question"], clarify=True)
            clar = r["clarification"] or {}
            got = "blocking" if clar.get("blocking") else ("advisory" if clar else ("rejected" if r["rejected"] else "answered"))
            # 按 expected 判定：expected=correct 表示"应当指出歧义"（blocking 或 advisory 都算指出）
            expected = row.get("expected", "correct")
            ok = (expected == "correct" and got in ("blocking", "advisory")) or (expected == "partial" and got != "rejected") or (expected == "answered" and got == "answered")
            asked += 1 if got == "blocking" else 0
            correct += 1 if ok else 0
            out.append({"qid": row["qid"], "question": row["question"], "trigger": row["trigger"], "expected": expected, "got": got, "ok": ok})
            print(f"  {row['qid']} {got:9s} ok={ok} {row['question'][:36]}")
        rate = asked / len(rows) if rows else 0
        acc = correct / len(rows) if rows else 0
        payload = {"mode": "ambiguity", "n": len(rows), "clarify_rate": round(rate, 4), "expected_acc": round(acc, 4), "cases": out}
        (EVIDENCE / f"eval-ambiguity-{stamp}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n阻塞反问率 {rate:.2%}（AC-06 阈值 60%）｜按 expected 命中率 {acc:.2%}")
        return 0 if rate >= 0.6 else 2

    path = ANCHORS if args.anchors else GOLDEN
    label = "anchors" if args.anchors else "main"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if args.limit:
        rows = rows[: args.limit]
    print(f"[eval] {label} {len(rows)} 条")
    agg = evaluate(rows, label, stamp)
    g = gate(agg)
    agg["gate"] = g
    (EVIDENCE / f"eval-{label}-{stamp}.json").write_text(json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")
    md = to_md(agg, g)
    (REPORTS / f"EVAL-REPORT-{label}.md").write_text(md, encoding="utf-8")

    print("\n=== 门禁 ===")
    for r in g["rows"]:
        print(f"  {r['metric']:26s} {r['threshold']:8s} {r['actual']:>10s} {r['status']}")
    print(f"\n结论：{g['conclusion']}")
    # 验收模式：必须在完整集上运行，FAIL/INCOMPLETE 返回非零（codex 评审 #6）
    if args.limit:
        print("[提示] --limit 仅用于冒烟，不构成验收结论")
        return 0
    if label == "main":
        if g["conclusion"].startswith("PASS"):
            return 0
        return 2 if g["conclusion"].startswith("FAIL") else 3
    return 0 if g["conclusion"].startswith("PASS") else 2


if __name__ == "__main__":
    sys.exit(main())
