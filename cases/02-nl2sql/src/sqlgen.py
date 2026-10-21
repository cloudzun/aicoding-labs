"""SQL 生成：schema + 语义层 + few-shot 入 prompt，调模型，提取 SQL。"""

from __future__ import annotations

import re
import time

from .db import ALLOWED_TABLES, schema_text, semantic_layer
from .llm import MODEL_MAIN, LLMError, chat, extract_sql

FEW_SHOT = [
    {
        "q": "杭州有多少家状态正常的客户？",
        "sql": "SELECT COUNT(*) AS cnt FROM dim_customer WHERE city LIKE '杭州%' AND status = '正常'",
    },
    {
        "q": "2026年9月应收合计多少元？",
        "sql": "SELECT ROUND(SUM(amount_due), 2) AS due FROM fact_bill WHERE bill_month = '2026-09'",
    },
    {
        "q": "各产品类型的在网订单折扣后月费合计是多少？",
        "sql": "SELECT p.product_type, ROUND(SUM(o.monthly_fee * o.discount_rate), 2) AS fee FROM fact_order o JOIN dim_product p ON p.product_id = o.product_id WHERE o.cancel_date IS NULL GROUP BY p.product_type ORDER BY fee DESC",
    },
]


def _semantic_block() -> str:
    sl = semantic_layer()
    lines = ["【指标口径】"]
    for m in sl["metrics"]:
        lines.append(f"- {m['name']}：{m['definition']}")
    lines.append("\n【同义词】")
    for k, v in sl["synonyms"].items():
        lines.append(f"- {k} → {v}")
    lines.append("\n【推荐关联】")
    for j in sl["joins"]:
        lines.append(f"- {j['left']} = {j['right']}（{j['comment']}）")
    return "\n".join(lines)


def system_prompt() -> str:
    tables = ", ".join(ALLOWED_TABLES)
    return f"""你是运营商政企业务的数据分析助手，把中文问题翻译成**一条 SQLite 查询**。

【可用表】{tables}

【表结构】
{schema_text()}

{_semantic_block()}

【硬规则】
1. 只输出一条 SELECT（可用 WITH），不要 INSERT/UPDATE/DELETE/DDL，不要多语句。
2. 只用上面列出的表和列，不要自造字段。
3. 地市字段存在『杭州/杭州市』两种写法，筛地市一律用 `city LIKE '杭州%'`。
4. 客户数用 `COUNT(DISTINCT customer_id)`，不要按名称计数（存在同名不同 ID 的客户）。
5. 产品关联一律用 product_id，**不要用 product_name 关联**（存在同名不同规格）。
6. 月费/金额要区分：标准月费 = `monthly_fee`；折扣后月费 = `monthly_fee * discount_rate`；营收 = `SUM(amount_due)`（含调整）。
7. 『在网』按语义层 M05：`cancel_date IS NULL AND effective_date <= 统计日`；『已退订』= `cancel_date IS NOT NULL`。
8. 平均响应时长必须排除未响应：`first_response_at IS NOT NULL`。
9. 题面给了具体月份/时间范围就严格用；没给就用数据里最大的账期。
10. 除非题面要求 Top N，不要自己加 LIMIT；外层会自动限行。
11. 季度标签统一写成 `YYYY-Qn`（如 2026-Q1）；月份写成 `YYYY-MM`。
12. 『平均标准月费』= `AVG(dim_product.standard_price)`，不要用订单月费代替；『月费合计』若未特别说明，按折扣后月费 `monthly_fee*discount_rate`。
13. 输出格式：先 ```sql 代码块，再一句话说明用到的口径（不要解释 SQL 语法）。"""


def build_messages(question: str) -> list[dict]:
    msgs = [{"role": "system", "content": system_prompt()}]
    for ex in FEW_SHOT:
        msgs.append({"role": "user", "content": ex["q"]})
        msgs.append({"role": "assistant", "content": f"```sql\n{ex['sql']}\n```"})
    msgs.append({"role": "user", "content": question})
    return msgs


def generate(question: str, model: str = MODEL_MAIN) -> dict:
    """返回 {sql, raw, elapsed_ms, usage}；提取失败抛 LLMError。"""
    t0 = time.perf_counter()
    out = chat(build_messages(question), model=model, effort="none", max_tokens=900, timeout_s=40)
    sql = extract_sql(out["content"])
    if not sql:
        raise LLMError("未能从模型输出中提取 SQL")
    import sqlite3 as _sq

    if not _sq.complete_statement(sql + ";"):
        raise LLMError("模型输出的 SQL 不完整")
    return {
        "sql": sql,
        "raw": out["content"][:800],
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        "usage": out.get("usage", {}),
        "model": out.get("model", model),
    }


def correct(question: str, bad_sql: str, error: str, model: str = MODEL_MAIN) -> dict:
    """纠错：带上失败 SQL 与错误信息，要求给一条新 SQL。"""
    msgs = build_messages(question)
    msgs.append({"role": "assistant", "content": f"```sql\n{bad_sql}\n```"})
    msgs.append(
        {
            "role": "user",
            "content": f"这条 SQL 执行失败或被安全策略拒绝，原因是：{error}\n请修正后重新输出一条 SQLite SELECT，只输出 ```sql 代码块。",
        }
    )
    t0 = time.perf_counter()
    out = chat(msgs, model=model, effort="none", max_tokens=900, timeout_s=40)
    sql = extract_sql(out["content"])
    if not sql:
        raise LLMError("纠错未能提取 SQL")
    return {
        "sql": sql,
        "raw": out["content"][:800],
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        "usage": out.get("usage", {}),
        "model": out.get("model", model),
    }


def metrics_used(question: str) -> list[str]:
    """粗粒度标注用到了哪些口径（供界面展示，不做判定）。"""
    sl = semantic_layer()
    hit: list[str] = []
    for m in sl["metrics"]:
        if m["name"] in question:
            hit.append(f"{m['name']}：{m['definition']}")
    for word, target in sl["synonyms"].items():
        if word in question and "M" in str(target):
            for m in sl["metrics"]:
                if m["id"] == target:
                    line = f"{m['name']}：{m['definition']}"
                    if line not in hit:
                        hit.append(line)
    return hit[:5]


__all__ = ["generate", "correct", "metrics_used", "system_prompt", "build_messages", "re"]
