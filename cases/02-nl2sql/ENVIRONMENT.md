# ENVIRONMENT · 环境基线（NL2SQL）

> 本文件是证据，不是说明书。能力项均有实测记录（`evidence/`）。
> **锁定项：** GStack `1.91.121.0`｜Python 3.12.10｜SQLite（stdlib）｜端口 `4181`｜模型 `opencode-go/gpt-6-luna`（`reasoning_effort=none`）

## 0. 依赖与运行环境

> 2026-10-21 补齐（HANDOFF §4 冻结项"环境写入 ENVIRONMENT.md"；此前本节缺失）。

| 项 | 值 | 说明 |
|---|---|---|
| Python | 3.12.10（3.12.x 均可） | 纯 Python，无容器、无 GPU |
| 依赖清单 | `requirements.txt`（本目录） | 按实际 import 冻结：`fastapi` `uvicorn` `httpx` `pydantic`；数据库用 stdlib `sqlite3` |
| 安装 | `pip install -r requirements.txt` | 版本为 2026-10-21 本机现网，非全量 `pip freeze` |
| 模型网关 | magpie `http://127.0.0.1:3425`，`Authorization: Bearer <MAGPIE_KEY>` | 生成与嵌入都走它；**网关不可用时无法生成 SQL** |
| 配置 | `.env`（本地，不提交）；模板 `.env.example` | 模板中密钥已占位为 `<MAGPIE_KEY>` |
| 端口 | `4181` | `PORT=4181` |
| 模型名 | 生成 `opencode-go/gpt-6-luna`；推理 `opencode-go/deepseek-v4.1-flash` | 见 `.env` |

## 1. 能力矩阵

| 能力 | 来源 | 状态 | 说明 |
|---|---|---|---|
| 生成（SQL） | magpie `/v1/chat/completions` | ✅ | 实测 p50 1.5–4.6s（含检索/排队波动），选 luna 最快 |
| 结构化输出 | magpie | ⚠️ | `/v1/systemone` 需 Jev provider，本机不可用；改用"提示词约束 + 正则提取 + 校验" |
| 嵌入 | magpie Qwen3-Embedding-4B | ✅ 可用但**本 demo 未使用** | 6 张表全量 schema 约 1.5k token，直接进 prompt 更可靠 |
| 数据库 | 本地 SQLite 文件 | ✅ | `data/aicoding.db`，8,584 行，sha256 `d1f5872e…`（2026-10-21 客户名改造后重冻结） |
| 容器/GPU | — | ❌ | 无（本机直跑，CPU 足够） |

**关键判断：本项目不需要 RAG。** 表少、schema 小、语义层可穷举——全量 schema + 语义层入 prompt 比"检索式 schema linking"更稳，也少一个故障点。若表数 >30 再考虑 schema 检索（登记为后续）。

## 2. 数据基线

| 项 | 值 | 证据 |
|---|---|---|
| 表数 / 行数 | 6 / 8,584 | `data/manifest.json` |
| 生成确定性 | seed=20261020，重跑 sha256 一致 | 同上 |
| 埋点 | 10 类，11 项断言全 PASS | `evidence/db-verify.json` |
| 只读连接 | `file:...?mode=ro` | `src/db.py` |

## 3. 安全闸（四道，全部确定性实现，不靠提示词）

| 闸 | 实现 | 失败表现 |
|---|---|---|
| 只读 | SQLite `mode=ro` + `set_authorizer` 拒绝非 SELECT | 返回"拒绝执行：只允许 SELECT" |
| 表白名单 | authorizer 校验表名 ∈ 6 张登记表 | 越界即拒（防 system 表/临时表） |
| 强制 LIMIT | 外层包 `SELECT * FROM (<sql>) LIMIT {MAX_ROWS}` | 超限截断并标注 |
| 超时 | `set_progress_handler` 计数中断（10s） | 中止并提示"查询超时" |

## 4. 已知限制

- 生成模型是通用大模型，**不懂业务口径**——所有口径必须由语义层喂进去，不能指望模型自己推断。
- 无 GPU、无专用推理，延迟受网关排队影响（实测同一模型 p50 可在 1.5s–18s 间波动）。
- 图表推荐是**规则表**（FT Visual Vocabulary 简化版），不是模型判断。
- 不支持多语句、不支持写操作、不支持跨库。

## 5. 复现

```powershell
cd project\02-nl2sql
python -m scripts.gen_db        # 生成库（约 3 秒）
python -m scripts.verify_db     # 11 项完整性断言
python -m src.server            # → http://127.0.0.1:4181
python -m eval.run_eval         # EX 全自动评测
```

## 6. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-20 | 初版：库生成 + 11 项断言 + 四道安全闸设计定稿 |
| 2026-10-21 | 会话一冻结：新增 §0 依赖与运行环境（requirements.txt / .env.example / 网关 / 端口 / 模型名）；业务代码与数据未改 |
| 2026-10-21 | 客户名改造（用户批准）：去掉名字里的序号，改「城市+生造字号+行业词+公司形式」；仅换字符串、不消耗随机数 ⇒ 其余数据逐值不变，聚合值（541252.34 / 57 / 35）与 11 项断言全部不变；db sha256 由 `fb383915…` 变为 `d1f5872e…`，已重冻结 |
