# AI Coding 教学案例：三个可运行、可评测的 AI 应用

用三个**小而完整**的案例，把"从需求到可验收"的 AI 应用工程链路跑通：

| 案例 | 做什么 | 难点 | 门禁结论（作者环境） |
|---|---|---|---|
| **[01 RAG 制度问答](cases/01-rag-qa)** | 12 份虚构制度，问答必须给引用、无答案必须拒答 | 拒答边界、冲突条款、评测口径 | **INCOMPLETE**（judge 失败率超 2%） |
| **[02 NL2SQL 政企问数](cases/02-nl2sql)** | 自然语言转 SQL，含歧义反问、写操作拦截 | 口径、JOIN、可执行性 | **FAIL**（EX 83.33% < 85%，JOIN 桶 68%） |
| **[03 合同审查](cases/03-contract-review)** | 27 条规则、双引擎（确定性 + 语义）、定位到原文 | 缺失型、立场、证据约束 | **PASS**（14 条 AC 全过，仍有未修项） |

> 三个案例的门禁结论**原样保留**：没达标就是没达标。这是本项目作为教学素材的核心价值——失败与修补过程比"全绿"更有信息量。

## 目录

```
cases/01-rag-qa/         RAG：语料、索引、评测、Web UI
cases/02-nl2sql/         NL2SQL：数据生成、语义层、评测、Web UI
cases/03-contract-review/合同审查：30 份 docx、27 条规则、评测
labs/                    实验手册、体验步骤、评审记录
docs/                    方法层文档（八环、性能分析、复盘等）
```

## 环境要求

- **Python 3.12**（3.10+ 大概率可用，未逐一验证）
- 一个模型服务 key：默认示例用 [硅基流动 SiliconFlow](https://siliconflow.cn)（同一个 key 覆盖对话、嵌入、重排）
- Windows PowerShell 5.1+ / macOS / Linux 均可（脚本以 PowerShell 为主，Linux 可直接用 python 命令）

## 快速开始（15 分钟）

```powershell
.\scripts\setup.ps1        # 建 .venv、装依赖、生成 .env
# 编辑 cases\*\..env 填入 SILICONFLOW_KEY
.\scripts\doctor.ps1       # 体检（红/绿清单）
.\scripts\run.ps1 -Case 1  # 打开 http://127.0.0.1:4180
```

三个案例的完整步骤见 **[QUICKSTART.md](QUICKSTART.md)**，排错见 **[FAQ.md](FAQ.md)**。

## 脚本

| 脚本 | 作用 |
|---|---|
| `scripts/setup.ps1` | 建 `.venv`、装三个案例依赖、生成 `.env`（幂等，`-Force` 覆盖） |
| `scripts/doctor.ps1` | 体检：Python、key、模型可用性、端口、索引/数据；给中文修复建议 |
| `scripts/run.ps1 -Case 1/2/3` | 启动对应案例；缺数据时自动生成（`-Port` 可换端口） |
| `scripts/verify.ps1` | 离线断言（语法/数据/索引/密钥）；`-WithNetwork` 加三案例真实模型调用 |
| `scripts/check-secrets.ps1` | 提交前扫描真实密钥（CI 同款） |

## 配置（双轨）

每个案例目录一份 `.env`（从根 `.env.example` 复制）：

- **档 A（默认）硅基流动**：一个 key 覆盖 chat / embedding / rerank；
- **档 B magpie 内网**：把 `LLM_PROVIDER=magpie` 与 `MAGPIE_BASE/KEY` 打开即可（不对外分发）。

`reasoning_effort` 是 magpie 专有参数，代码只在 magpie 档发送；`MIN_RERANK_SCORE` 可用 `.env` 覆盖（换重排模型后需重新校准）。

## 数据是生成的，不是提交的

被 `.gitignore` 排除、按需生成：

| 内容 | 生成命令 |
|---|---|
| 案例一索引 | `cd cases\01-rag-qa; python -m src.ingest`（需要 key） |
| 案例二数据库 | `cd cases\02-nl2sql; python -m scripts.gen_db` |
| 案例三合同 | `cd cases\03-contract-review; python -m scripts.gen_contracts` |

`scripts/run.ps1` 会自动补；`scripts/verify.ps1` 会重新生成并断言（案例二 11 项、案例三 10 项）。

## 数字口径（重要）

- 仓库里的指标（正确率、召回、延迟、EX）都是**作者环境的一次性读数**，随模型版本、网关负载、网络变化。换环境后**不可复现**，只能作参考。
- 案例一中出现了"同一批题、同一模型名，重跑结果不同"的情况，我们在 `cases/01-rag-qa/qa-report.md` §七 如实记录了归因（模型/判官漂移 + 采样波动），并明令**不得**把差异写成"改名/优化带来的提升"。
- 每个案例目录下的 `qa-report.md` 是当前口径；历史读数在 `DECISIONS.md` / `CHANGELOG.md` 中保留并标注，**不同口径不可混写**。

## 维护状态

**教学标本**：内容以发布时点为准，**不接收 PR**，issue 不保证回复。欢迎 fork 后自行改造。
依赖已按 `==` 精确钉版（实测 Python 3.12.10）；模型服务若下架示例模型，按 `FAQ.md` §1 换名即可。

## 许可

- 代码：MIT（见 [LICENSE](LICENSE)）
- 文档与课程材料：CC BY-NC-SA 4.0
- 数据为程序生成的虚构内容，见 [DISCLAIMER.md](DISCLAIMER.md)

## 已知限制

- 案例三仅支持 docx；PDF/扫描件未支持；语义规则有波动，确定性规则稳定。
- 案例二 JOIN 类问题是已知短板（JOIN 桶 68%），不是环境问题。
- 案例一门禁结论为 INCOMPLETE（judge 失败率超 2%），刻意保留。
