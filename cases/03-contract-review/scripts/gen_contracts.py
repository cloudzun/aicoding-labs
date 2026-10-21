"""确定性生成 30 份合成合同（docx）+ 810 个判定单元的真值标注。

设计：
- 3 类 × 10 份：采购合同 / 服务合同 / 框架协议
- 6 份正常（对照），24 份各植入 2–5 处缺陷（12 类）
- **真值由生成器按植入计划直接产出**（不是事后标注），因此 810 单元标注 100% 有据

用法：python -m scripts.gen_contracts
产出：data/contracts/*.docx、data/truth/units.jsonl、data/manifest.json
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import date, timedelta
from pathlib import Path

from docx import Document
from docx.shared import Pt

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "contracts"
TRUTH = ROOT / "data" / "truth" / "units.jsonl"
MANIFEST = ROOT / "data" / "manifest.json"

SEED = 20261020
rng = random.Random(SEED)

PARTY_A = ["明州数智服务有限公司", "明州数智服务有限公司杭州分公司"]
PARTY_B = ["华瑞信息技术有限公司", "恒通智联科技有限公司", "启明数据服务有限公司", "蓝海智联科技有限公司"]
CITIES = ["杭州市", "宁波市", "温州市"]
TYPES = [("采购合同", 10), ("服务合同", 10), ("框架协议", 10)]

# 缺陷 → 规则映射（12 类植入缺陷）
DEFECT_RULES = {
    "D01": ["R01"], "D02": ["R14"], "D03": ["R15"], "D04": ["R20"], "D05": ["R21"],
    "D06": ["R22"], "D07": ["R23"], "D08": ["R24"], "D09": ["R02"], "D10": ["R03"],
    "D11": ["R04"], "D12": ["R26", "R27"], "D13": ["R25"],
}
# 扩展缺陷池：保证 27 条规则每条至少被违反一次（否则该规则无区分度）
DEFECT_POOL = [
    "D01", "D04", "D05", "D06", "D07", "D08", "D09", "D10", "D11", "D12", "D13",
    "假R14", "假R15", "假R16", "假R17", "假R18", "假R19",
    "缺R05", "缺R06", "缺R07", "缺R08", "缺R09", "缺R10", "缺R11", "缺R12", "缺R13",
]
SEMANTIC_RULES = {"R20", "R21", "R22", "R23", "R24", "R25"}

# 每条规则对应的"正常条款文本"（缺失类缺陷即删除该条）
CLAUSE_TEXT = {
    "R01": "第八条 保密\n双方对因履行本合同知悉的对方商业秘密承担保密义务，保密期限为合同终止后三年。",
    "R02": "第九条 发票与税率\n乙方应开具税率为6%的增值税专用发票，甲方收到发票后付款。",
    "R03": "第十条 服务标准\n乙方承诺故障响应时间不超过4小时，服务标准详见附件SLA。",
    "R04": "第十一条 数据与个人信息\n乙方处理甲方数据应遵守数据安全要求，涉及个人信息的应取得合法授权，合同终止后删除。",
    "R05": "第十二条 争议解决\n因本合同发生争议，双方应协商解决；协商不成的，提交甲方所在地人民法院诉讼解决。",
    "R06": "第十三条 不可抗力\n因不可抗力导致不能履行的，遭遇方应在15日内通知对方并提供证明，可部分或全部免责。",
    "R07": "第十四条 验收标准\n交付物按附件验收标准验收，甲方应在10个工作日内完成验收，不通过的一次性书面说明。",
    "R08": "第十五条 合同转让\n未经对方书面同意，任何一方不得转让本合同项下的权利义务。",
    "R09": "第二条 合同期限\n本合同有效期自生效之日起十二个月。",
    "R10": "第六条 付款方式\n甲方按进度分两期付款，验收合格后支付尾款。",
    "R11": "第七条 违约责任\n任何一方违约的，应赔偿对方因此遭受的直接损失。",
    "R12": "第十六条 知识产权\n乙方交付成果的知识产权归甲方所有，乙方保留通用组件的使用权。",
    "R13": "第十七条 签署与盖章\n本合同一式肆份，双方签字并加盖公章后生效。",
    "R20": "第十八条 合同解除\n任何一方提前三十日书面通知即可解除本合同，无需承担赔偿责任。",  # 缺陷版本
    "R21": "第十九条 续期\n本合同期满后自动续期一年。",                                # 缺陷版本
    "R22": "第七条 赔偿责任\n乙方违约应赔偿甲方全部损失，包括间接损失。",              # 缺陷版本（无限责任）
    "R23": "第十二条 管辖\n争议提交乙方所在地人民法院诉讼解决。",                      # 缺陷版本
    "R24": "第十六条 成果归属\n成果归属双方另行协商确定。",                            # 缺陷版本（模糊）
    "R25": "第二十条 对等责任\n甲方逾期付款的，应按日千分之一向乙方支付违约金；乙方逾期交付的，不承担责任。",  # 缺陷版本（不对等）
}

# 语义规则的**正常版**文本（未植入缺陷时必须用它，否则每份合同都自带缺陷 ← 本轮致命 bug）
NORMAL_SEM = {
    "R20": "第十八条 合同解除\n一方严重违约且经催告三十日仍未纠正的，对方有权解除本合同。",
    "R21": "第十九条 续期\n本合同期满前六十日双方书面确认是否续期，未确认的到期终止。",
    "R22": "第七条 赔偿责任\n任何一方违约应赔偿对方直接损失，赔偿总额不超过合同总额的100%。",
    "R23": "第十二条 管辖\n争议提交甲方所在地人民法院诉讼解决。",
    "R24": "第十六条 成果归属\n乙方交付成果的所有权归甲方所有，乙方保留通用组件的使用权。",
    "R25": "第二十条 对等责任\n双方违约责任对等，逾期均按合同总额的0.5‰/日计违约金。",
}

# 数值型：正常值 / 缺陷值
NUMERIC = {
    "R14": ("违约金按合同总额的0.5‰/日计算。", "违约金按合同总额的0.1‰/日计算。"),
    "R15": ("甲方应在验收后30日内付款。", "甲方应在验收后90日内付款。"),
    "R16": ("质保期为24个月。", "质保期为6个月。"),
    "R17": ("变更通知应提前20日送达。", "变更通知应提前3日送达。"),
    "R18": ("预付款比例为20%。", "预付款比例为50%。"),
    "R19": ("赔偿总额不超过合同总额的100%。", "赔偿总额不超过合同总额的30%。"),
}


def _para(doc, text: str, size: int = 10, bold: bool = False) -> int:
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.bold = bold
    return len(doc.paragraphs) - 1


def build_contract(cid: str, ctype: str, defects: list[str], idx: int) -> tuple[Path, list[dict]]:
    doc = Document()
    party_a = PARTY_A[idx % len(PARTY_A)]
    party_b = PARTY_B[idx % len(PARTY_B)]
    city = CITIES[idx % len(CITIES)]
    amount = round(rng.uniform(80, 900), 2)
    sign = date(2026, rng.randrange(1, 10), rng.randrange(1, 28))
    unit_rows: list[dict] = []

    def add(rule_id: str, text: str, present: bool = True) -> dict:
        pidx = _para(doc, text) if present else None
        unit_rows.append(
            {"rule_id": rule_id, "present": present, "para": pidx,
             "text": text[:120] if present else "", "defect": None}
        )
        return unit_rows[-1]

    _para(doc, f"{ctype}", size=16, bold=True)
    _para(doc, f"合同编号：{cid}", size=9)
    _para(doc, f"甲方：{party_a}\n地址：{city}某某路18号\n联系人：张经理")
    if "D12" in defects:
        # D12：主体信息缺失 + 签署日期与生效日期不一致
        pidx = len(doc.paragraphs) - 1
        doc.paragraphs[pidx].text = f"甲方：{party_a}"
        unit_rows.append({"rule_id": "R26", "present": False, "para": pidx, "text": "", "defect": "D12"})
    else:
        unit_rows.append({"rule_id": "R26", "present": True, "para": len(doc.paragraphs) - 1, "text": "", "defect": None})
    _para(doc, f"乙方：{party_b}")
    _para(doc, f"第一条 标的\n甲方向乙方采购/委托{ctype[:2]}相关产品与服务，合同总额人民币{amount}万元。")

    # 期限 / 付款 / 违约 / 知识产权 / 签署（存在型 + 缺失型）
    # D06/D07/D08 会把对应主题的条款改写成缺陷版，此时不要再写正常条款（否则全文矛盾）
    replaced_by_defect = {"R11": "D06", "R12": "D08"}
    for rid in ("R09", "R10", "R11", "R12", "R13"):
        if f"缺{rid}" in defects or replaced_by_defect.get(rid) in defects:
            add(rid, "", present=False)
        else:
            add(rid, CLAUSE_TEXT[rid])

    # 存在型 8 条中，D01/D09/D10/D11 会删除对应条款
    skip = {"D01": "R01", "D09": "R02", "D10": "R03", "D11": "R04"}
    for d, rid in skip.items():
        if d in defects:
            add(rid, "", present=False)
        else:
            add(rid, CLAUSE_TEXT[rid])
    for rid in ("R05", "R06", "R07", "R08"):
        if f"缺{rid}" in defects or (rid == "R05" and "D07" in defects):
            add(rid, "", present=False)
        else:
            add(rid, CLAUSE_TEXT[rid])

    # 数值型：以段落形式插入正文
    num_parts = []
    for rid in NUMERIC:
        if rid == "R19" and "D06" in defects:
            num_parts.append("赔偿总额按实际损失确定。")  # 与"无限责任"一致，避免自相矛盾
        else:
            num_parts.append(NUMERIC[rid][1] if f"假{rid}" in defects else NUMERIC[rid][0])
    num_para = "第五条 履约要求\n" + " ".join(num_parts)
    add("R14", num_para)  # 数值型统一挂一个段落（规则引擎按正则全文抽取）

    # 语义型：缺陷版本替换正常表述
    sem_map = {"D04": "R20", "D05": "R21", "D06": "R22", "D07": "R23", "D08": "R24", "D13": "R25"}
    for d, rid in sem_map.items():
        add(rid, CLAUSE_TEXT[rid] if d in defects else NORMAL_SEM[rid])

    # 签署页
    if "D12" in defects:
        _para(doc, "签署日期：2026-09-30　　生效日期：2026-01-01")
        unit_rows.append({"rule_id": "R27", "present": False, "para": len(doc.paragraphs) - 1, "text": "", "defect": "D12"})
    else:
        _para(doc, f"签署日期：{sign.isoformat()}　　生效日期：{sign.isoformat()}")
        unit_rows.append({"rule_id": "R27", "present": True, "para": len(doc.paragraphs) - 1, "text": "", "defect": None})

    # 补 R25（语义型，正常/缺陷由 LLM 判；这里只登记存在）
    unit_rows.append({"rule_id": "R25", "present": True, "para": None, "text": "", "defect": None})

    path = OUT_DIR / f"{cid}.docx"
    doc.save(path)
    return path, unit_rows


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TRUTH.parent.mkdir(parents=True, exist_ok=True)
    contracts = []
    units: list[dict] = []
    all_rules = [f"R{i:02d}" for i in range(1, 28)]

    idx = 0
    for ctype, n in TYPES:
        for k in range(n):
            idx += 1
            cid = f"CT{idx:03d}"
            defects: list[str] = []
            if k >= 2:  # 前 2 份正常，其余植入 3–6 处（从扩展池抽样）
                defects.extend(rng.sample(DEFECT_POOL, rng.randrange(3, 7)))
                # 冲突消解：语义缺陷条款本身会提供该条款（如 R22 文本即『违约责任』），
                # 因此不能同时声明该条款缺失，否则真值自相矛盾（实测 recall 被压到 50%）
                for sem, missing in (("D06", "缺R11"), ("D07", "缺R05"), ("D08", "缺R12")):
                    if sem in defects and missing in defects:
                        defects.remove(missing)
            path, rows = build_contract(cid, ctype, defects, idx)

            violated: set[str] = set()
            # 缺陷替换了正常条款 → 该条款视为缺失（与 truth 的 present=False 一致）
            for sem, miss in (("D06", "R11"), ("D07", "R05"), ("D08", "R12")):
                if sem in defects:
                    violated.add(miss)
            for d in defects:
                if d.startswith("假"):
                    violated.add(d[1:])
                elif d.startswith("缺"):
                    violated.add(d[1:])
                else:
                    violated.update(DEFECT_RULES.get(d, []))

            for rid in all_rules:
                got = next((r for r in rows if r["rule_id"] == rid), None)
                present = bool(got and got["present"]) if got else True
                risk = rid in violated or not present
                HIGH_SET = {"R01", "R03", "R04", "R05", "R09", "R10", "R11", "R12", "R14", "R19", "R20", "R22", "R24", "R26"}
                MID_SET = {"R02", "R07", "R13", "R15", "R16", "R18", "R21", "R23", "R25"}
                # 保持优先级：先判 risk，再判严重度（原写法 risk=false 时高严重度仍写"高"，属实值 bug）
                level = ("高" if rid in HIGH_SET else ("中" if rid in MID_SET else "低")) if risk else "无"
                units.append(
                    {
                        "contract_id": cid,
                        "contract_type": ctype,
                        "rule_id": rid,
                        "present": present,
                        "risk": risk,
                        "level": level,
                        "defect_code": next((d for d in defects if rid in DEFECT_RULES.get(d, []) or d in (f"假{rid}", f"缺{rid}")), None),
                        "evidence_expected": (got or {}).get("text", "")[:80],
                    }
                )
            contracts.append(
                {"contract_id": cid, "type": ctype, "defects": defects, "violated_rules": sorted(violated),
                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest()[:16], "paras": len(Document(str(path)).paragraphs)}
            )

    TRUTH.write_text("\n".join(json.dumps(u, ensure_ascii=False) for u in units) + "\n", encoding="utf-8")
    MANIFEST.write_text(
        json.dumps(
            {"seed": SEED, "contracts": len(contracts), "units": len(units),
             "defective": sum(1 for c in contracts if c["defects"]),
             "detail": contracts},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[done] {len(contracts)} 份合同 → {OUT_DIR}")
    print(f"[done] 判定单元 {len(units)} 条（{len(contracts)}×27）→ {TRUTH}")
    print(f"  有缺陷合同 {sum(1 for c in contracts if c['defects'])} / 正常 {sum(1 for c in contracts if not c['defects'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
