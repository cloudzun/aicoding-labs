"""报告装配：固定 schema（客户要的结构化报告）+ 覆盖率与未检出显式标注。"""

from __future__ import annotations

from datetime import datetime

from .engine import SEV_ORDER


def build_report(parsed: dict, findings: list[dict], rules: dict, meta: dict) -> dict:
    order = sorted(findings, key=lambda f: (-SEV_ORDER.get(f["level"], 0), f["rule_id"]))
    summary = {"高": 0, "中": 0, "低": 0, "必查缺失": 0}
    for f in order:
        if f["violated"]:
            summary[f["level"]] = summary.get(f["level"], 0) + 1
            if f["category"] in ("缺失型", "存在型"):
                summary["必查缺失"] += 1

    # 按规则注册表对账：未出现在 findings 里的规则（如关闭语义执行）必须显式列为未取得依据
    reported = {f["rule_id"] for f in findings}
    not_detected = [f["rule_id"] for f in order if not f["detected"]]
    not_detected += [r["id"] for r in rules["rules"] if r["id"] not in reported]
    not_detected = sorted(set(not_detected))
    return {
        "contract_id": parsed.get("name", "").replace(".docx", ""),
        "file": parsed["name"],
        "pages_estimated": parsed["pages_estimated"],
        "n_paras": parsed["n_paras"],
        "summary": summary,
        "findings": [
            {
                "rule_id": f["rule_id"],
                "title": f["name"],
                "category": f["category"],
                "level": f["level"],
                "violated": f["violated"],
                "detected": f["detected"],
                "locator": f["locator"],
                "evidence": f["evidence"],
                "reason": f["reason"],
                "remediation": f["remediation"],
                "detector": f["detector"],
            }
            for f in order
            if f["violated"] or not f["detected"]
        ],
        "coverage": {
            "rules_total": len(rules["rules"]),
            "rules_checked": len([f for f in order if f["detected"]]),
            "not_detected": not_detected,
            "note": "not_detected 表示未取得判定依据，**不等于合规**",
        },
        "meta": {
            "rule_version": rules.get("version", ""),
            "model": meta.get("model", ""),
            "semantic_model": meta.get("semantic_model", ""),
            "elapsed_ms": meta.get("elapsed_ms"),
            "timings_ms": meta.get("timings_ms", {}),
            "reviewed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    }
