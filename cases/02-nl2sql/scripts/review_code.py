"""独立评审 v3：小分片（~1600 字符）+ 多模型回退 + 空响应重试。

实测（见本轮控制台）：deepseek/sol 在输入 >~1.5k 字符时返回空；glm/kimi 在 2k 可用、5k 不稳；
luna（被测模型）稳定但不能自评。故用 glm-5.3 为主、kimi-k3 回退、luna 末位兜底，切片送审。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.llm import chat  # noqa: E402

FILES = ["src/safety.py", "src/pipeline.py", "src/sqlgen.py", "eval/run_eval.py", "scripts/build_gold.py", "src/chart.py"]
MODELS = ["opencode-go/glm-5.3", "opencode-go/kimi-k3"]
CHUNK = 1600

HEAD = """你在做代码安全评审。只输出发现，格式：[严重度] 位置 — 问题 — 修法。严重度 Critical/High/Medium/Low。没有真问题就输出 NONE。

背景：NL2SQL demo，四道安全闸 = 只读连接 + SQLite authorizer 表白名单 + 外层 LIMIT 包装 + progress_handler 超时。"""


def slice_file(text: str) -> list[str]:
    parts, i = [], 0
    while i < len(text):
        parts.append(text[i : i + CHUNK])
        i += CHUNK - 200
    return parts


def ask(chunk: str, fname: str, idx: int) -> str:
    for model in MODELS:
        for _ in range(2):
            try:
                r = chat(
                    [{"role": "user", "content": f"{HEAD}\n\n===== {fname} 片段 {idx} =====\n{chunk}"}],
                    model=model,
                    effort="none",
                    max_tokens=500,
                    timeout_s=120,
                )
                if r["content"].strip():
                    return f"[{model}] {r['content'].strip()}"
            except Exception:  # noqa: BLE001
                continue
    return ""


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_chunks = []
    empty = 0
    for rel in FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        pieces = slice_file(text)
        got = []
        for i, piece in enumerate(pieces):
            r = ask(piece, rel, i)
            if not r:
                empty += 1
                got.append(f"- 片段 {i}：空响应（未获发现）")
            else:
                got.append(r)
        valid = sum(1 for g in got if not g.startswith("- "))
        print(f"  {rel:24s} {len(pieces)} 片，有效 {valid}")
        out_chunks.append(f"\n## {rel}\n\n" + "\n".join(f"- {g}" for g in got) + "\n")

    doc = f"""# 独立评审记录（NL2SQL）

> 评审方：`opencode-go/glm-5.3`（主）、`kimi-k3`（回退）；与被测 `gpt-6-luna` 不同家族
> 生成时间：{stamp}　方式：**1600 字符分片 + 空响应重试**
> 局限：① 本机无 codex CLI，非沙箱执行；② 评审方只读静态阅读，不运行代码；③ 长输入下多模型返回空（实测），故分片
> 空响应片段数：{empty}
{''.join(out_chunks)}
"""
    ev = ROOT / "evidence" / f"review-{stamp}.md"
    ev.write_text(doc, encoding="utf-8")
    print(f"\n[evidence] {ev}（{len(doc)} 字符，空响应 {empty} 片）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
