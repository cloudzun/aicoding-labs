# AI Coding 教学案例：三个可运行、可评测的 AI 应用

用三个**小而完整**的案例，把"从需求到可验收"的 AI 应用工程链路跑通：

| 案例 | 做什么 | 难点 | 门禁结论（作者环境） |
|---|---|---|---|
| **[01 RAG 制度问答](cases/01-rag-qa)** | 12 份虚构制度，问答必须给引用、无答案必须拒答 | 拒答边界、冲突条款、评测口径 | **INCOMPLETE**（judge 失败率超 2%） |
| **[02 NL2SQL 政企问数](cases/02-nl2sql)** | 自然语言转 SQL，含歧义反问、写操作拦截 | 口径、JOIN、可执行性 | **FAIL**（EX 83.33% < 85%，JOIN 桶 68%） |
| **[03 合同审查](cases/03-contract-review)** | 27 条规则、双引擎（确定性 + 语义）、定位到原文 | 缺失型、立场、证据约束 | **PASS**（14 条 AC 全过，仍有未修项） |

> 三个案例的门禁结论**原样保留**：没达标就是没达标。这是本项目作为教学素材的核心价值——失败与修补过程比"全绿"更有信息量。

## 目录

| 路径 | 内容 |
|---|---|
| [`cases/01-rag-qa/`](cases/01-rag-qa) · [`cases/02-nl2sql/`](cases/02-nl2sql) · [`cases/03-contract-review/`](cases/03-contract-review) | 三个可运行案例：语料/数据生成、评测、Web UI；各有 `README.md` 与 `qa-report.md` |
| [`labs/`](labs/README.md) | 手册体例与待写计划、体验步骤、评审记录（三本实验手册**待写**）；`labs/scripts/smoke-*.ps1` 是三个现成的验收脚本 |
| [`docs/`](docs/README.md) | 方法层文档（八环、性能分析、复盘等），入口见 [`docs/README.md`](docs/README.md) |
| `scripts/` | 一键脚本：`setup` / `doctor` / `run` / `verify` / `check-secrets` |

## 环境要求

- **Python 3.12**（实测 3.12.10）；**3.11+** 理论可用（`numpy==2.4.2` 等依赖要求 3.11+），3.10 会在装依赖时失败
- 一个模型服务 key：默认示例用 [硅基流动 SiliconFlow](https://siliconflow.cn)（同一个 key 覆盖对话、嵌入、重排）
- Windows PowerShell 5.1+ / macOS / Linux 均可（脚本以 PowerShell 为主，Linux 可直接用 python 命令；注意 5.1 **不支持 `&&`**）

## 快速开始（15 分钟）

```powershell
.\scripts\setup.ps1        # 建 .venv、装依赖、生成 .env
# 编辑 cases\01-rag-qa\.env（三个案例各一份）填入 SILICONFLOW_KEY
.\scripts\doctor.ps1       # 体检（红/绿清单）
.\scripts\run.ps1 -Case 1  # 打开 http://127.0.0.1:4180
```

三个案例的完整步骤见 **[QUICKSTART.md](QUICKSTART.md)**，排错见 **[FAQ.md](FAQ.md)**。

## 脚本

| 脚本 | 作用 |
|---|---|
| `scripts/setup.ps1` | 建 `.venv`、装三个案例依赖、生成 `.env`（优先用各案例自带模板；幂等，`-Force` 覆盖） |
| `scripts/doctor.ps1` | 体检：Python、key、模型名是否在 `/models` 列表、端口、索引/数据；给中文修复建议 |
| `scripts/run.ps1 -Case 1/2/3` | 启动对应案例；缺数据时自动生成（`-Port` 可换端口） |
| `scripts/verify.ps1` | 离线断言（语法/两案例数据断言/索引存在则校验/密钥扫描）；`-WithNetwork` 加三案例真实模型调用 |
| `scripts/check-secrets.ps1` | 提交前扫描真实密钥（CI 同款） |
| `labs/scripts/smoke-*.ps1` | 服务启动后的 5 分钟验收（HTTP 断言），用法见 [QUICKSTART](QUICKSTART.md) 第 5 步 |

## 配置（双轨）

每个案例目录一份 `.env`，**从该案例自带的模板复制**（`cases\<案例>\.env.example` 键名与端口都对得上；根 `.env.example` 只是兜底，`setup.ps1` 优先用案例模板）：

| 案例 | 代码真正读取的模型键 |
|---|---|
| 01 RAG | `MODEL_MAIN` / `MODEL_REASONER`（判官）/ `EMBED_MODEL` / `RERANK_MODEL` |
| 02 NL2SQL | `MODEL_MAIN` |
| 03 合同审查 | `MODEL_MAIN` / `MODEL_SEMANTIC`（语义引擎） |

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

`evidence/`（原始评测 JSON、评审记录、截图）**未随仓库分发**：体积大且含内部路径。结论性摘要见各案例 `qa-report.md` 与 `eval/reports/`；文档里出现的 `evidence/...` 引用属于作者环境，克隆后不存在是正常的。

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
- `evidence/`、案例一索引、案例二数据库、案例三合同都不随仓库分发；缺文件按上文命令生成，不是克隆坏了。
- 三份 `BUILD.md` / `ENVIRONMENT.md` 已按默认公网（硅基流动）书写；内网 magpie 仅作可选档 B，见 `.env.example` 注释块。
