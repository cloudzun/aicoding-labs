"""生成 golden_set_v2：为每题抽 1–4 条「最小事实点」（SPEC v0.2 / C-1）。

- 单跳/多跳/无关题：LLM 从 gold_answer 抽取
- 冲突/时效 8 条：**人工手写**（依据 EMBEDDED_CASES 的期望行为），避免抽取偏差
- 输出：eval/golden_set_v2.jsonl（保留 v1 全部字段，新增 facts / facts_source）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.generate import chat  # noqa: E402

GOLDEN_V1 = ROOT / "eval" / "golden_set.jsonl"
GOLDEN_V2 = ROOT / "eval" / "golden_set_v2.jsonl"

HAND_FACTS = {
    "h-01": [
        "500万元以上采购项目提交总经理办公会审议",
        "2023年办法第十二条关于采购审批权限的规定已被2025年细则第二十六条废止",
    ],
    "h-02": [
        "《采购管理办法》规定合同签订期限为30日",
        "《采购合同管理细则》规定为15个工作日",
        "两文件均现行且未相互废止，存在冲突需确认",
    ],
    "h-03": [
        "第八条规定200万元以上报总经理审批",
        "第十九条规定大额支付为300万元以上",
        "同一办法内两个金额门槛不一致",
    ],
    "h-04": [
        "第十四条规定15分钟内上报",
        "第二十六条规定30分钟内报送",
        "两处时限与起算点不一致",
    ],
    "h-05": ["履约保证金为合同金额5%", "制度未规定提交时限", "制度未规定退还时限"],
    "h-06": ["复核受理部门写作公司有关部门", "未指定具体责任部门"],
    "h-07": ["试行期为两年", "自2024年1月1日起算、2026年1月1日届满", "未见转正或废止文件"],
    "h-08": [
        "第二十四条过渡安排自发布之日起6个月后失效",
        "2024年2月28日发布、2024年8月28日失效",
        "现行按第十五条预算外支出审批权限办理",
    ],
}

PROMPT = (
    "下面是一条制度条款。请抽取 1–4 条**最小可判定事实点**，用于判断一个回答是否答对。\n"
    "要求：\n"
    "1. 每条事实点必须独立可判定，含主体/对象/数字或动作；\n"
    "2. 数字、金额、期限、比例必须单独成条，不得合并；\n"
    "3. 不要写成\"见第X条\"这种无法判定的表述；\n"
    "4. 只输出 JSON 数组：[\"事实点1\",\"事实点2\"]\n\n"
    "条款：\n{text}"
)


def extract_facts(text: str) -> list[str]:
    for _ in range(3):
        try:
            out = chat(
                [{"role": "user", "content": PROMPT.format(text=text[:1200])}],
                effort="none",
                max_tokens=600,
                timeout_s=60,
            )
            raw = out["content"].strip()
            s, e = raw.find("["), raw.rfind("]")
            if s < 0:
                continue
            facts = json.loads(raw[s : e + 1])
            facts = [str(f).strip() for f in facts if str(f).strip()]
            if 1 <= len(facts) <= 6:
                return facts[:4]
        except Exception:  # noqa: BLE001
            continue
    return []


def main() -> int:
    rows = [json.loads(line) for line in GOLDEN_V1.read_text(encoding="utf-8").splitlines() if line.strip()]
    out = []
    for n, r in enumerate(rows, start=1):
        if r["qid"] in HAND_FACTS:
            facts, src = HAND_FACTS[r["qid"]], "human"
        else:
            facts, src = extract_facts(r.get("gold_answer") or ""), "llm_extracted"
        row = dict(r)
        row["facts"] = facts
        row["facts_source"] = src
        out.append(row)
        if n % 20 == 0:
            print(f"  {n}/{len(rows)}")

    bad = [r["qid"] for r in out if not r["facts"]]
    if bad:
        print(f"[warn] {len(bad)} 条未抽到 facts：{bad[:5]}（这些题在 v0.2 口径下无法判 correct）")
    GOLDEN_V2.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n", encoding="utf-8")
    print(f"[done] {GOLDEN_V2} 共 {len(out)} 条；human_facts={sum(1 for r in out if r['facts_source']=='human')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
