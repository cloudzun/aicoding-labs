# FAQ / 故障排查

> 本项目是**静态教学标本**，不接收 PR，issue 不保证回复。下面覆盖了绝大多数克隆后会遇到的问题，请先自查。

## 0. 最快路径

```powershell
.\scripts\setup.ps1      # 建 .venv + 装依赖 + 生成 .env
# 编辑 cases\01-rag-qa\.env（三个案例各一份），填入你的 SILICONFLOW_KEY
.\scripts\doctor.ps1     # 体检（红/绿清单）
.\scripts\run.ps1 -Case 1
```

## 1. Key 与模型服务

| 现象 | 原因 | 处理 |
|---|---|---|
| `[FAIL] 未填 API key` | `.env` 里还是 `<YOUR_SILICONFLOW_KEY>` | 打开 `cases\01-rag-qa\.env` 填真实 key；三个案例各自一份 |
| `401 Unauthorized` | key 错误 / 复制时带了空格 | 重新复制；确认没有引号、没有换行 |
| `400 / 402 余额不足` | 账户欠费或未实名 | 去硅基流动控制台确认余额与实名状态 |
| `[WARN] 默认模型缺失` | 平台下架了默认模型，或 `.env` 里的模型名拼错 | 在 `.env` 把 `MODEL_MAIN`（案例一还有 `EMBED_MODEL` / `RERANK_MODEL`）换成 `/models` 列表里同系列的模型；判官/语义模型的键是 `MODEL_REASONER`（案例一）/ `MODEL_SEMANTIC`（案例三） |
| 改了 `MODEL_JUDGE` 没反应 | 代码不读这个键：案例一读 `MODEL_REASONER`、案例三读 `MODEL_SEMANTIC` | 改成对应键名；旧模板留下的 `MODEL_JUDGE` 会被 `doctor.ps1` 的 `[WARN]` 直接点出来 |
| `429 Too Many Requests` | 免费额度限流 | 等 1 分钟重试；跑评测时降低并发或分批 |

> 换 `EMBED_MODEL` 后**必须**重建案例一索引（`python -m src.ingest`），否则维度不一致会拒绝启动。

## 2. 端口与启动

| 现象 | 处理 |
|---|---|
| 端口被占用（`[Errno 10048]`）/ 想一次停掉所有服务 | `.\scripts\demo-control.ps1 status` 看端口与 PID，`stop` 一键停（只杀本项目服务）；在对应 `.env` 改 `PORT`，或 `.\scripts\run.ps1 -Case 1 -Port 5180` |
| 打开页面但接口全报错 | 服务窗口是否还在？`/api/health` 是否正常？ |
| `ModuleNotFoundError: src` | 要在**案例目录内**运行 `python -m src.server`，或用 `run.ps1` |
| `标记"&&"不是此版本中的有效语句分隔符` | Windows PowerShell 5.1 不支持 `&&`（PS 7+ 才有）。逐行执行，或用 `;` 分隔，或装 PowerShell 7 |
| 中文乱码 | `chcp 65001` 后重试；本项目文件均为 UTF-8 |

## 3. 数据与索引

| 现象 | 处理 |
|---|---|
| 案例一启动报索引缺失 | `cd cases\01-rag-qa; python -m src.ingest`（需要 key） |
| 案例一页面能开、但每次都回"资料不足"/被拒答 | 索引没生成或为空（`/api/health` 的 `index.chunk_count` 为 0 或缺失）：`cd cases\01-rag-qa; python -m src.ingest`（需要 key，315 chunk，约 1 分钟）；`doctor.ps1` 会先给 `[WARN] 案例一索引缺失` |
| 案例二 `/api/ask` 报无表 | `cd cases\02-nl2sql; python -m scripts.gen_db`（不需要 key） |
| 案例三合同列表为空 | `cd cases\03-contract-review; python -m scripts.gen_contracts`（约 3 秒） |
| `verify.ps1` 报索引维度不对 | 你换过嵌入模型；重建索引，或恢复默认 `Qwen/Qwen3-Embedding-4B`（2560 维） |
| 文档里提到的 `evidence/`、`probe-*.txt` 找不到 | 正常：原始评测/评审记录**未随仓库分发**（体积大且含内部路径），结论性摘要见各案例 `qa-report.md` |

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
| Python | 3.12（实测 3.12.10）；**3.11+** 理论可用（`numpy==2.4.2` 等依赖要求 3.11+），3.10 会在装依赖时失败 |
| 系统 | Windows PowerShell 5.1+；macOS/Linux 可手动执行同样的 python 命令。5.1 不支持 `&&`，命令逐行执行 |
| 网络 | 需要访问模型服务（默认 `api.siliconflow.cn`）；`setup.ps1` 与默认的 `verify.ps1` 不调模型，`doctor.ps1` 只多调一次 `/models` |
| 磁盘 | 约 100 MB（含 .venv 与生成数据） |

## 6. 干净机 / 服务器环境（Azure VM 实测）

以下问题在全新 Windows Server 2022（无 git、英文代码页 cp437）上真实出现过，已修复或已在脚本中处理：

| 现象 | 原因 | 处理 |
|---|---|---|
| `No module named 'encodings'` / `Could not find platform independent libraries` | PATH 里的 `python` 是 shim，或 Python 安装残缺（`Lib` 为空） | 用完整路径（如 `C:\Python312\python.exe`）或重装；`setup.ps1` 会自动探测可用解释器并给出提示 |
| 打印中文报 `UnicodeEncodeError: 'charmap' codec` | 系统默认代码页不是 UTF-8 | 脚本已设 `PYTHONUTF8=1`；手动运行前先 `$env:PYTHONUTF8='1'` |
| `check-secrets.ps1` 报 `git 不是内部或外部命令` | 机器没装 git（直接下载 zip 的情况） | 脚本已支持无 git：退化为扫描工作区并跳过 `.env` |
| `setup.ps1` 报 `.venv 创建失败` | 解释器不可用（同上第一条） | 按提示改用完整路径重跑 |

> 验证记录：2026-10-21，Azure `Standard_B2s` / Windows Server 2022，无 git、cp437、NuGet 版 Python 3.12.10，`setup.ps1` 与 `verify.ps1` 均通过。

## 7. 安装与网络细节（pip / 代理 / 模型名）

| 现象 | 处理 |
|---|---|
| `pip install` 很慢、超时或 `SSLError` | 换国内镜像：`.\.venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r cases\01-rag-qa\requirements.txt`（三个案例各跑一次）。`setup.ps1` 不会透传 `-i`，可先手动装；装完重跑 `setup.ps1` 会复用已有 `.venv` |
| 公司代理 / 内网 | 先 `$env:HTTPS_PROXY='http://<proxy>:<port>'`（HTTP 同理）再跑脚本；`doctor.ps1` 报 `[FAIL] 连不上模型服务` 多为代理或防火墙拦了 `api.siliconflow.cn` |
| 怎么确认模型名写对 | 对照平台模型列表：`curl -H "Authorization: Bearer <key>" https://api.siliconflow.cn/v1/models`，或直接看硅基流动控制台的模型广场。`doctor.ps1` 的 `[WARN] 案例N 默认模型缺失` 即表示该名字不在列表里（拼错或已下架） |
| 想看脚本有哪些参数 | 脚本只有注释式帮助：`Get-Help .\scripts\run.ps1 -Full` |
| 想换回默认配置 | `.\scripts\setup.ps1 -Force` 会用模板重新生成 `.env`（**会覆盖已填的 key**，先备份） |