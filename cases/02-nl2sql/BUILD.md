# BUILD · 启动与故障处理

> 面向第一次跑这个 demo 的人。全程 PowerShell，约 1 分钟。

## 1. 环境

- Python 3.12（`python --version`）
- 依赖：`fastapi uvicorn httpx pydantic`（已在本机环境）
- 模型网关：magpie `http://127.0.0.1:3425`（`.env` 可改）

## 2. 四步启动

```powershell
cd project\02-nl2sql

# ① 生成库（确定性，约 3 秒）
python -m scripts.gen_db

# ② 数据完整性断言（11 项，必须全 PASS）
python -m scripts.verify_db

# ③ 起服务
python -m src.server          # → http://127.0.0.1:4181

# ④ 冒烟（另开一个终端）
python -m scripts.smoke
```

## 3. 评测（不依赖服务）

```powershell
python -m eval.run_eval              # 主集 150（EX 全自动，约 10 分钟）
python -m eval.run_eval --anchors    # 锚点集 20
python -m eval.run_eval --ambiguity  # 歧义集 15（反问率）
python -m eval.run_eval --limit 5    # 冒烟
```

## 4. 安全栅自检

```powershell
python -m scripts.test_safety        # 12 条对抗用例，必须全 PASS
```

## 5. 故障表

| 现象 | 原因 | 处理 |
|---|---|---|
| `端口 4181 被占用` | 旧进程未退 | 改 `.env` 的 `PORT`，或 `Get-Process python \| Stop-Process` |
| `库不存在` / health 显示 db_exists=false | 没跑 ① | `python -m scripts.gen_db` |
| `verify_db` 有 FAIL | 库被改过 | 删 `data/aicoding.db` 重跑 ①（seed 固定，结果一致） |
| 全部问题都被拒 | authorizer 白名单与表名不一致 | 检查 `src/db.py: ALLOWED_TABLES` |
| 所有查询超时 | 网关慢 + 首次加载 | 重试；或把 `.env` 的 `QUERY_TIMEOUT_S` 调大 |
| `生成失败：LLMError` | magpie 不可达或模型名错 | 先 `curl http://127.0.0.1:3425/v1/models` |
| 问题被判"歧义"不回答 | 阻塞式歧义（营收/近三月） | 在问题里写清口径，如"应收（含调整）" |

## 6. 降级边界（如实说明）

- 本 demo **不承诺**：完全离线、写操作、跨库、多轮质量。
- 嵌入/重排未使用；若表数增至 30+ 才需要 schema 检索。
- 数据为**完全虚构**，不可用于任何对外口径引用。
