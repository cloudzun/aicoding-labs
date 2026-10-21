"""从 gold SQL + 结果样例生成自然语言问句（LLM，批量 10 条/次）。

原则：问题在标准答案之后生成，避免"问题与答案错位"（RAG 那轮题料同源的教训）。
用法：python -m scripts.gen_questions
产出：eval/golden_set.jsonl（在 gold_cases 基础上补 question 字段）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.llm import chat  # noqa: E402

GOLD = ROOT / "eval" / "gold_cases.jsonl"
OUT = ROOT / "eval" / "golden_set.jsonl"
BATCH = 10

PROMPT = """下面是若干条 SQL 及其执行结果样例。请为**每一条**写一个业务人员真的会问的中文问题。

要求：
1. 口语化，15–35 字，像业务同事在群里问数据；
2. **不要出现**表名、列名、SELECT、JOIN 等 SQL 词汇；
3. 问题必须能被该 SQL 完整回答（不要额外加条件），且**必须点到 SQL 输出的每一列**
   （例如 SQL 返回 ticket_id/created_at/urgency，问题要同时提到单号、创建时间、紧急度）；
4. 如果 SQL 里有 LIMIT n，问题里必须写明"前 n 条/最近 n 条/Top n"，不能只说"有哪些"；
5. 时间范围要写清楚（例如"2026年9月""2025年第一季度"），不要用"最近"这类模糊词；
6. 只输出 JSON 数组，每项形如 {"qid":"...","question":"..."}，不要解释。

{cases}"""


def main() -> int:
    cases = [json.loads(x) for x in GOLD.read_text(encoding="utf-8").splitlines() if x.strip()]
    todo = [c for c in cases if not c.get("question")]
    print(f"待生成 {len(todo)} 条，分 {(len(todo) + BATCH - 1) // BATCH} 批")

    for i in range(0, len(todo), BATCH):
        batch = todo[i : i + BATCH]
        blocks = []
        for c in batch:
            sample = json.dumps(c.get("gold_sample", [])[:3], ensure_ascii=False)
            blocks.append(
                f"【{c['qid']}】要点：{c['hint']}\nSQL：{c['sql']}\n列：{c['columns']}\n结果样例：{sample}\n结果行数：{c['row_count']}"
            )
        got: dict[str, str] = {}
        for attempt in range(3):
            try:
                out = chat(
                    [{"role": "user", "content": PROMPT.replace("{cases}", "\n\n".join(blocks))}],
                    effort="none",
                    max_tokens=2200,
                    timeout_s=120,
                )
                raw = out["content"].strip()
                s, e = raw.find("["), raw.rfind("]")
                data = json.loads(raw[s : e + 1])
                for item in data:
                    qid, q = item.get("qid"), (item.get("question") or "").strip()
                    if qid and q:
                        got[qid] = q
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  批 {i // BATCH + 1} 重试（{type(exc).__name__}）")
        for c in batch:
            if c["qid"] in got:
                c["question"] = got[c["qid"]]
        print(f"  批 {i // BATCH + 1}/{(len(todo) + BATCH - 1) // BATCH} 完成，累计 {sum(1 for c in cases if c.get('question'))}")

    missing = [c["qid"] for c in cases if not c.get("question")]
    OUT.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n", encoding="utf-8")
    print(f"[done] {OUT}；缺问题 {len(missing)} 条 {missing[:5]}")
    return 0 if not missing else 2


if __name__ == "__main__":
    sys.exit(main())
