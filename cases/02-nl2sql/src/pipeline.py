"""编排：歧义闸 → 生成 → 安全校验/执行 → 纠错(≤2) → 图表 → trace。"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from . import sqlgen
from .chart import recommend
from .db import semantic_layer
from .safety import guarded_query
from .llm import LLMError

ROOT = Path(__file__).resolve().parents[1]
TRACES = ROOT / "data" / "traces"
MAX_ATTEMPTS = 2  # 首次 + 最多 2 次纠错

DISAMBIGUATORS = {
    "营收": ["含调整", "不含调整", "原值", "扣调整"],
    "近三个月": ["不含当月", "含当月", "完整账期"],
    "近3个月": ["不含当月", "含当月", "完整账期"],
    "最近三个月": ["不含当月", "含当月", "完整账期"],
    "客户数": ["去重", "客户编号", "customer_id", "按名称"],
    "多少客户": ["去重", "客户编号", "按名称"],
    "客户数量": ["去重", "客户编号", "按名称"],
    "SLA": ["按时长", "按时长", "按标记", "4小时"],
    "超时": ["按时长", "按时长", "按标记", "4小时"],
    "在网": ["含待生效", "仅已生效", "已生效"],
    "月费": ["折扣后", "标准月费"],
    "多少钱": ["折扣后", "标准月费"],
    "金额": ["应收", "实收", "欠费", "调整"],
}


WRITE_INTENT = re.compile(
    r"(删除|删掉|删了|清除|清空|清掉|更新|修改|改成|改为|插入|覆盖|drop|delete|update|insert|truncate|alter)",
    re.IGNORECASE,
)


def detect_write_intent(question: str) -> str | None:
    """意图闸：命中写操作动词即拒绝，不交给模型解释成查询（避免"以为删了"的误解）。"""
    m = WRITE_INTENT.search(question)
    return m.group(1) if m else None


def detect_ambiguity(question: str) -> dict | None:
    """命中歧义词且没有消歧表述 → 返回澄清请求（不生成 SQL）。"""
    sl = semantic_layer()
    for amb in sl["ambiguities"]:
        for trig in amb["trigger"]:
            if trig in question:
                marks = DISAMBIGUATORS.get(trig, [])
                if any(m in question for m in marks):
                    continue  # 已自行消歧，正常作答
                return {
                    "trigger": trig,
                    "question": amb["question"],
                    "options": amb["options"],
                    "blocking": bool(amb.get("blocking")),
                    "default": amb.get("default"),
                }
    return None


TRACE_ID_RE = __import__("re").compile(r"^q[0-9a-f]{8,16}$")


def _trace_path(tid: str) -> Path:
    if not TRACE_ID_RE.match(tid or ""):
        raise ValueError("trace_id 非法")
    return TRACES / f"{tid}.json"


def ask(question: str, clarify: bool = True, max_rows: int = 1000) -> dict:
    t0 = time.perf_counter()
    question = (question or "").strip()[:500]
    max_rows = max(1, min(int(max_rows), 1000))
    tid = "q" + uuid.uuid4().hex[:12]
    TRACES.mkdir(parents=True, exist_ok=True)

    result: dict = {
        "trace_id": tid,
        "question": question,
        "clarification": None,
        "sql": None,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "chart": {"type": "empty", "reason": "未执行"},
        "metrics_used": sqlgen.metrics_used(question),
        "attempts": 0,
        "timings_ms": {},
        "rejected": None,
    }

    # ⓪ 意图闸（确定性）：写操作直接拒绝，绝不静默改成查询
    write_hit = detect_write_intent(question)
    if write_hit:
        result["rejected"] = {
            "reason": f"本系统只读，不能执行写操作（识别到『{write_hit}』）。如需查看数据，请改成查询类问题。",
            "gate": "write_intent",
        }
        result["timings_ms"] = {"total": int((time.perf_counter() - t0) * 1000)}
        _write_trace(tid, result, final_sql=None, validation={"stage": "write_intent_rejected", "hit": write_hit})
        return result

    # ① 歧义闸（确定性，先于生成）
    if clarify:
        amb = detect_ambiguity(question)
        if amb and amb["blocking"]:
            # 阻塞式：口径不定就不能答（营收/近三月/金额）
            result["clarification"] = {**amb, "level": "blocking"}
            result["timings_ms"] = {"total": int((time.perf_counter() - t0) * 1000)}
            _write_trace(tid, result, final_sql=None, validation={"stage": "clarification_blocking"})
            return result
        if amb:
            # 提示式：语义层已有默认口径，照常作答并声明采用的口径
            result["clarification"] = {**amb, "level": "advisory"}

    # ② 生成 + ③ 校验执行 + 纠错
    gen_ms = 0
    exec_ms = 0
    candidates: list[dict] = []
    sql = ""
    try:
        g = sqlgen.generate(question)
        gen_ms += g["elapsed_ms"]
        sql = g["sql"]
        candidates.append({"sql": sql, "stage": "initial"})
    except LLMError as exc:
        # 不让异常原文（可能含 URL/key/prompt）回传给调用方
        result["rejected"] = {"reason": "生成失败：模型服务暂不可用或超时，请重试"}
        result["timings_ms"] = {"total": int((time.perf_counter() - t0) * 1000)}
        _write_trace(tid, result, final_sql=None, validation={"stage": "generate_failed"})
        return result

    exec_result: dict | None = None
    for attempt in range(MAX_ATTEMPTS + 1):
        r = guarded_query(sql, max_rows=max_rows)
        exec_ms += r["elapsed_ms"]
        candidates[-1]["ok"] = r["ok"]
        candidates[-1]["reason"] = r["reason"]
        if r["ok"]:
            exec_result = r
            break
        if attempt < MAX_ATTEMPTS:
            try:
                c = sqlgen.correct(question, sql, r["reason"])
                gen_ms += c["elapsed_ms"]
                sql = c["sql"]
                candidates.append({"sql": sql, "stage": f"correction_{attempt + 1}"})
            except LLMError:
                break

    result["attempts"] = len(candidates)
    result["timings_ms"] = {
        "generate": gen_ms,
        "execute": exec_ms,
        "total": int((time.perf_counter() - t0) * 1000),
    }

    if exec_result is None:
        result["rejected"] = {"reason": candidates[-1].get("reason") or "执行失败", "sql": sql}
        _write_trace(tid, result, final_sql=sql, validation={"candidates": candidates})
        return result

    result.update(
        {
            "sql": exec_result["sql"],
            "columns": exec_result["columns"],
            "rows": exec_result["rows"][:200],  # 界面展示用
            "rows_full": exec_result["rows"],  # 评测用（避免展示截断污染 EX）
            "row_count": len(exec_result["rows"]),
            "truncated": exec_result["truncated"],
            "chart": recommend(exec_result["columns"], exec_result["rows"]),
        }
    )
    _write_trace(tid, result, final_sql=exec_result["sql"], validation={"candidates": candidates})
    return result


def _write_trace(tid: str, result: dict, final_sql: str | None, validation: dict) -> None:
    trace = {
        "trace_id": tid,
        "question": result["question"],
        "clarification": result["clarification"],
        "candidates": validation.get("candidates", []),
        "final_sql": final_sql,
        "validation": validation,
        "attempts": result["attempts"],
        "row_count": result["row_count"],
        "truncated": result["truncated"],
        "elapsed_ms": result["timings_ms"].get("total"),
        "timings_ms": result["timings_ms"],
        "model": sqlgen.MODEL_MAIN,
        "effort": "none",
        "semantic_version": semantic_layer().get("version"),
        "metrics_used": result["metrics_used"],
        "rejected": result["rejected"],
    }
    _trace_path(tid).write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")


def load_trace(tid: str) -> dict | None:
    p = _trace_path(tid)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
