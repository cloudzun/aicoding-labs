"""只读诊断（不改任何逻辑）：缺失型 FN 分类 + 定位可用性分解。

用法：
    python -m scripts.diag_metrics              # 确定性全量（秒级）
    python -m scripts.diag_metrics --semantic 6 # 语义子集（6 份，约 3 分钟）
输出：evidence/diag-<mode>.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import engine  # noqa: E402
from src.parse import parse_docx  # noqa: E402
from src.pipeline import review  # noqa: E402

UNITS = ROOT / "data" / "truth" / "units.jsonl"
HEAD_RE = re.compile(r"^第[一二三四五六七八九十百]+条\s*(.{0,20})")


def headings(parsed: dict) -> list[str]:
    out = []
    for p in parsed["paras"]:
        m = HEAD_RE.match(p["text"])
        if m:
            out.append(p["text"][:24].replace("\n", " "))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--semantic", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rules = engine.load_rules()
    cat_of = {r["id"]: r["category"] for r in rules["rules"]}
    head_of = {r["id"]: r.get("heading", "") for r in rules["rules"]}
    truth = [json.loads(x) for x in UNITS.read_text(encoding="utf-8").splitlines() if x.strip()]
    man = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))["detail"]
    ids = [c["contract_id"] for c in man]
    if args.limit:
        ids = ids[: args.limit]

    sem_ids = set()
    if args.semantic:
        # 优先挑「语义型有真值风险」的合同
        risk_sem = defaultdict(int)
        for u in truth:
            if cat_of.get(u["rule_id"]) == "语义型" and u["risk"]:
                risk_sem[u["contract_id"]] += 1
        sem_ids = set(sorted(risk_sem, key=lambda k: -risk_sem[k])[: args.semantic])
        print(f"[info] 语义子集：{sorted(sem_ids)}")

    tmap = {(u["contract_id"], u["rule_id"]): u for u in truth}
    fn_missing: list[dict] = []
    loc = defaultdict(Counter)          # (mode, category) -> {locator, evidence_only, none}
    tp_by_cat = Counter()
    downgraded: list[dict] = []

    for cid in ids:
        path = ROOT / "data" / "contracts" / f"{cid}.docx"
        with_sem = cid in sem_ids
        rep = review(path, rules=rules, with_semantic=with_sem)
        parsed = parse_docx(path)
        heads = headings(parsed)
        pred = {f["rule_id"]: f for f in rep["findings"]}

        for rid, cat in cat_of.items():
            if cat == "语义型" and not with_sem:
                continue
            t = tmap[(cid, rid)]
            p = pred.get(rid)
            p_risk = bool(p and p["violated"])
            if t["risk"] and not p_risk:
                if cat == "缺失型":
                    fn_missing.append({"contract": cid, "rule": rid, "expected_heading": head_of[rid],
                                       "present_in_truth": t["present"], "defect": t.get("defect_code"),
                                       "reason": (p or {}).get("reason", "未报告")[:60],
                                       "headings": heads})
                # 语义型：判违规但被降级
                if cat == "语义型" and p and "降级" in (p.get("reason") or ""):
                    downgraded.append({"contract": cid, "rule": rid, "reason": p["reason"][:80],
                                       "evidence": (p.get("evidence") or "")[:60]})
            if t["risk"] and p_risk:
                tp_by_cat[cat] += 1
                mode = "semantic" if (p or {}).get("detector") == "llm" else "deterministic"
                has_loc = bool(p.get("locator"))
                has_ev = bool(p.get("evidence"))
                loc[(mode, cat)]["locator" if has_loc else ("evidence_only" if has_ev else "none")] += 1

    # 汇总
    print("\n=== A. 缺失型 FN 明细（每条附该合同的实际条款标题）===")
    for f in fn_missing:
        print(f"{f['contract']} {f['rule']} 期望标题『{f['expected_heading']}』 truth_present={f['present_in_truth']} defect={f['defect']}")
        print(f"   检测理由：{f['reason']}")
        print(f"   实际标题：{f['headings']}")
    kinds = Counter()
    for f in fn_missing:
        hit = [h for h in f["headings"] if f["expected_heading"] and f["expected_heading"] in h]
        kinds["B 同词在其它标题" if hit else "A 标题写法差异/无对应"] += 1
    print(f"\nFN 分类（启发式）：{dict(kinds)}  共 {len(fn_missing)} 条")

    print("\n=== B. 定位可用性分解（TP 口径）===")
    for key in sorted(loc):
        print(f"{key[0]:14s} {key[1]:6s} {dict(loc[key])}")
    # 可定位项定位率：排除缺失型与"存在型缺失"（本来没有位置）
    num = sum(v["locator"] for (m, c), v in loc.items() if c not in ("缺失型",))
    den = sum(sum(v.values()) for (m, c), v in loc.items() if c not in ("缺失型",))
    print(f"\n含缺失/存在型的原口径分母 = {sum(sum(v.values()) for v in loc.values())}")
    print(f"可定位项定位率 = {num}/{den} = {num/den:.2%}" if den else "无可定位项")
    print(f"\n语义降级（判违规但证据定位失败）样本 {len(downgraded)}：")
    for d in downgraded[:5]:
        print(f"  {d['contract']} {d['rule']} {d['reason']} | ev={d['evidence']}")

    out = {"mode": "semantic-subset" if args.semantic else "deterministic",
           "fn_missing": fn_missing, "fn_kinds": dict(kinds),
           "locator": {f"{m}|{c}": dict(v) for (m, c), v in loc.items()},
           "locatable_rate": round(num / den, 4) if den else None,
           "downgraded": downgraded}
    p = ROOT / "evidence" / f"diag-{out['mode']}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[evidence] {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
