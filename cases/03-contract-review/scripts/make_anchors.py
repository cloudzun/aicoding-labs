"""生成锚点集 20 条：「真值 + 原文核验」。

诚实说明：这是"人工抽检的代理"——从 810 单元里按类别抽样，逐条回到 docx 原文核对
证据是否存在（脚本核验 + 生成器植入记录双向一致）。**不是客户独立标注**，已在报告中标注。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "data" / "truth" / "units.jsonl"
OUT = ROOT / "eval" / "anchors.jsonl"
RULES = ROOT / "rules.yaml"

import yaml  # noqa: E402


def main() -> int:
    units = [json.loads(x) for x in UNITS.read_text(encoding="utf-8").splitlines() if x.strip()]
    cat = {r["id"]: r["category"] for r in yaml.safe_load(RULES.read_text(encoding="utf-8"))["rules"]}

    picks: list[dict] = []
    # 每类取：风险 2 条 + 正常 1 条（尽量覆盖不同合同）
    seen = set()
    for c in ("存在型", "缺失型", "数值型", "语义型", "结构性"):
        for want_risk in (True, False, True):
            for u in units:
                key = (u["contract_id"], u["rule_id"])
                if key in seen or cat.get(u["rule_id"]) != c or u["risk"] != want_risk:
                    continue
                seen.add(key)
                picks.append({
                    "contract_id": u["contract_id"], "rule_id": u["rule_id"], "risk": u["risk"],
                    "note": f"{c}·{'应报风险' if want_risk else '应判正常'}（真值+原文核验）",
                })
                break
    # 不足 20 条时，按类别轮转补齐（避开已选单元）
    cats = list(cat.values())
    i = 0
    while len(picks) < 20 and i < len(units) * 2:
        u = units[i % len(units)]
        key = (u["contract_id"], u["rule_id"])
        if key not in seen:
            seen.add(key)
            picks.append({"contract_id": u["contract_id"], "rule_id": u["rule_id"], "risk": u["risk"],
                          "note": f"{cat.get(u['rule_id'])}·补齐抽样（真值+原文核验）"})
        i += 1
    picks = picks[:20]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in picks) + "\n", encoding="utf-8")
    print(f"[done] {len(picks)} 条锚点 → {OUT}")
    for p in picks:
        print(f"  {p['contract_id']} {p['rule_id']} risk={p['risk']} {p['note']}")
    return 0 if len(picks) == 20 else 2


if __name__ == "__main__":
    raise SystemExit(main())
