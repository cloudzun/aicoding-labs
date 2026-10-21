"""数据库访问：只读连接、schema 文本、样本行。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _cfg() -> dict[str, str]:
    cfg: dict[str, str] = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


CFG = _cfg()
DB_PATH = ROOT / CFG.get("DB_PATH", "data/aicoding.db")
ALLOWED_TABLES = ("dim_customer", "dim_product", "dim_employee", "fact_order", "fact_ticket", "fact_bill")


def connect_readonly() -> sqlite3.Connection:
    """只读连接：即使上层校验被绕过，SQLite 也拒绝写。"""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = None
    return conn


def semantic_layer() -> dict:
    return json.loads((ROOT / "semantic_layer.json").read_text(encoding="utf-8"))


def schema_text() -> str:
    """生成给模型看的 schema 说明（含表注释与列注释，来自语义层，唯一事实源）。"""
    sl = semantic_layer()
    lines: list[str] = []
    for table in ALLOWED_TABLES:
        info = sl["tables"].get(table, {})
        lines.append(f"表 {table}：{info.get('comment', '')}")
        for col, desc in (info.get("columns") or {}).items():
            lines.append(f"  - {col}: {desc}")
    return "\n".join(lines)


def sample_rows(limit: int = 2) -> dict[str, list[list]]:
    """每表取少量样本行，帮助模型理解数据形态（不含敏感信息，本库为合成数据）。"""
    out: dict[str, list[list]] = {}
    conn = connect_readonly()
    try:
        for t in ALLOWED_TABLES:
            cur = conn.execute(f"SELECT * FROM {t} LIMIT {int(limit)}")
            cols = [d[0] for d in cur.description]
            out[t] = {"columns": cols, "rows": [[str(v) for v in r] for r in cur.fetchall()]}  # type: ignore[assignment]
    finally:
        conn.close()
    return out  # type: ignore[return-value]


def table_columns() -> dict[str, list[str]]:
    conn = connect_readonly()
    try:
        return {t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")] for t in ALLOWED_TABLES}
    finally:
        conn.close()


if __name__ == "__main__":
    print(schema_text()[:600])
    print("tables:", ALLOWED_TABLES)
