"""FastAPI 服务：合同列表 / 审查 / 上传 / 规则 / trace。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import engine, pipeline  # noqa: E402
from src.parse import parse_docx  # noqa: E402

PORT = int(__import__("os").environ.get("PORT", "4182"))
WEB = ROOT / "web"
UPLOADS = ROOT / "data" / "uploads"
TRACES = ROOT / "data" / "traces"
MAX_MB = 10
RID_RE = re.compile(r"^rv[0-9a-f]{8,16}$")

app = FastAPI(title="合同审查 demo", version="1.0.0")


class ReviewIn(BaseModel):
    contract_id: str
    with_semantic: bool = True


@app.get("/api/health")
def health() -> dict:
    rules = engine.load_rules()
    return {"ok": True, "contracts": len(pipeline.list_contracts()), "rules": len(rules["rules"]),
            "rule_version": rules["version"], "docx_only": True}


@app.get("/api/contracts")
def contracts() -> list[dict]:
    return pipeline.list_contracts()


@app.get("/api/contract/{contract_id}/text")
def contract_text(contract_id: str) -> dict:
    """只读返回合同段落（供前端「合同原文」面板做定位）。

    2026-10-21 新增（用户批准）：不改审查逻辑，只把 parse_docx 的结果暴露出来。
    安全：只接受 CT\\d{3}，不返回服务器文件路径。
    """
    if not re.match(r"^CT\d{3}$", contract_id):
        raise HTTPException(status_code=400, detail="contract_id 非法（形如 CT001）")
    path = ROOT / "data" / "contracts" / f"{contract_id}.docx"
    if not path.exists():
        raise HTTPException(status_code=404, detail="合同不存在")
    parsed = parse_docx(path)
    return {
        "contract_id": contract_id,
        "file": parsed["name"],
        "n_paras": parsed["n_paras"],
        "pages_estimated": parsed["pages_estimated"],
        "pages_note": "页号按每页约 40 段估算，非真实排版分页",
        "paras": [{"idx": p["idx"], "page": p["page"], "text": p["text"]} for p in parsed["paras"]],
    }


@app.get("/api/rules")
def rules() -> dict:
    r = engine.load_rules()
    return {"version": r["version"], "rules": r["rules"]}


@app.post("/api/review")
def review(body: ReviewIn) -> dict:
    cid = (body.contract_id or "").strip()
    if not re.match(r"^CT\d{3}$", cid):
        raise HTTPException(status_code=400, detail="contract_id 非法（形如 CT001）")
    path = ROOT / "data" / "contracts" / f"{cid}.docx"
    if not path.exists():
        raise HTTPException(status_code=404, detail="合同不存在")
    return pipeline.review(path, with_semantic=body.with_semantic)


@app.post("/api/upload")
async def upload(file: UploadFile) -> dict:
    name = (file.filename or "").lower()
    if not name.endswith(".docx"):
        raise HTTPException(status_code=400, detail="v1 仅支持 .docx（PDF/扫描件不支持）")
    content = await file.read()
    if len(content) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"文件过大（>{MAX_MB}MB）")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    dst = UPLOADS / f"{Path(file.filename).stem[:40]}.docx"
    dst.write_bytes(content)
    return pipeline.review(dst)


@app.get("/api/report/{review_id}")
def get_report(review_id: str) -> dict:
    if not RID_RE.match(review_id):
        raise HTTPException(status_code=400, detail="review_id 非法")
    p = TRACES / f"{review_id}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="报告不存在")
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/")
def home() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


def main() -> int:
    print(f"[启动] http://127.0.0.1:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
