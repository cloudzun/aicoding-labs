"""docx 解析：段落级定位（页号以估算给出，偏移为段内字符偏移）。

设计取舍（与 ① 一致：先做能判定的，不承诺做不到的）：
- 只支持 .docx；PDF/扫描件 v1 明确不支持，避免"解析质量污染全部指标"。
- 定位单位是**段落 + 段内字符偏移**，可回查；页号按每页约 40 段估算并标注 estimated。
"""

from __future__ import annotations

from pathlib import Path

from docx import Document

PARAS_PER_PAGE = 40


def parse_docx(path: str | Path) -> dict:
    doc = Document(str(path))
    paras = []
    for i, p in enumerate(doc.paragraphs):
        text = (p.text or "").strip()
        if not text:
            continue
        paras.append({"idx": i, "text": text, "page": i // PARAS_PER_PAGE + 1})
    full = "\n".join(x["text"] for x in paras)
    return {
        "path": str(path),
        "name": Path(path).name,
        "paras": paras,
        "full_text": full,
        "n_paras": len(paras),
        "pages_estimated": max(1, len(paras) // PARAS_PER_PAGE + 1),
    }


def find_para(parsed: dict, keyword: str) -> dict | None:
    for p in parsed["paras"]:
        if keyword in p["text"]:
            off = p["text"].find(keyword)
            return {"page": p["page"], "para": p["idx"], "char_offset": off, "quote": p["text"][:200]}
    return None


def locate_regex(parsed: dict, pattern) -> dict | None:
    for p in parsed["paras"]:
        m = pattern.search(p["text"])
        if m:
            return {
                "page": p["page"],
                "para": p["idx"],
                "char_offset": m.start(),
                "quote": p["text"][:200],
                "match": m.group(0),
            }
    return None
