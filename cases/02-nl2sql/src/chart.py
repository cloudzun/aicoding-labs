"""图表推荐：规则表（不交给模型），可解释、可测试。

规则来源：FT Visual Vocabulary 简化版（轴二分册 §6.5）。
"""

from __future__ import annotations

import re

TIME_HINT = re.compile(r"(month|date|time|day|created_at|bill_month|生效|日期|月份)", re.IGNORECASE)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def recommend(columns: list[str], rows: list[list]) -> dict:
    if not rows:
        return {"type": "empty", "x": None, "y": None, "reason": "无数据"}
    ncol = len(columns)
    nrow = len(rows)
    numeric_cols = [i for i in range(ncol) if any(_is_number(r[i]) for r in rows[:10])]
    text_cols = [i for i in range(ncol) if i not in numeric_cols]
    time_cols = [i for i in text_cols if TIME_HINT.search(columns[i])]

    # 单值 KPI
    if nrow == 1 and ncol == 1:
        return {"type": "kpi", "x": None, "y": columns[0], "reason": "单值指标"}

    # 单指标 + 一行多列（如 应收/实收/欠费）
    if nrow == 1 and ncol > 1 and numeric_cols:
        return {"type": "kpi_group", "x": None, "y": [columns[i] for i in numeric_cols], "reason": "单行多指标"}

    if len(numeric_cols) >= 1 and time_cols:
        return {"type": "line", "x": columns[time_cols[0]], "y": columns[numeric_cols[0]], "reason": "时间序列"}

    if len(numeric_cols) >= 1 and len(text_cols) >= 1:
        dim = columns[text_cols[0]]
        metric = columns[numeric_cols[0]]
        if nrow <= 6 and "%" in metric or metric.lower() in {"ratio", "rate"}:
            return {"type": "pie", "x": dim, "y": metric, "reason": "占比关系且类别≤6"}
        if nrow > 12:
            return {"type": "bar_h", "x": dim, "y": metric, "reason": "类别较多，横向条形"}
        return {"type": "bar", "x": dim, "y": metric, "reason": "类别与度量对比"}

    if len(numeric_cols) >= 2 and nrow > 1:
        return {"type": "scatter", "x": columns[numeric_cols[0]], "y": columns[numeric_cols[1]], "reason": "双变量关系"}

    return {"type": "table", "x": None, "y": None, "reason": "多维度明细，用表格最清晰"}
