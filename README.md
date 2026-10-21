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

## 快速开始（5 分钟）

```powershell
git clone <this-repo> aicoding-labs
cd aicoding-labs
copy .env.example cases\01-rag-qa\.env    # 然后填入 SILICONFLOW_KEY
cd cases\01-rag-qa
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.ingest        # 重建索引（315 chunk / 2560 维）
python -m src.server        # http://127.0.0.1:4180
```

三个案例的完整步骤见 **[QUICKSTART.md](QUICKSTART.md)**。

## 数字口径（重要）

- 仓库里的指标（正确率、召回、延迟、EX）都是**作者环境的一次性读数**，随模型版本、网关负载、网络变化。换环境后**不可复现**，只能作参考。
- 案例一中出现了"同一批题、同一模型名，重跑结果不同"的情况，我们在 `cases/01-rag-qa/qa-report.md` §七 如实记录了归因（模型/判官漂移 + 采样波动），并明令**不得**把差异写成"改名/优化带来的提升"。
- 每个案例目录下的 `qa-report.md` 是当前口径；历史读数在 `DECISIONS.md` / `CHANGELOG.md` 中保留并标注，**不同口径不可混写**。

## 许可

- 代码：MIT（见 [LICENSE](LICENSE)）
- 文档与课程材料：CC BY-NC-SA 4.0
- 数据为程序生成的虚构内容，见 [DISCLAIMER.md](DISCLAIMER.md)

## 尚未完成

- 一键安装脚本（`scripts/setup|doctor|run|verify|check-secrets`）正在补充；当前按 QUICKSTART 手动执行即可。
- 案例三仅支持 docx；PDF/扫描件未支持。
