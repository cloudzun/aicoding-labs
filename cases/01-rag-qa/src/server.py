"""FastAPI 服务：SSE 流式问答 + 静态前端 + trace 查询。

启动：python -m src.server   （默认 http://127.0.0.1:4180）
"""

from __future__ import annotations

import json
import socket
import sys
import threading

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .core import CACHE, INDEX, PORT, WEB, ensure_dirs, now_iso
from .rag import answer_stream, load_trace
from .vector import Embedder, Index, load_index

ensure_dirs()

app = FastAPI(title="政企制度问答 demo", version="1.0.0")

_state: dict = {"index": None, "embedder": None, "error": None, "built_at": None}


def _init_state() -> None:
    try:
        _state["index"] = load_index()
        _state["embedder"] = Embedder()
        _state["error"] = None
        meta_path = INDEX / "meta.json"
        if meta_path.exists():
            _state["built_at"] = json.loads(meta_path.read_text(encoding="utf-8")).get("built_at")
    except Exception as exc:  # noqa: BLE001
        _state["error"] = f"{type(exc).__name__}: {exc}"


_init_state()


class ChatIn(BaseModel):
    question: str
    history: list[dict] = []


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/health")
def health() -> dict:
    idx = _state["index"]
    stats = idx.stats() if idx else {}
    return {
        "ok": _state["error"] is None,
        "error": _state["error"],
        "index": stats,
        "built_at": _state["built_at"],
        "embed_cache_entries": _cache_size(),
        "time": now_iso(),
    }


def _cache_size() -> int:
    p = CACHE / "embeddings.jsonl"
    if not p.exists():
        return 0
    with p.open("rb") as fh:
        return sum(1 for _ in fh)


@app.post("/api/chat")
def chat(body: ChatIn):
    if _state["error"]:
        raise HTTPException(status_code=503, detail=f"服务未就绪：{_state['error']}")
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    def gen():
        try:
            for evt in answer_stream(body.question.strip(), _state["index"], _state["embedder"], body.history):
                if evt["type"] == "meta":
                    yield _sse("meta", evt["meta"])
                elif evt["type"] == "delta":
                    yield _sse("delta", {"text": evt["text"]})
                elif evt["type"] == "done":
                    payload = {k: v for k, v in evt.items() if k != "type"}
                    yield _sse("done", payload)
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"error": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


_TRACE_ID_RE = __import__("re").compile(r"^t[0-9a-f]{8,32}$")


@app.get("/api/trace/{trace_id}")
def trace(trace_id: str) -> dict:
    # F08：白名单校验，阻断 Windows 反斜杠路径穿越
    if not _TRACE_ID_RE.match(trace_id):
        raise HTTPException(status_code=400, detail="trace_id 非法")
    data = load_trace(trace_id)
    if data is None:
        raise HTTPException(status_code=404, detail="trace 不存在")
    return data


@app.get("/")
def home() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def main() -> int:
    if not _port_free(PORT):
        print(f"[错误] 端口 {PORT} 已被占用。请关闭占用进程，或在 .env 里改 PORT。")
        return 1
    if _state["error"]:
        print(f"[警告] 索引/嵌入未就绪：{_state['error']}")
        print("       请先运行 `python -m src.ingest` 建库。页面仍可打开，但问答会报 503。")
    print(f"[启动] http://127.0.0.1:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
