"""claim 级引用支撑校验（SPEC v0.2 / AC-11）。

方法：把答案按句切分，对每个带引用编号的句子，与所引 chunk 做**字符 3-gram Jaccard**，
低于阈值即记为 unsupported_claim。

诚实边界（会审 E1-02）：
- 这是**下限指标**：只能发现"明显没有任何字面支撑"的引用，不能证明"引用在语义上支持该论断"。
- 改写、同义替换、语序调整会降低重叠度，因此阈值取宽松值 0.15，宁可少报不可误杀。
- 真正的 claim-level 校验需要独立 judge 或 NLI 模型，属下一轮（R-05 完整版）。
"""

from __future__ import annotations

import re

CITE_RE = re.compile(r"\[\s*[cC]\s*(\d+)\s*\]")
SENT_SPLIT = re.compile(r"(?<=[。；！？\n])")
DEFAULT_THRESHOLD = 0.15


def grams(text: str, n: int = 3) -> set[str]:
    chars = [c for c in text if not c.isspace()]
    if len(chars) < n:
        return {"".join(chars)} if chars else set()
    return {"".join(chars[i : i + n]) for i in range(len(chars) - n + 1)}


def check_claims(answer: str, sources: list[dict], threshold: float = DEFAULT_THRESHOLD) -> dict:
    """返回 {claims:[...], unsupported:[...], support_rate: float, cited_sentences: int}

    实现要点（v2 修复）：以引用编号为锚点，**回看**它前面最近的句子作为论断，
    而不是按句号切分后再找引用——否则 "[c01]" 常被切到下一段，导致论断为空、重叠度恒为 0。
    """
    by_idx = {s["idx"]: s for s in sources}
    claims: list[dict] = []
    cursor = 0
    for m in CITE_RE.finditer(answer):
        seg = answer[cursor : m.start()]
        cursor = m.end()
        parts = [x.strip() for x in SENT_SPLIT.split(seg) if x.strip()]
        body = parts[-1] if parts else seg.strip()
        idx = f"c{int(m.group(1)):02d}"

        # 连续引用（[c01][c02]）并入上一条 claim
        if not grams(body) and claims and claims[-1]["ok"] is not None:
            if idx not in claims[-1]["cited"]:
                claims[-1]["cited"].append(idx)
                src = by_idx.get(idx)
                if src:
                    g_prev = grams(claims[-1]["sentence"])
                    sg = grams(src["chunk"]["text"])
                    if g_prev and sg:
                        j = len(g_prev & sg) / len(g_prev | sg)
                        if j > claims[-1]["best_overlap"]:
                            claims[-1]["best_overlap"] = round(j, 3)
                            claims[-1]["matched"] = idx
                            claims[-1]["ok"] = j >= threshold
            continue

        g = grams(body)
        best, best_idx = 0.0, None
        for cand in [idx]:
            src = by_idx.get(cand)
            if not src or not g:
                continue
            sg = grams(src["chunk"]["text"])
            if not sg:
                continue
            j = len(g & sg) / len(g | sg)
            if j > best:
                best, best_idx = j, cand
        claims.append(
            {
                "sentence": (body or "[仅引用]")[:160],
                "cited": [idx],
                "best_overlap": round(best, 3),
                "matched": best_idx,
                "ok": bool(g) and best >= threshold,
            }
        )

    unsupported = [c for c in claims if not c["ok"]]
    total = len(claims)
    return {
        "claims": claims,
        "unsupported": unsupported,
        "cited_sentences": total,
        "support_rate": round(1 - len(unsupported) / total, 4) if total else None,
        "threshold": threshold,
        "method": "char3gram_jaccard",
    }
