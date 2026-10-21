# FAQ / 故障排查

> 本项目是**静态教学标本**，不接收 PR，issue 不保证回复。下面覆盖了绝大多数克隆后会遇到的问题，请先自查。

## 0. 最快路径

```powershell
.\scripts\setup.ps1      # 建 .venv + 装依赖 + 生成 .env
# 编辑 cases\*\..env，填入你的 SILICONFLOW_KEY
.\scripts\doctor.ps1     # 体检（红/绿清单）
.\scripts\run.ps1 -Case 1
```

## 1. Key 与模型服务

| 现象 | 原因 | 处理 |
|---|---|---|
| `[FAIL] 未填 API key` | `.env` 里还是 `<YOUR_SILICONFLOW_KEY>` | 打开 `cases\01-rag-qa\.env` 填真实 key；三个案例各自一份 |
| `401 Unauthorized` | key 错误 / 复制时带了空格 | 重新复制；确认没有引号、没有换行 |
| `400 / 402 余额不足` | 账户欠费或未实名 | 去硅基流动控制台确认余额与实名状态 |
| `[WARN] 默认模型缺失` | 平台下架了默认模型 | 在 `.env` 把 `MODEL_MAIN` / `EMBED_MODEL` 换成 `/models` 列表里同系列的模型 |
| `429 Too Many Requests` | 免费额度限流 | 等 1 分钟重试；跑评测时降低并发或分批 |

> 换 `EMBED_MODEL` 后**必须**重建案例一索引（`python -m src.ingest`），否则维度不一致会拒绝启动。

## 2. 端口与启动

| 现象 | 处理 |
|---|---|
| `[Errno 10048] address already in use` | `.\scripts\doctor.ps1` 会列出占用端口；在对应 `.env` 改 `PORT`，或 `.\scripts\run.ps1 -Case 1 -Port 5180` |
| 打开页面但接口全报错 | 服务窗口是否还在？`/api/health` 是否正常？ |
| `ModuleNotFoundError: src` | 要在**案例目录内**运行 `python -m src.server`，或用 `run.ps1` |
| 中文乱码 | `chcp 65001` 后重试；本项目文件均为 UTF-8 |

## 3. 数据与索引

| 现象 | 处理 |
|---|---|
| 案例一启动报索引缺失 | `cd cases\01-rag-qa; python -m src.ingest`（需要 key） |
| 案例二 `/api/ask` 报无表 | `cd cases\02-nl2sql; python -m scripts.gen_db`（不需要 key） |
| 案例三合同列表为空 | `cd cases\03-contract-review; python -m scripts.gen_contracts`（约 3 秒） |
| `verify.ps1` 报索引维度不对 | 你换过嵌入模型；重建索引，或恢复默认 `Qwen/Qwen3-Embedding-4B`（2560 维） |

## 4. 结果与指标

| 现象 | 说明 |
|---|---|
| 案例一答不出 / 答偏 | 先看是否拒答（`refused`）；再确认索引是否重建、检索来源是否命中 |
| 案例二 SQL 错 | JOIN 类问题本身是已知短板（JOIN 桶 68%），不是你的环境坏了 |
| 案例三语义规则时有时无 | 语义 6 条依赖模型，**允许波动**；确定性 21 条稳定复现 |
| 指标与 README 不一致 | **正常**：所有指标是作者环境的一次性读数，换模型/网络后不可复现（见各案例 `qa-report.md`） |
| 为什么案例一门禁是 INCOMPLETE | judge 失败率超 2%，按规则判定"正确率不可读"——这是刻意保留的失败案例 |

## 5. 环境

| 项 | 要求 |
|---|---|
| Python | 3.12（本项目实测 3.12.10）；3.10/3.11 大概率可用但未验证 |
| 系统 | Windows PowerShell 5.1+；macOS/Linux 可手动执行同样的 python 命令 |
| 网络 | 需要访问模型服务（默认 `api.siliconflow.cn`）；`*.ps1` 不联网 |
| 磁盘 | 约 100 MB（含 .venv 与生成数据） |
