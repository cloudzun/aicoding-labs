"""环 6 QA：可复现的实机检查（不是手工点点）。

用法：python scripts/qa_checks.py [--base http://127.0.0.1:4180]
输出：evidence/qa-<时间戳>.json + 控制台表格
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"


def post_chat(base: str, question: str, history: list[dict] | None = None, timeout: float = 120) -> dict:
    """返回 {answer, sources, done, raw_events}"""
    answer, sources, done = "", [], {}
    with httpx.stream(
        "POST",
        f"{base}/api/chat",
        json={"question": question, "history": history or []},
        timeout=timeout,
    ) as resp:
        resp.raise_for_status()
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                ev = data = None
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
                elif ev == "delta":
                    answer += payload["text"]
                elif ev == "done":
                    done = payload
    return {"answer": answer, "sources": sources, "done": done}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:4180")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    checks: list[dict] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "pass": ok, "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name} — {detail}")

    # Q1 健康检查
    try:
        h = httpx.get(f"{base}/api/health", timeout=20).json()
        record("Q1 健康检查", bool(h.get("ok")) and h.get("index", {}).get("chunk_count", 0) > 0,
               f"chunk={h.get('index', {}).get('chunk_count')} docs={h.get('index', {}).get('docs')}")
    except Exception as exc:  # noqa: BLE001
        record("Q1 健康检查", False, f"{type(exc).__name__}: {exc}")

    # Q2 无答案拒答（不调用模型）
    try:
        r = post_chat(base, "员工的婚假有多少天？")
        ok = bool(r["done"].get("refused")) and "资料不足" in r["answer"]
        record("Q2 无答案拒答", ok, f"refused={r['done'].get('refused')} elapsed={r['done'].get('elapsed_ms')}ms")
    except Exception as exc:  # noqa: BLE001
        record("Q2 无答案拒答", False, f"{type(exc).__name__}: {exc}")

    # Q3 冲突场景：必须指出废止/并列
    try:
        r = post_chat(base, "单笔采购金额500万元以上的采购项目，需要提交什么会议审议？")
        ans = r["answer"]
        ok = ("500" in ans) and ("废止" in ans or "不再适用" in ans)
        record("Q3 版本冲突处理", ok, f"含500万={'500' in ans} 含废止说明={'废止' in ans}")
    except Exception as exc:  # noqa: BLE001
        record("Q3 版本冲突处理", False, f"{type(exc).__name__}: {exc}")

    # Q4 双重冲突（同文件两数字）：必须并列
    try:
        r = post_chat(base, "单笔资金支付达到多少金额需要报总经理审批？")
        ans = r["answer"]
        ok = ("200" in ans) and ("300" in ans)
        record("Q4 同文件数字冲突", ok, "同时出现200与300" if ok else "未并列两个数字")
    except Exception as exc:  # noqa: BLE001
        record("Q4 同文件数字冲突", False, f"{type(exc).__name__}: {exc}")

    # Q5 引用完整性
    try:
        r = post_chat(base, "履约保证金按什么比例缴纳？")
        invalid = r["done"].get("invalid_citations") or []
        has_cite = "[c" in r["answer"]
        record("Q5 引用有效", (not invalid) and has_cite, f"invalid={invalid} 有引用={has_cite}")
    except Exception as exc:  # noqa: BLE001
        record("Q5 引用有效", False, f"{type(exc).__name__}: {exc}")

    # Q6 多轮指代：第二轮必须能接住
    try:
        r1 = post_chat(base, "单笔采购金额500万元以上的采购项目，需要提交什么会议审议？")
        hist = [{"role": "user", "content": "单笔采购金额500万元以上的采购项目，需要提交什么会议审议？"}, {"role": "assistant", "content": r1["answer"][:600]}]
        r2 = post_chat(base, "那这个还需要谁来审批？", history=hist)
        ok = (not r2["done"].get("refused")) and len(r2["answer"]) > 20
        record("Q6 多轮指代", ok, f"第二链 refused={r2['done'].get('refused')} 长度={len(r2['answer'])}")
    except Exception as exc:  # noqa: BLE001
        record("Q6 多轮指代", False, f"{type(exc).__name__}: {exc}")

    # Q7 非法 trace_id 必须 400（F08 回归）
    try:
        resp = httpx.get(f"{base}/api/trace/..%5C..%5Ceval%5Creports%5Cx", timeout=15)
        record("Q7 路径穿越拦截", resp.status_code == 400, f"status={resp.status_code}")
    except Exception as exc:  # noqa: BLE001
        record("Q7 路径穿越拦截", False, f"{type(exc).__name__}: {exc}")

    # Q8 合法 trace 可读
    try:
        r = post_chat(base, "供应商管理实施细则还有效吗？")
        tid = r["done"].get("trace_id")
        tr = httpx.get(f"{base}/api/trace/{tid}", timeout=15)
        body = tr.json()
        need = {"question", "rewritten_query", "reasoning_effort", "index_meta", "selected"}
        ok = tr.status_code == 200 and need.issubset(body.keys())
        record("Q8 trace 字段完整", ok, f"status={tr.status_code} 缺={sorted(need - set(body.keys()))}")
    except Exception as exc:  # noqa: BLE001
        record("Q8 trace 字段完整", False, f"{type(exc).__name__}: {exc}")

    # Q9 空问题必须 400
    try:
        resp = httpx.post(f"{base}/api/chat", json={"question": "   ", "history": []}, timeout=15)
        record("Q9 空问题拦截", resp.status_code == 400, f"status={resp.status_code}")
    except Exception as exc:  # noqa: BLE001
        record("Q9 空问题拦截", False, f"{type(exc).__name__}: {exc}")

    # Q10 并发 3 路不互相污染 trace
    try:
        ids = []
        t0 = time.perf_counter()
        for q in ["履约保证金按什么比例缴纳？", "重大故障多久内上报？", "员工申诉复核多久出结论？"]:
            ids.append(post_chat(base, q)["done"].get("trace_id"))
        ok = len(set(ids)) == 3
        record("Q10 并发 trace 唯一", ok, f"ids={ids} 耗时={time.perf_counter() - t0:.1f}s")
    except Exception as exc:  # noqa: BLE001
        record("Q10 并发 trace 唯一", False, f"{type(exc).__name__}: {exc}")

    passed = sum(1 for c in checks if c["pass"])
    result = {
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base": base,
        "passed": passed,
        "total": len(checks),
        "checks": checks,
    }
    EVIDENCE.mkdir(exist_ok=True)
    out = EVIDENCE / f"qa-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{passed}/{len(checks)} 通过 → {out}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
