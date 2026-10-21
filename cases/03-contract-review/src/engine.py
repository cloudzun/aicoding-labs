"""确定性规则引擎：存在型 / 缺失型 / 数值型 / 结构性（27 条中 21 条）。

原则（复用 BP-2/BP-6）：
- 能确定性判的绝不交模型；
- 判不了要**显式标注 not_detected**，不能默认"合规"（避免假阴性被当成通过）。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .parse import find_para, locate_regex

ROOT = Path(__file__).resolve().parents[1]
SEV_ORDER = {"高": 3, "中": 2, "低": 1, "无": 0}


def load_rules(path: str | Path | None = None) -> dict:
    return yaml.safe_load((path or ROOT / "rules.yaml").read_text(encoding="utf-8"))


def _finding(rule: dict, violated: bool, detected: bool, evidence: str, loc: dict | None, reason: str) -> dict:
    level = rule["severity"] if violated else "无"
    return {
        "rule_id": rule["id"],
        "name": rule["name"],
        "category": rule["category"],
        "detector": "deterministic",
        "violated": violated,
        "detected": detected,
        "level": level,
        "evidence": evidence[:200],
        "locator": loc,
        "reason": reason,
        "remediation": rule.get("remediation", ""),
    }


HEADING_RE = re.compile(r"^第[一二三四五六七八九十百]+条\s*([^\n]{0,24})")


def heading_part(text: str) -> str:
    """只取"标题部分"：有『第X条』则取其后到换行；否则取首行前 24 字。

    诊断结论：原实现扫整段，导致『第二十条 对等责任 / 双方违约责任对等…』里的正文
    『违约责任』被当成标题命中，7 条缺失型漏报全部由此产生。
    """
    m = HEADING_RE.match(text)
    if m:
        return m.group(1).strip()
    return text.split("\n", 1)[0][:24]


def detect_present(rule: dict, parsed: dict) -> dict:
    """存在型/缺失型：以**条款标题**为主判据，关键词仅作兜底。

    背景（本轮实测）：只用关键词会把『保密期限』当成『合同期限』、把『收到发票后付款』
    当成『付款方式』，导致缺失型条款被误判为存在（recall 25%）。
    """
    heading = rule.get("heading")
    if heading:
        aliases = [heading] + list(rule.get("heading_aliases") or [])
        for p in parsed["paras"]:
            hp = heading_part(p["text"])
            for kw in aliases:
                if kw and kw in hp:
                    loc = {"page": p["page"], "para": p["idx"], "char_offset": p["text"].find(kw), "quote": p["text"][:200]}
                    return _finding(rule, False, True, p["text"], loc, f"标题命中：{kw}")
        return _finding(rule, True, True, "", None, f"未找到条款标题『{heading}』（条款可能缺失）")

    hits = [k for k in rule.get("keywords", []) if k in parsed["full_text"]]
    if hits:
        loc = find_para(parsed, hits[0])
        return _finding(rule, False, True, loc["quote"] if loc else "", loc, f"检出关键词：{hits[0]}")
    return _finding(rule, True, True, "", None, f"未检出任何关键词：{'/'.join(rule.get('keywords', []))}")


def detect_limit(rule: dict, parsed: dict) -> dict:
    """数值型：抽第一个数值与阈值比较；匹配不到则显式 not_detected。"""
    pattern = re.compile(rule["pattern"])
    loc = locate_regex(parsed, pattern)
    if not loc:
        return _finding(rule, False, False, "", None, "未能从文本中抽到指标值（not_detected）")
    m = re.search(rule["pattern"], loc["quote"])
    if not m:
        return _finding(rule, False, False, "", loc, "抽到段但无法解析数值（not_detected）")
    raw_val = next((g for g in m.groups() if g), None)
    try:
        value = float(raw_val)
    except (TypeError, ValueError):
        return _finding(rule, False, False, "", loc, "数值解析失败（not_detected）")
    ok = value >= rule["threshold"] if rule.get("op", ">=") == ">=" else value <= rule["threshold"]
    reason = f"实测 {value}{rule.get('unit', '')}，阈值 {rule.get('op', '>=')} {rule['threshold']}{rule.get('unit', '')}"
    return _finding(rule, not ok, True, loc["quote"], loc, reason)


def detect_structure(rule: dict, parsed: dict) -> dict:
    if rule["id"] == "R26":
        head = "\n".join(p["text"] for p in parsed["paras"][:6])
        need = ["甲方", "乙方", "地址", "联系人"]
        missing = [k for k in need if k not in head]
        if missing:
            return _finding(rule, True, True, head[:150], {"page": 1, "para": parsed["paras"][0]["idx"], "char_offset": 0, "quote": head[:150]},
                            f"主体信息缺：{'/'.join(missing)}")
        return _finding(rule, False, True, head[:100], None, "主体信息齐全")
    if rule["id"] == "R27":
        sign = re.search(r"签署日期[：:]\s*(\d{4}-\d{2}-\d{2})", parsed["full_text"])
        eff = re.search(r"生效日期[：:]\s*(\d{4}-\d{2}-\d{2})", parsed["full_text"])
        if not sign or not eff:
            return _finding(rule, False, False, "", None, "未找到签署/生效日期（not_detected）")
        same = sign.group(1) == eff.group(1)
        loc = find_para(parsed, "签署日期")
        return _finding(rule, not same, True, loc["quote"] if loc else "", loc,
                        f"签署 {sign.group(1)} / 生效 {eff.group(1)}")
    return _finding(rule, False, False, "", None, "未实现的结构检查（not_detected）")


CLAUSE_NO_RE = re.compile(r"^第([一二三四五六七八九十百]+)条")


def infer_missing_locator(parsed: dict, expected_heading: str) -> dict:
    """为"缺失型"发现推断应出现位置：找最近的相邻条款，返回"位于第X条与第Y条之间"。"""
    numbered = [(p, CLAUSE_NO_RE.match(p["text"])) for p in parsed["paras"]]
    numbered = [(p, m) for p, m in numbered if m]
    if not numbered:
        return {"page": 1, "para": None, "char_offset": 0, "quote": "", "inferred": True,
                "note": "无条款编号，无法推断位置"}
    # 缺失项一般排在"违约/争议/签署"类附近；这里用最接近的末尾条款做锚点，明确标注 inferred
    anchor = numbered[-1][0]
    return {
        "page": anchor["page"],
        "para": anchor["idx"],
        "char_offset": 0,
        "quote": anchor["text"][:120],
        "inferred": True,
        "note": f"『{expected_heading}』条款缺失，位置为推断（参照{anchor['text'][:16]}）",
    }


def detect_deterministic(rules: dict, parsed: dict) -> list[dict]:
    out: list[dict] = []
    for rule in rules["rules"]:
        if rule.get("detector") != "deterministic":
            continue
        expect = rule["expect"]
        if expect == "present":
            f = detect_present(rule, parsed)
            if f["violated"]:
                f["locator"] = infer_missing_locator(parsed, rule.get("heading", rule["name"]))
            out.append(f)
        elif expect == "limit":
            out.append(detect_limit(rule, parsed))
        elif expect == "structure":
            out.append(detect_structure(rule, parsed))
    return out
