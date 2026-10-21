"""数据断言：30 份合同 / 810 单元 / 缺陷分布 / 正常合同零风险（复用 BP-3 题库不变量思路）。

用法：python -m scripts.verify_data
"""

from __future__ import annotations
import sys as _sys

# 干净 Windows 的默认代码页可能不是 UTF-8；中文 print 会抛 UnicodeEncodeError。
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "data" / "truth" / "units.jsonl"
MANIFEST = ROOT / "data" / "manifest.json"
DOCX = ROOT / "data" / "contracts"

CHECKS: list[tuple[str, bool, str]] = []


def chk(name: str, ok: bool, detail: str) -> None:
    CHECKS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name:34s} {detail}")


def main() -> int:
    units = [json.loads(x) for x in UNITS.read_text(encoding="utf-8").splitlines() if x.strip()]
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))

    chk("合同数=30", len(man["detail"]) == 30, f"{len(man['detail'])}")
    chk("docx 文件数=30", len(list(DOCX.glob('*.docx'))) == 30, f"{len(list(DOCX.glob('*.docx')))}")
    chk("判定单元=810（30×27）", len(units) == 810, f"{len(units)}")
    chk("每份合同 27 单元", all(v == 27 for v in Counter(u["contract_id"] for u in units).values()), "27×30")

    normal = [c["contract_id"] for c in man["detail"] if not c["defects"]]
    chk("正常合同=6", len(normal) == 6, f"{normal[:3]}…")
    bad_normal = [u["contract_id"] for u in units if u["contract_id"] in normal and u["risk"]]
    chk("正常合同零风险单元", not bad_normal, f"{len(bad_normal)}")

    defective = [c for c in man["detail"] if c["defects"]]
    chk("有缺陷合同=24", len(defective) == 24, f"{len(defective)}")
    truth_units = [u for u in units if u["risk"]]
    REPLACED = {"R05", "R11", "R12"}  # 被 D07/D06/D08 的缺陷文本替换掉的条款
    unexplained = [u for u in truth_units if not u.get("defect_code") and u["rule_id"] not in REPLACED]
    chk("每个风险单元可解释", not unexplained,
        f"truth_risk={len(truth_units)} 无解释={len(unexplained)} {[ (u['contract_id'], u['rule_id']) for u in unexplained][:4]}")

    # 每条规则至少被违反 1 次（否则该规则无区分度）
    per_rule = Counter(u["rule_id"] for u in units if u["risk"])
    missing = [f"R{i:02d}" for i in range(1, 28) if per_rule.get(f"R{i:02d}", 0) == 0]
    chk("每条规则至少违反 1 次", not missing, f"未覆盖={missing}")

    # 缺陷码与规则的对应
    codes = Counter(u["defect_code"] for u in units if u["defect_code"])
    chk("缺陷码种类≥10", len(codes) >= 10, f"{sorted(codes)[:12]}")

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    out = ROOT / "evidence" / "data-verify.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"passed": passed, "total": len(CHECKS),
                               "checks": [{"check": n, "pass": o, "detail": d} for n, o, d in CHECKS]},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{passed}/{len(CHECKS)} 通过 → {out}")
    return 0 if passed == len(CHECKS) else 2


if __name__ == "__main__":
    sys.exit(main())
