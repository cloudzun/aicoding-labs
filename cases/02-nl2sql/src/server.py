"""FastAPI 服务：POST /api/ask、GET /api/health、GET /api/trace/{id}。"""

from __future__ import annotations

import re
import socket
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import pipeline  # noqa: E402
from src.db import ALLOWED_TABLES, DB_PATH  # noqa: E402

def _port() -> int:
    """端口优先级：环境变量 PORT > .env 的 PORT > 4181。"""
    import os
    if "PORT" in os.environ:
        return int(os.environ["PORT"])
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("PORT="):
                return int(line.split("=", 1)[1].strip())
    return 4181


PORT = _port()
WEB = ROOT / "web"
TRACE_ID_RE = re.compile(r"^q[0-9a-f]{8,16}$")

app = FastAPI(title="政企 NL2SQL 问数 demo", version="1.0.0")


class AskIn(BaseModel):
    question: str
    clarify: bool = True


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": DB_PATH.exists(),
        "db": str(DB_PATH.name),
        "db_exists": DB_PATH.exists(),
        "tables": list(ALLOWED_TABLES),
        "semantic_version": __import__("json").loads((ROOT / "semantic_layer.json").read_text(encoding="utf-8"))["version"],
    }


@app.post("/api/ask")
def ask(body: AskIn) -> dict:
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="问题不能为空")
    if len(q) > 500:
        raise HTTPException(status_code=400, detail="问题过长（>500 字）")
    return pipeline.ask(q, clarify=body.clarify)


@app.get("/api/trace/{trace_id}")
def trace(trace_id: str) -> dict:
    if not TRACE_ID_RE.match(trace_id):
        raise HTTPException(status_code=400, detail="trace_id 非法")
    data = pipeline.load_trace(trace_id)
    if data is None:
        raise HTTPException(status_code=404, detail="trace 不存在")
    return data


@app.get("/")
def home() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


def _free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def main() -> int:
    if not _free(PORT):
        print(f"[错误] 端口 {PORT} 被占用，请在 .env 改 PORT")
        return 1
    print(f"[启动] http://127.0.0.1:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
