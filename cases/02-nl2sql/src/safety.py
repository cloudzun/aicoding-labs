"""四道安全闸（全部确定性实现，不依赖提示词）。

1. 只读：连接层 mode=ro（见 db.py）
2. 表白名单 + 语句白名单：SQLite authorizer（运行时拦截，比正则可靠）
3. 强制 LIMIT：外层包装
4. 超时：progress handler 计数中断
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field

from .db import ALLOWED_TABLES, connect_readonly

# 允许的 SQL 函数白名单（默认拒绝，防 load_extension 等被调用）
ALLOWED_FUNCTIONS = {
    "count", "sum", "avg", "min", "max", "total", "round", "abs",
    "substr", "length", "instr", "replace", "trim", "ltrim", "rtrim",
    "julianday", "strftime", "date", "datetime", "time",
    "lower", "upper", "coalesce", "ifnull", "nullif", "printf", "cast",
    "group_concat", "distinct", "like", "glob",
}

MAX_ROWS_DEFAULT = 1000
TIMEOUT_S_DEFAULT = 10.0

FORBIDDEN_ACTIONS = {
    sqlite3.SQLITE_INSERT,
    sqlite3.SQLITE_UPDATE,
    sqlite3.SQLITE_DELETE,
    sqlite3.SQLITE_PRAGMA,
    sqlite3.SQLITE_ATTACH,
    sqlite3.SQLITE_DETACH,
    sqlite3.SQLITE_ALTER_TABLE,
    sqlite3.SQLITE_CREATE_TABLE,
    sqlite3.SQLITE_CREATE_INDEX,
    sqlite3.SQLITE_DROP_TABLE,
    sqlite3.SQLITE_DROP_INDEX,
    sqlite3.SQLITE_REINDEX,
    sqlite3.SQLITE_ANALYZE,
}

WRITE_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|attach|detach|pragma|vacuum|reindex)\b",
    re.IGNORECASE,
)


@dataclass
class Validation:
    ok: bool
    reason: str = ""
    sql: str = ""
    checks: list[str] = field(default_factory=list)


def _split_statements(sql: str) -> list[str]:
    return [s.strip() for s in sql.split(";") if s.strip()]


def validate_sql(sql: str, allowed_tables: tuple[str, ...] = ALLOWED_TABLES) -> Validation:
    """静态校验：只允许单条 SELECT / WITH 查询，且不出现写关键字与系统表。"""
    checks: list[str] = []
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        return Validation(False, "SQL 为空", s, checks)
    checks.append("非空")

    stmts = _split_statements(sql)
    if len(stmts) > 1:
        return Validation(False, f"检测到 {len(stmts)} 条语句，只允许单条查询", s, checks)
    checks.append("单语句")

    if not re.match(r"^\s*(select|with)\b", s, re.IGNORECASE):
        return Validation(False, "只允许 SELECT（或 WITH 开头的查询）", s, checks)
    checks.append("仅查询")

    if WRITE_KEYWORDS.search(s):
        hit = WRITE_KEYWORDS.search(s)
        return Validation(False, f"包含写操作关键字：{hit.group(0) if hit else ''}", s, checks)
    checks.append("无写关键字")

    if re.search(r"\bsqlite_[a-z_]+\b", s, re.IGNORECASE):
        return Validation(False, "禁止访问 sqlite 系统表", s, checks)
    checks.append("无系统表")

    # 表名白名单（粗筛；精确拦截由 authorizer 负责）
    mentioned = set(re.findall(r"\b(from|join)\s+([a-zA-Z_][\w]*)", s, re.IGNORECASE))
    bad = {t[1].lower() for t in mentioned if t[1].lower() not in {x.lower() for x in allowed_tables}}
    if bad:
        return Validation(False, f"涉及未授权表：{sorted(bad)}", s, checks)
    checks.append("表白名单")

    return Validation(True, "", s, checks)


def wrap_limit(sql: str, max_rows: int = MAX_ROWS_DEFAULT) -> str:
    # 取 max_rows+1 行用于精确判截断；多行包裹避免 SQL 末尾 `-- 注释` 吞掉右括号
    body = sql.rstrip().rstrip(";")
    return f"SELECT * FROM (\n{body}\n) LIMIT {int(max_rows) + 1}"


def _authorizer(action, arg1, arg2, dbname, trigger):
    """默认拒绝（评审意见：原实现末尾无条件放行，ATTACH/DETACH 等可绕过白名单）。"""
    if action in FORBIDDEN_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        table = (arg1 or "").lower()
        if table.startswith("sqlite_") or table not in {t.lower() for t in ALLOWED_TABLES}:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION:
        name = (arg2 or "").lower()
        return sqlite3.SQLITE_OK if name in ALLOWED_FUNCTIONS else sqlite3.SQLITE_DENY
    if action in (sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT):
        return sqlite3.SQLITE_OK
    if action == getattr(sqlite3, "SQLITE_RECURSIVE", -1):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def guarded_query(sql: str, max_rows: int = MAX_ROWS_DEFAULT, timeout_s: float = TIMEOUT_S_DEFAULT) -> dict:
    """校验 → 包装 LIMIT → authorizer → 超时执行。返回 {ok, sql, columns, rows, truncated, reason, elapsed_ms}"""
    v = validate_sql(sql)
    if not v.ok:
        return {"ok": False, "reason": v.reason, "sql": sql, "columns": [], "rows": [], "truncated": False, "elapsed_ms": 0}

    wrapped = wrap_limit(v.sql, max_rows)
    conn = connect_readonly()
    deadline = time.perf_counter() + timeout_s
    timed_out = {"hit": False}

    def handler() -> int:
        if time.perf_counter() > deadline:
            timed_out["hit"] = True
            return 1
        return 0

    t0 = time.perf_counter()
    try:
        conn.set_authorizer(_authorizer)
        conn.set_progress_handler(handler, 1000)
        cur = conn.execute(wrapped)
        cols = [d[0] for d in cur.description]
        rows = [list(r) for r in cur.fetchall()]
        truncated = len(rows) > max_rows
        if truncated:
            rows = rows[:max_rows]
    except sqlite3.OperationalError as exc:
        if timed_out["hit"] or "interrupted" in str(exc).lower():
            return {"ok": False, "reason": f"查询超时（>{timeout_s}s）", "sql": wrapped, "columns": [], "rows": [], "truncated": False,
                    "elapsed_ms": int((time.perf_counter() - t0) * 1000)}
        return {"ok": False, "reason": f"执行失败：{exc}", "sql": wrapped, "columns": [], "rows": [], "truncated": False,
                "elapsed_ms": int((time.perf_counter() - t0) * 1000)}
    except sqlite3.DatabaseError as exc:
        return {"ok": False, "reason": f"被安全策略拒绝：{exc}", "sql": wrapped, "columns": [], "rows": [], "truncated": False,
                "elapsed_ms": int((time.perf_counter() - t0) * 1000)}
    finally:
        conn.close()

    norm = [[round(v, 2) if isinstance(v, float) else v for v in r] for r in rows]
    return {
        "ok": True,
        "reason": "",
        "sql": wrapped,
        "columns": cols,
        "rows": norm,
        "truncated": truncated,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }
