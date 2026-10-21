"""对话冒烟测试：对运行中的服务发起问题，打印来源、答案与耗时。

用法：python scripts/smoke_chat.py "问题1" "问题2" ...
"""

from __future__ import annotations

import json
import sys

import httpx

BASE = "http://127.0.0.1:4180"


def ask(question: str) -> None:
    print("=" * 78)
    print("Q:", question)
    sources: list[dict] = []
    answer = ""
    done: dict = {}
    with httpx.stream(
        "POST", f"{BASE}/api/chat", json={"question": question, "history": []}, timeout=120
    ) as resp:
        resp.raise_for_status()
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                ev, data = None, None
                for line in block.splitlines():
                    if line.startswith("event:"):
                        ev = line[6:].strip()
                    elif line.startswith("data:"):
                        data = line[5:].strip()
                if not ev or data is None:
                    continue
                payload = json.loads(data)
                if ev == "meta":
                    sources = payload.get("sources", [])
                    print(f"-- 检索 max_score={payload.get('max_score')} 耗时={payload.get('retrieval_ms')}ms")
                    for s in sources:
                        print(f"   [{s['idx']}] {s['doc_title'][:20]} {s['clause_no']} score={s['score']} {s['status']}")
                elif ev == "delta":
                    answer += payload["text"]
                elif ev == "done":
                    done = payload
                elif ev == "error":
                    print("!! error:", payload)
    print("-- 答案 --")
    print(answer)
    print(
        f"-- 指标 refused={done.get('refused')} timed_out={done.get('timed_out')} "
        f"ttft={done.get('ttft_ms')}ms elapsed={done.get('elapsed_ms')}ms "
        f"invalid={done.get('invalid_citations')}"
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    for q in sys.argv[1:]:
        ask(q)
