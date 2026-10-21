"""构建评测集：golden_set.jsonl（主集 200）+ refusal_set.jsonl（拒答集 50）。

构成（诚实披露，报告会引用）：
- 单跳 120 条：LLM 从真实条款反推用户会问的问题（gold = 该条款）
- 多跳 40 条：跨文档两条款配对，LLM 生成需要同时参考两条款的问题
- 冲突/时效 8 条：**手写**，依据 data/corpus/synthetic/EMBEDDED_CASES.md 的埋点
- 无关 32 条：LLM 生成"通信企业合理但本库没有"的问题
- 拒答集 50 条：全部不可回答（LLM 生成 + 人工挑选）

用法：python -m scripts.make_golden_set [--rebuild]
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from src.core import CORPUS, EVIDENCE, ROOT, read_jsonl, write_jsonl
from src.generate import chat

EVAL = ROOT / "eval"
GOLDEN = EVAL / "golden_set.jsonl"
REFUSAL = EVAL / "refusal_set.jsonl"
CHUNKS = ROOT / "data" / "index" / "chunks.jsonl"

# ---- 手写冲突/时效用例（依据 EMBEDDED_CASES.md）----
HAND_CASES = [
    {
        "qid": "h-01",
        "split": "conflict_or_stale",
        "question": "单笔采购金额500万元以上的采购项目，需要提交什么会议审议？",
        "gold_refs": [("zdcg-2025-004", "第十条"), ("zdcg-2025-004", "第二十六条"), ("zdcg-2023-001", "第十二条")],
        "expect": "答500万口径，并说明2023办法第十二条已被2025细则第二十六条废止；只答300万或只说'两份冲突'均不合格",
    },
    {
        "qid": "h-02",
        "split": "conflict_or_stale",
        "question": "中标供应商应在多少天内与公司签订书面合同？",
        "gold_refs": [("zdcg-2023-001", "第十八条"), ("zdcg-2024-003", "第九条")],
        "expect": "并列30日与15个工作日，说明均现行、无废止，属冲突需确认；只答一个数字不合格",
    },
    {
        "qid": "h-03",
        "split": "conflict_or_stale",
        "question": "单笔资金支付达到多少金额需要报总经理审批？",
        "gold_refs": [("zdcw-2023-005", "第八条"), ("zdcw-2023-005", "第十九条")],
        "expect": "指出同一办法内200万与300万两个门槛不一致，无法据文本判定，建议从严或请财务部解释",
    },
    {
        "qid": "h-04",
        "split": "conflict_or_stale",
        "question": "发生重大通信故障后，应在多长时间内上报省公司网络运行维护中心？",
        "gold_refs": [("zdww-2023-010", "第十四条"), ("zdww-2023-010", "第二十六条")],
        "expect": "并列15分钟与30分钟，指出起算点不同且未定义'故障确认'，建议按15分钟从严并请确认",
    },
    {
        "qid": "h-05",
        "split": "conflict_or_stale",
        "question": "履约保证金什么时候提交，什么时候退还？",
        "gold_refs": [("zdcg-2023-001", "第十九条")],
        "expect": "明确说明制度只规定比例5%与退还条件，未规定提交时限与退还时限，不得编造期限",
    },
    {
        "qid": "h-06",
        "split": "conflict_or_stale",
        "question": "员工对申诉处理结论不服，应向哪个部门申请复核？",
        "gold_refs": [("zdrl-2025-009", "第十四条")],
        "expect": "指出条文只写'公司有关部门'未指定部门，可推断人力资源部但须标注为推断",
    },
    {
        "qid": "h-07",
        "split": "conflict_or_stale",
        "question": "供应商管理实施细则现在还有效吗？",
        "gold_refs": [("zdcg-2023-002", "第二十七条")],
        "expect": "指出试行期两年已于2026年1月1日届满、未见转正或废止文件，适用性需确认",
    },
    {
        "qid": "h-08",
        "split": "conflict_or_stale",
        "question": "数字化服务成本科目的立项由谁审批？",
        "gold_refs": [("zdcw-2024-006", "第二十四条"), ("zdcw-2024-006", "第十五条")],
        "expect": "说明第二十四条过渡安排已于2024-08-28失效，现行按第十五条预算外支出审批权限办理",
    },
]


def llm_json(prompt: str, max_tokens: int = 3000) -> list | dict | None:
    """让模型输出 JSON，容错解析。"""
    out = chat(
        [{"role": "system", "content": "你只输出 JSON，不要解释、不要 markdown 代码块。"}, {"role": "user", "content": prompt}],
        effort="none",
        max_tokens=max_tokens,
        timeout_s=120,
    )
    text = out["content"].strip()
    start = min([i for i in (text.find("["), text.find("{")) if i >= 0], default=-1)
    if start < 0:
        return None
    end = max(text.rfind("]"), text.rfind("}"))
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def build() -> None:
    chunks = read_jsonl(CHUNKS)
    if not chunks:
        raise SystemExit("先运行 python -m src.ingest")
    key_map = {(c["doc_id"], c["clause_no"]): c["chunk_id"] for c in chunks if c["clause_no"]}
    by_doc: dict[str, list[dict]] = {}
    for c in chunks:
        by_doc.setdefault(c["doc_id"], []).append(c)

    rng = random.Random(20261020)
    rows: list[dict] = []

    # ---- 冲突/时效（手写）----
    for case in HAND_CASES:
        ids = [key_map[ref] for ref in case["gold_refs"] if ref in key_map]
        if len(ids) != len(case["gold_refs"]):
            print(f"[warn] {case['qid']} 有 gold 条款未找到，跳过：{case['gold_refs']}")
            continue
        rows.append(
            {
                "qid": case["qid"],
                "split": case["split"],
                "question": case["question"],
                "gold_chunk_ids": ids,
                "gold_answer": "\n".join(
                    next(c["text"] for c in chunks if c["chunk_id"] == i) for i in ids
                ),
                "expect": case["expect"],
                "source": "human",
                "answerable": True,
            }
        )
    print(f"手写冲突/时效：{len(rows)} 条")

    # ---- 单跳 120（LLM 反推）----
    # F11：只允许有条款号的正文件段出题，避免标题/元数据 chunk 污染 gold
    pool = [c for c in chunks if c["char_count"] >= 60 and c["clause_no"]]
    sample = rng.sample(pool, min(120, len(pool)))
    for n, c in enumerate(sample, start=1):
        prompt = (
            f"下面是一条企业制度条款。请写一个**员工真的会问**的问题（口语化，20-40字，"
            f"不要出现'第X条'，不要抄原文句子，必须能只靠这条款回答）。只输出 JSON：{{\"question\":\"...\"}}\n\n"
            f"《{c['doc_title']}》{c['clause_no']}：{c['text'][:400]}"
        )
        data = None
        for _ in range(3):  # F11 残余：单跳生成失败重试
            data = llm_json(prompt, 300)
            if isinstance(data, dict) and data.get("question"):
                break
        q = (data or {}).get("question") if isinstance(data, dict) else None
        if not q:
            print(f"  [skip] {c['chunk_id']} 生成失败")
            continue
        rows.append(
            {
                "qid": f"a-{n:03d}",
                "split": "single_hop",
                "question": q.strip(),
                "gold_chunk_ids": [c["chunk_id"]],
                "gold_answer": c["text"],
                "source": "llm_generated",
                "answerable": True,
            }
        )
        if n % 20 == 0:
            print(f"  单跳 {n}/120")
    print(f"单跳小计：{sum(1 for r in rows if r['split'] == 'single_hop')} 条")

    # ---- 多跳 40（跨文档配对）----
    docs = [d for d in by_doc if len(by_doc[d]) >= 5]
    pairs: list[tuple[dict, dict]] = []

    def _pick(doc_id: str) -> dict:
        cands = [c for c in by_doc[doc_id] if c["char_count"] >= 60 and c["clause_no"]]
        return rng.choice(cands)

    # 多生成 20 组作为失败重试的余量
    while len(pairs) < 60:
        d1, d2 = rng.sample(docs, 2)
        pairs.append((_pick(d1), _pick(d2)))
    for n, (c1, c2) in enumerate(pairs, start=1):
        prompt = (
            "下面两条来自不同制度的条款。请写一个必须**同时参考这两条**才能完整回答的问题"
            "（口语化，25-45字，不要出现'第X条'）。只输出 JSON：{\"question\":\"...\"}\n\n"
            f"《{c1['doc_title']}》{c1['clause_no']}：{c1['text'][:300]}\n\n"
            f"《{c2['doc_title']}》{c2['clause_no']}：{c2['text'][:300]}"
        )
        data = None
        for _ in range(3):  # F11 残余：多跳生成失败重试
            data = llm_json(prompt, 300)
            if isinstance(data, dict) and data.get("question"):
                break
        q = (data or {}).get("question") if isinstance(data, dict) else None
        if not q:
            continue
        rows.append(
            {
                "qid": f"m-{n:03d}",
                "split": "multi_hop",
                "question": q.strip(),
                "gold_chunk_ids": [c1["chunk_id"], c2["chunk_id"]],
                "gold_answer": c1["text"] + "\n" + c2["text"],
                "source": "llm_generated",
                "answerable": True,
            }
        )
    print(f"多跳小计：{sum(1 for r in rows if r['split'] == 'multi_hop')} 条")

    # ---- 无关 32（库内没有，但通信企业合理）----
    topic_hint = "考勤、个税、公积金、员工体检、工会经费、办公用品领用、车辆管理、涉密文件、新闻宣传、客户投诉、渠道酬金、实名制、携号转网、专线装维、IDC 机房、基站电费、铁塔租费、频谱、应急通信、网络安全演练"
    data = llm_json(
        "请生成 32 个企业员工可能问、但下面这份制度库**没有**规定的问题（通信运营企业场景）。"
        "参考主题：" + topic_hint + "。问题要具体口语化，20-40字，不要重复。"
        '只输出 JSON 数组：["问题1","问题2",...]',
        3000,
    )
    if isinstance(data, list):
        for n, q in enumerate(data[:32], start=1):
            if not isinstance(q, str):
                continue
            rows.append(
                {
                    "qid": f"u-{n:03d}",
                    "split": "unanswerable",
                    "question": q.strip(),
                    "gold_chunk_ids": [],
                    "gold_answer": None,
                    "source": "llm_generated",
                    "answerable": False,
                }
            )
    print(f"无关小计：{sum(1 for r in rows if r['split'] == 'unanswerable')} 条")

    # F11：数量断言，生成失败就报错，不静默缩水
    n_single = sum(1 for r in rows if r["split"] == "single_hop")
    n_multi = sum(1 for r in rows if r["split"] == "multi_hop")
    n_conf = sum(1 for r in rows if r["split"] == "conflict_or_stale")
    if n_conf != 8 or n_single < 110 or n_multi < 30:  # 重试后门槛提高到 30
        raise SystemExit(
            f"评测集规模不达标：single={n_single}/120 multi={n_multi}/40 conflict={n_conf}/8"
        )
    write_jsonl(GOLDEN, rows)
    print(f"[done] {GOLDEN} 共 {len(rows)} 条")

    # ---- 拒答集 50 ----
    refusal = [r for r in rows if r["split"] == "unanswerable"]
    extra = llm_json(
        "请再生成 40 个通信企业员工可能问、但制度库里没有的问题（与考勤、薪酬、福利、办公后勤、"
        "客户服务细则相关），每条 20-40 字，不重复。只输出 JSON 数组。",
        4000,
    )
    if isinstance(extra, list):
        for n, q in enumerate(extra, start=1):
            if isinstance(q, str) and len(q.strip()) > 6:
                refusal.append(
                    {
                        "qid": f"r-{n:03d}",
                        "split": "unanswerable",
                        "question": q.strip(),
                        "gold_chunk_ids": [],
                        "gold_answer": None,
                        "source": "llm_generated",
                        "answerable": False,
                    }
                )
    seen = set()
    uniq = []
    for r in refusal:
        if r["question"] in seen:
            continue
        seen.add(r["question"])
        uniq.append(r)
    write_jsonl(REFUSAL, uniq[:50])
    print(f"[done] {REFUSAL} 共 {min(len(uniq), 50)} 条")

    manifest = {
        "built_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "golden_count": len(rows),
        "refusal_count": min(len(uniq), 50),
        "composition": {
            "single_hop": sum(1 for r in rows if r["split"] == "single_hop"),
            "multi_hop": sum(1 for r in rows if r["split"] == "multi_hop"),
            "conflict_or_stale": sum(1 for r in rows if r["split"] == "conflict_or_stale"),
            "unanswerable": sum(1 for r in rows if r["split"] == "unanswerable"),
            "human_written": sum(1 for r in rows if r.get("source") == "human"),
            "llm_generated": sum(1 for r in rows if r.get("source") == "llm_generated"),
        },
        "disclosure": "单跳/多跳/无关题为 LLM 生成，冲突与时效 8 条为人工手写；用于教学演示，对外使用前需人工复核。",
    }
    (EVAL / "golden_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest["composition"], ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    if GOLDEN.exists() and not args.rebuild:
        print(f"{GOLDEN} 已存在（{len(read_jsonl(GOLDEN))} 条），加 --rebuild 重建")
    else:
        build()
