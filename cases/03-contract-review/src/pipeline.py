"""编排：解析 → 确定性规则 → 语义规则 → 报告。"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from . import engine, semantic
from .llm import MODEL_MAIN, MODEL_SEMANTIC
from .parse import parse_docx
from .report import build_report

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "data" / "contracts"
TRACES = ROOT / "data" / "traces"


def list_contracts() -> list[dict]:
    out = []
    for p in sorted(CONTRACTS.glob("*.docx")):
        out.append({"contract_id": p.stem, "file": p.name, "size_kb": round(p.stat().st_size / 1024, 1)})
    return out


def review(path: str | Path, rules: dict | None = None, with_semantic: bool = True) -> dict:
    t0 = time.perf_counter()
    rules = rules or engine.load_rules()
    parsed = parse_docx(path)
    t_parse = int((time.perf_counter() - t0) * 1000)

    t1 = time.perf_counter()
    findings = engine.detect_deterministic(rules, parsed)
    t_det = int((time.perf_counter() - t1) * 1000)

    t2 = time.perf_counter()
    findings += semantic.judge_semantic(rules["rules"], parsed) if with_semantic else []
    t_sem = int((time.perf_counter() - t2) * 1000)

    rid = "rv" + uuid.uuid4().hex[:12]
    report = build_report(
        parsed, findings, rules,
        {
            "model": MODEL_MAIN,
            "semantic_model": MODEL_SEMANTIC if with_semantic else "",
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "timings_ms": {"parse": t_parse, "deterministic": t_det, "semantic": t_sem},
        },
    )
    report["review_id"] = rid

    TRACES.mkdir(parents=True, exist_ok=True)
    import json

    (TRACES / f"{rid}.json").write_text(
        json.dumps({"review_id": rid, "report": report, "findings_all": findings}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report
