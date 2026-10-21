"""评测：规则命中集（810 单元）+ 报告质量集（30 份）+ 锚点集（20 条）。

用法：
    python -m eval.run_eval                      # 确定性 21 条（快，约 5 秒）
    python -m eval.run_eval --semantic           # 含语义 6 条（30 次 LLM 调用）
    python -m eval.run_eval --anchors            # 只跑锚点集
    python -m eval.run_eval --limit 3            # 冒烟
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import engine  # noqa: E402
from src.parse import parse_docx  # noqa: E402
from src.pipeline import review  # noqa: E402

UNITS = ROOT / "data" / "truth" / "units.jsonl"
MANIFEST = ROOT / "data" / "manifest.json"
ANCHORS = ROOT / "eval" / "anchors.jsonl"
REPORTS = ROOT / "eval" / "reports"
EVIDENCE = ROOT / "evidence"

CATS = ("存在型", "缺失型", "数值型", "语义型", "结构性")
AC = {"存在P": 0.85, "存在R": 0.88, "存在F1": 0.85, "缺失R": 0.85, "缺失FP": 0.15,
      "语义R": 0.70, "等级一致": 0.80, "定位率": 0.90, "报告结构": 1.0}


def pct(v: list[float], q: float):
    if not v:
        return None
    s = sorted(v)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = (2 * p * r / (p + r)) if p and r else None
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(p, 4) if p is not None else None,
            "recall": round(r, 4) if r is not None else None,
            "f1": round(f, 4) if f is not None else None}


def check_report_quality(report: dict, parsed: dict) -> tuple[bool, list[str]]:
    problems = []
    for k in ("contract_id", "summary", "findings", "coverage", "meta"):
        if k not in report:
            problems.append(f"缺字段 {k}")
    para_idx = {p["idx"] for p in parsed["paras"]}
    for f in report["findings"]:
        if f["level"] not in ("高", "中", "低", "无"):
            problems.append(f"{f['rule_id']} 等级非法 {f['level']}")
        loc = f.get("locator")
        if loc:
            if loc.get("para") not in para_idx:
                problems.append(f"{f['rule_id']} 定位段 {loc.get('para')} 不存在")
            if f["evidence"] and f["evidence"][:20] not in (loc.get("quote") or ""):
                problems.append(f"{f['rule_id']} 引用不在定位段内")
        if f["violated"] and f["level"] == "无":
            problems.append(f"{f['rule_id']} 判违规但等级为无")
    return (not problems), problems


def run_suite(with_semantic: bool, limit: int = 0) -> dict:
    rules = engine.load_rules()
    truth = [json.loads(x) for x in UNITS.read_text(encoding="utf-8").splitlines() if x.strip()]
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    contracts = man["detail"][: limit or None]

    per_rule = {f"R{i:02d}": {"tp": 0, "fp": 0, "fn": 0} for i in range(1, 28)}
    per_cat = {c: {"tp": 0, "fp": 0, "fn": 0} for c in CATS}
    level_ok = level_total = 0
    loc_ok = loc_total = 0            # 定位准确率：仅可定位项且非推断
    miss_cov_ok = miss_cov_total = 0  # 缺失项位置覆盖率（推断）
    any_loc_ok = any_loc_total = 0    # 旧口径（对照）
    latencies: list[float] = []
    struct_fail: list[str] = []
    missed: list[dict] = []
    false_pos: list[dict] = []

    truth_map = {(u["contract_id"], u["rule_id"]): u for u in truth}
    cat_of = {r["id"]: r["category"] for r in rules["rules"]}

    for c in contracts:
        path = ROOT / "data" / "contracts" / f"{c['contract_id']}.docx"
        rep = review(path, rules=rules, with_semantic=with_semantic)
        latencies.append(float(rep["meta"]["elapsed_ms"]))
        parsed = parse_docx(path)
        ok, probs = check_report_quality(rep, parsed)
        if not ok:
            struct_fail.append(f"{c['contract_id']}: {probs[:3]}")

        pred = {f["rule_id"]: f for f in rep["findings"]}
        for rid in cat_of:
            t = truth_map[(c["contract_id"], rid)]
            p = pred.get(rid)
            p_risk = bool(p and p["violated"])
            p_level = p["level"] if p else "无"
            cat = cat_of[rid]
            if not with_semantic and cat == "语义型":
                continue  # 未执行的规则不进入分母（否则必然 0 召回）
            if t["risk"] and p_risk:
                per_rule[rid]["tp"] += 1
                per_cat[cat]["tp"] += 1
                level_total += 1
                level_ok += 1 if p_level == t["level"] else 0
                # 旧口径（对照）：全部 TP 中"有任意定位依据"的比例
                any_loc_total += 1
                if p and (p.get("locator") or p.get("evidence")):
                    any_loc_ok += 1

                locobj = (p or {}).get("locator") or {}
                if cat in ("数值型", "结构性", "语义型"):
                    # 可定位项：必须是真实（非推断）locator，evidence 不算定位
                    loc_total += 1
                    if locobj and not locobj.get("inferred"):
                        loc_ok += 1
                else:
                    # 缺失/存在型缺失：只看能否给出"应出现位置"（推断）
                    miss_cov_total += 1
                    if locobj.get("inferred"):
                        miss_cov_ok += 1
            else:
                if t["risk"]:
                    per_rule[rid]["fn"] += 1
                    per_cat[cat]["fn"] += 1
                    missed.append({"contract": c["contract_id"], "rule": rid, "truth_level": t["level"],
                                   "why": (p or {}).get("reason", "未报告")[:60]})
                if p_risk:
                    per_rule[rid]["fp"] += 1
                    per_cat[cat]["fp"] += 1
                    false_pos.append({"contract": c["contract_id"], "rule": rid,
                                      "evidence": (p or {}).get("evidence", "")[:40]})

    total = {"tp": 0, "fp": 0, "fn": 0}
    for rid, v in per_rule.items():
        for k in total:
            total[k] += v[k]
    by_cat = {c: prf(**per_cat[c]) for c in CATS}
    cat_totals: dict[str, int] = {c: 0 for c in CATS}
    for c in contracts:
        for rid in cat_of:
            cat_totals[cat_of[rid]] += 1
    for c in CATS:
        m = by_cat[c]
        tn = cat_totals[c] - m["tp"] - m["fp"] - m["fn"]
        m["n"] = cat_totals[c]
        m["fp_rate"] = round(m["fp"] / (m["fp"] + tn), 4) if (m["fp"] + tn) else None
    weak_rules = sorted(
        [(rid, prf(**v)) for rid, v in per_rule.items() if v["tp"] + v["fn"] > 0],
        key=lambda x: (x[1]["recall"] if x[1]["recall"] is not None else 9),
    )[:6]

    return {
        "mode": "semantic" if with_semantic else "deterministic",
        "n_contracts": len(contracts),
        "units": len(contracts) * 27,
        "overall": prf(**total),
        "by_category": by_cat,
        "level_agreement": round(level_ok / level_total, 4) if level_total else None,
        "locator_rate": round(loc_ok / loc_total, 4) if loc_total else None,
        "locator_n": loc_total,
        "missing_cov_rate": round(miss_cov_ok / miss_cov_total, 4) if miss_cov_total else None,
        "missing_cov_n": miss_cov_total,
        "locator_rate_legacy": round(any_loc_ok / any_loc_total, 4) if any_loc_total else None,
        "report_structure_pass": round(1 - len(struct_fail) / len(contracts), 4) if contracts else None,
        "structure_failures": struct_fail[:5],
        "weak_rules": [{"rule": r, **m} for r, m in weak_rules],
        "latency_p50_ms": pct(latencies, 0.5),
        "latency_p95_ms": pct(latencies, 0.95),
        "missed": missed[:20],
        "false_pos": false_pos[:20],
    }


def gate(agg: dict) -> dict:
    rows = []
    def add(name, thr, val, ok, fmt="pct"):
        shown = "—" if val is None else (f"{val:.2%}" if fmt == "pct" else f"{val:.1f}ms")
        rows.append({"metric": name, "threshold": thr, "actual": shown,
                     "status": "SKIP" if val is None else ("PASS" if ok else "FAIL")})

    c = agg["by_category"]
    ex = c.get("存在型", {})
    add("存在型 Precision", "≥85%", ex.get("precision"), (ex.get("precision") or 0) >= AC["存在P"])
    add("存在型 Recall", "≥88%", ex.get("recall"), (ex.get("recall") or 0) >= AC["存在R"])
    add("存在型 F1", "≥85%", ex.get("f1"), (ex.get("f1") or 0) >= AC["存在F1"])
    miss = c.get("缺失型", {})
    add("缺失型 Recall", "≥85%", miss.get("recall"), (miss.get("recall") or 0) >= AC["缺失R"])
    add("缺失型误报率", "≤15%", miss.get("fp_rate"), (miss.get("fp_rate") or 0) <= AC["缺失FP"])
    sem = c.get("语义型", {})
    add("语义型 Recall", "≥70%", sem.get("recall"), (sem.get("recall") or 0) >= AC["语义R"])
    add("等级一致率", "≥80%", agg["level_agreement"], (agg["level_agreement"] or 0) >= AC["等级一致"])
    add("定位准确率（可定位项）", "≥90%", agg["locator_rate"], (agg["locator_rate"] or 0) >= AC["定位率"])
    add("缺失项位置覆盖率（推断）", "≥80%", agg["missing_cov_rate"], (agg["missing_cov_rate"] or 0) >= 0.80)
    add("报告结构通过率", "100%", agg["report_structure_pass"], (agg["report_structure_pass"] or 0) >= AC["报告结构"])

    fails = [r for r in rows if r["status"] == "FAIL"]
    conclusion = "FAIL —— " + "、".join(r["metric"] for r in fails) if fails else "PASS"
    return {"conclusion": conclusion, "rows": rows}


def to_md(agg: dict, g: dict) -> str:
    lines = [f"# 合同审查评测报告（{agg['mode']}）", "",
             f"> 合同 {agg['n_contracts']} 份 / 判定单元 {agg['units']} / 规则 27 条",
             "> 判定单元口径：规则×合同；真值由生成器植入计划直接产出（非事后标注）。", "",
             "## 一、门禁", "", f"**{g['conclusion']}**", "",
             "| 指标 | 阈值 | 实测 | 判定 |", "|---|---|---|---|"]
    for r in g["rows"]:
        lines.append(f"| {r['metric']} | {r['threshold']} | {r['actual']} | {r['status']} |")
    o = agg["overall"]
    lines += ["", "## 二、总体与分类型", "",
              f"- 总体：P {o['precision']:.2%} / R {o['recall']:.2%} / F1 {o['f1']:.2%}（TP {o['tp']} / FP {o['fp']} / FN {o['fn']}）"
              if o["precision"] is not None else "- 总体：—", "",
              "| 类别 | TP | FP | FN | Precision | Recall | F1 |", "|---|---|---|---|---|---|---|"]
    for cat, m in agg["by_category"].items():
        fmt = lambda v: f"{v:.2%}" if v is not None else "—"
        lines.append(f"| {cat} | {m['tp']} | {m['fp']} | {m['fn']} | {fmt(m['precision'])} | {fmt(m['recall'])} | {fmt(m['f1'])} |")
    lines += ["", f"- 等级一致率：{agg['level_agreement']:.2%}" if agg["level_agreement"] is not None else "- 等级一致率：—",
              (f"- **定位准确率（可定位项，n={agg['locator_n']}）**：{agg['locator_rate']:.2%}"
               if agg["locator_rate"] is not None else "- 定位准确率：—"),
              (f"- **缺失项位置覆盖率（推断，n={agg['missing_cov_n']}）**：{agg['missing_cov_rate']:.2%}"
               if agg["missing_cov_rate"] is not None else "- 缺失项位置覆盖率：—"),
              (f"- 旧口径定位率（含缺失项，仅供对照）：{agg['locator_rate_legacy']:.2%}"
               if agg["locator_rate_legacy"] is not None else "- 旧口径：—"),
              f"- 报告结构通过率：{agg['report_structure_pass']:.2%}" if agg["report_structure_pass"] is not None else "- 报告结构：—",
              f"- 单份耗时 p50/p95：{agg['latency_p50_ms']} / {agg['latency_p95_ms']} ms", "",
              "## 三、最弱规则（按召回升序）", ""]
    for w in agg["weak_rules"]:
        fmt = lambda v: f"{v:.0%}" if v is not None else "—"
        lines.append(f"- {w['rule']}：R { fmt(w['recall'])} / P {fmt(w['precision'])}（TP {w['tp']} FP {w['fp']} FN {w['fn']}）")
    lines += ["", "## 四、漏报与误报样例", ""]
    for m in agg["missed"][:8]:
        lines.append(f"- 漏报 {m['contract']} {m['rule']}（真值 {m['truth_level']}）：{m['why']}")
    for f in agg["false_pos"][:8]:
        lines.append(f"- 误报 {f['contract']} {f['rule']}：{f['evidence']}")
    lines += ["", "## 五、诚实边界", "",
              "- 数据为合成合同，缺陷由生成器植入；真值 100% 有据，但**覆盖面受合成模板限制**。",
              "- `not_detected` 表示未取得判定依据，**不等于合规**。",
              "- 语义型依赖 LLM，本轮未做双判官；锚点集为「真值 + 原文核验」，非纯人工独立标注。",
              "- v1 仅支持 .docx，PDF/扫描件不支持。", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--semantic", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--anchors", action="store_true")
    args = ap.parse_args()
    REPORTS.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(exist_ok=True)

    if args.anchors:
        return run_anchors()

    agg = run_suite(args.semantic, args.limit)
    g = gate(agg)
    agg["gate"] = g
    tag = "semantic" if args.semantic else "deterministic"
    (EVIDENCE / f"eval-{tag}.json").write_text(json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")
    md = to_md(agg, g)
    (REPORTS / f"EVAL-REPORT-{tag}.md").write_text(md, encoding="utf-8")
    print("\n=== 门禁 ===")
    for r in g["rows"]:
        print(f"  {r['metric']:22s} {r['threshold']:7s} {r['actual']:>10s} {r['status']}")
    print(f"\n总体 P/R/F1: {agg['overall']}")
    print(f"结论：{g['conclusion']}")
    if args.limit:
        return 0
    return 0 if g["conclusion"].startswith("PASS") else 2


def run_anchors() -> int:
    """锚点集：20 条「真值 + 原文核验」，检查系统判定是否一致。"""
    rows = [json.loads(x) for x in ANCHORS.read_text(encoding="utf-8").splitlines() if x.strip()]
    rules = engine.load_rules()
    cache: dict[str, dict] = {}
    ok = 0
    out = []
    for r in rows:
        cid = r["contract_id"]
        if cid not in cache:
            cache[cid] = review(ROOT / "data" / "contracts" / f"{cid}.docx", rules=rules, with_semantic=True)
        pred = {f["rule_id"]: f for f in cache[cid]["findings"]}
        got_risk = bool((pred.get(r["rule_id"]) or {}).get("violated"))
        hit = got_risk == bool(r["risk"])
        ok += 1 if hit else 0
        out.append({"contract_id": cid, "rule_id": r["rule_id"], "expected": r["risk"], "got": got_risk, "hit": hit,
                    "note": r.get("note", "")})
        print(f"  {cid} {r['rule_id']} expect={r['risk']} got={got_risk} {'OK' if hit else 'MISS'}")
    acc = ok / len(rows) if rows else 0
    payload = {"mode": "anchors", "n": len(rows), "accuracy": round(acc, 4), "cases": out}
    (EVIDENCE / "eval-anchors.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n锚点一致率 {acc:.2%}（阈值 85%）→ {'PASS' if acc >= 0.85 else 'FAIL'}")
    return 0 if acc >= 0.85 else 2


if __name__ == "__main__":
    sys.exit(main())
