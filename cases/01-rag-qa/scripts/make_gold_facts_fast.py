"""批量抽取 facts（8 题/次），只为评测子集生成 v2 数据。

背景：逐题调用在网关争抢下会拖到不可用（实测 35 分钟 20 题）。批量化把 80 次调用压到 10 次。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.generate import chat  # noqa: E402
from scripts.make_gold_facts import HAND_FACTS  # noqa: E402

SUBSET = ROOT / "eval" / "subset_judged.jsonl"
FULL = ROOT / "eval" / "golden_set.jsonl"
OUT = ROOT / "eval" / "golden_set_v2.jsonl"
BATCH = 8

PROMPT = (
    "下面是若干条制度条款（带编号）。请为**每一条**抽取 1–4 条最小可判定事实点，用于判断回答是否答对。\n"
    "要求：数字/金额/期限/比例必须单独成条；每条事实点须含主体或对象；不要写『见第X条』。\n"
    "只输出 JSON 数组，每项形如 {\"qid\":\"...\",\"facts\":[\"事实点1\",\"事实点2\"]}，不要解释。\n\n"
    "{blocks}"
)


def main() -> int:
    subset = [json.loads(x) for x in SUBSET.read_text(encoding="utf-8").splitlines() if x.strip()]
    full = {r["qid"]: r for r in (json.loads(x) for x in FULL.read_text(encoding="utf-8").splitlines() if x.strip())}
    rows = []
    for r in subset:
        row = dict(full.get(r["qid"], r))
        row["gold_answer"] = row.get("gold_answer") or ""
        rows.append(row)

    todo = [r for r in rows if r["qid"] not in HAND_FACTS]
    results: dict[str, list[str]] = {}
    for i in range(0, len(todo), BATCH):
        batch = todo[i : i + BATCH]
        blocks = "\n\n".join(
            f"【{r['qid']}】{(r.get('gold_answer') or '')[:700]}" for r in batch
        )
        ok = False
        for _ in range(3):
            try:
                out = chat(
                    [{"role": "user", "content": PROMPT.replace("{blocks}", blocks)}],
                    effort="none",
                    max_tokens=2200,
                    timeout_s=120,
                )
                raw = out["content"].strip()
                s, e = raw.find("["), raw.rfind("]")
                data = json.loads(raw[s : e + 1])
                for item in data:
                    qid, facts = item.get("qid"), item.get("facts") or []
                    facts = [str(f).strip() for f in facts if str(f).strip()]
                    if qid and 1 <= len(facts) <= 6:
                        results[qid] = facts[:4]
                ok = True
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  batch {i // BATCH + 1} 重试：{type(exc).__name__}")
        print(f"  batch {i // BATCH + 1}/{(len(todo) + BATCH - 1) // BATCH} -> {'ok' if ok else 'fail'}，累计 {len(results)} 题")

    out_rows = []
    for r in rows:
        qid = r["qid"]
        facts = HAND_FACTS.get(qid) or results.get(qid) or []
        src = "human" if qid in HAND_FACTS else ("llm_extracted" if facts else "missing")
        row = dict(r)
        row["facts"] = facts
        row["facts_source"] = src
        out_rows.append(row)

    missing = [r["qid"] for r in out_rows if not r["facts"]]
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out_rows) + "\n", encoding="utf-8")
    print(f"[done] {OUT} 共 {len(out_rows)} 条；缺 facts {len(missing)} 条 {missing[:5]}")
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
