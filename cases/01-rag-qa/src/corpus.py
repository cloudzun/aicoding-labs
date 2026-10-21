"""语料解析与切分。

切分策略（见 SPEC §5）：以「第X条」为最小单位；单条过长按句号二次切分；
chunk_id 按文档内条款出现顺序编号，保证可复现。
"""

from __future__ import annotations

import re
from pathlib import Path

from .core import CORPUS, INDEX, sha256_text, write_jsonl

CLAUSE_RE = re.compile(r"^\s*(第[一二三四五六七八九十百零〇\d]+条)\s*")
META_RE = re.compile(r"^>\s*([^：:]+)[：:]\s*(.+?)\s*$")
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
MAX_CLAUSE_CHARS = 800
MIN_MERGE_CHARS = 24
# 登记表/清单类文件不是制度正文，不参与索引（否则会把埋点表当制度答出来）
SKIP_STEMS = {"EMBEDDED_CASES", "MANIFEST", "README", "INDEX", "CHANGELOG"}


def _read_text(path: Path) -> tuple[list[tuple[int | None, str]], str]:
    """返回 [(page, line), ...] 与 doc_title。"""
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        raw = path.read_text(encoding="utf-8", errors="replace")
        title = ""
        for line in raw.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        return [(None, line) for line in raw.splitlines()], title

    if suffix == ".pdf":
        import fitz  # PyMuPDF

        lines: list[tuple[int | None, str]] = []
        title = ""
        with fitz.open(path) as doc:
            for pno, page in enumerate(doc, start=1):
                for line in page.get_text("text").splitlines():
                    lines.append((pno, line))
                    if not title and line.strip():
                        title = line.strip()[:80]
        return lines, title

    if suffix == ".docx":
        try:
            import docx  # python-docx
        except ImportError as exc:  # 明确报错，不静默跳过
            raise RuntimeError("解析 .docx 需要 python-docx，请先 `pip install python-docx`") from exc
        d = docx.Document(str(path))
        lines = [(None, p.text) for p in d.paragraphs]
        title = lines[0][1].strip() if lines else ""
        return lines, title

    raise RuntimeError(f"不支持的文档类型：{path.suffix}")


def parse_document(path: Path, doc_dir: str) -> dict:
    lines, title = _read_text(path)
    doc_id = path.stem
    meta: dict[str, str] = {}
    blocks: list[dict] = []
    section = ""
    current: dict | None = None
    seen_clause = False  # 修订 F01：元数据是否已结束，改用"是否已出现条款"判断，不用 not blocks

    for page, raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("<!--"):
            continue

        # 修订 F01：一级标题只是文档标题，不能进 blocks（否则后续元数据永远解析不到）
        if stripped.startswith("# ") and not stripped.startswith("## "):
            if not title:
                title = stripped[2:].strip()
            continue

        m = META_RE.match(stripped)
        if m and not seen_clause:
            key, value = m.group(1).strip(), m.group(2).strip()
            if key in {"文号", "发布部门", "发布日期", "生效日期", "状态", "密级"}:
                meta[key] = value
            continue

        h = HEADING_RE.match(stripped)
        if h:
            section = h.group(1).strip()
            current = None
            continue

        if not stripped:
            continue

        cm = CLAUSE_RE.match(stripped)
        if cm:
            seen_clause = True
            current = {
                "clause_no": cm.group(1),
                "section": section,
                "page": page,
                "text": stripped,
            }
            blocks.append(current)
            continue

        if current is not None:
            if len(current["text"]) < MAX_CLAUSE_CHARS:
                current["text"] = current["text"] + "\n" + stripped
            else:  # 超长条款另起一段，仍归属同一 clause_no
                current = {
                    "clause_no": current["clause_no"],
                    "section": section,
                    "page": page,
                    "text": stripped,
                }
                blocks.append(current)
        elif seen_clause:
            # 条款之间的散落文字保留；条款之前的序言/目录不进索引（修订 F01）
            blocks.append({"clause_no": "", "section": section, "page": page, "text": stripped})

    if not blocks:
        raise RuntimeError(f"{path.name} 未解析出任何条款，可能是扫描件或非文本 PDF")

    return {
        "doc_id": doc_id,
        "title": title or doc_id,
        "doc_dir": doc_dir,
        "meta": meta,
        "blocks": blocks,
    }


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CLAUSE_CHARS * 1.4:
        return [text]
    sentences = re.split(r"(?<=[。；])", text)
    parts: list[str] = []
    buf = ""
    for s in sentences:
        if len(buf) + len(s) > MAX_CLAUSE_CHARS and buf:
            parts.append(buf)
            buf = s
        else:
            buf += s
    if buf:
        parts.append(buf)
    return parts


def chunk_document(doc: dict, status_override: str | None = None) -> list[dict]:
    chunks: list[dict] = []
    seq = 0
    for block in doc["blocks"]:
        text = block["text"].strip()
        if len(text) < MIN_MERGE_CHARS and chunks:
            chunks[-1]["text"] = chunks[-1]["text"] + "\n" + text
            chunks[-1]["char_count"] = len(chunks[-1]["text"])
            continue
        for part in _split_long(text):
            seq += 1
            chunks.append(
                {
                    "chunk_id": f"{doc['doc_id']}#c{seq:03d}",
                    "doc_id": doc["doc_id"],
                    "doc_title": doc["title"],
                    "category": doc["meta"].get("发布部门", ""),
                    "status": status_override or doc["meta"].get("状态", ""),
                    "effective_date": doc["meta"].get("生效日期", ""),
                    "doc_number": doc["meta"].get("文号", ""),
                    "corpus": doc["doc_dir"],
                    "section": block.get("section", ""),
                    "clause_no": block.get("clause_no", ""),
                    "page": block.get("page"),
                    "text": part.strip(),
                    "char_count": len(part.strip()),
                }
            )

    for i, c in enumerate(chunks):
        c["prev_id"] = chunks[i - 1]["chunk_id"] if i > 0 else None
        c["next_id"] = chunks[i + 1]["chunk_id"] if i + 1 < len(chunks) else None
    return chunks


def iter_corpus_files() -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for sub in ("synthetic", "public"):
        d = CORPUS / sub
        if not d.exists():
            continue
        for p in sorted(d.iterdir()):
            if p.suffix.lower() not in {".md", ".txt", ".pdf", ".docx"}:
                continue
            # 登记表/清单类文件不是制度正文，不能进索引（否则会把埋点表当制度答出来）
            if p.name.startswith("_") or p.stem.upper() in SKIP_STEMS:
                continue
            files.append((p, sub))
    return files


def build_chunks() -> list[dict]:
    all_chunks: list[dict] = []
    for path, sub in iter_corpus_files():
        doc = parse_document(path, sub)
        all_chunks.extend(chunk_document(doc))
    return all_chunks


def corpus_fingerprint(chunks: list[dict]) -> str:
    joined = "\n".join(c["chunk_id"] + "|" + c["text"] for c in chunks)
    return sha256_text(joined)


if __name__ == "__main__":
    chunks = build_chunks()
    write_jsonl(INDEX / "chunks.jsonl", chunks)
    print(f"chunks={len(chunks)} fingerprint={corpus_fingerprint(chunks)[:12]}")
