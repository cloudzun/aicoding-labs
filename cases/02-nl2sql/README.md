# 政企问数 · NL2SQL demo（案例 ②）

> 运营商政企业务的"中文问数"演示：问一句中文，自动出受约束的 SQL、结果表、图表建议，并把口径讲清楚。
> **属于三个教学案例中的第 ② 个**，用于演示"从工具到方法"：证据边界（①）→ **确定性安全边界 + 可自动验收**（②）→ 分级与追溯（③）。

> **证据说明：** `evidence/` 原始记录未随仓库分发（体积大且含内部路径）；本目录 `qa-report.md` 是结论性摘要。

## 一句话定位

**一个能问出数字、看得到 SQL、说得清口径、且物理上写不坏数据的问数助手。**

## 现在能做什么

| 能力 | 说明 |
|---|---|
| 中文问数 | 单表筛选 / 两表三表关联 / 聚合分组 / 时间窗口 / 否定与空值，共 6 类 |
| SQL 可见 | 界面展示**经过安全闸后**的最终 SQL，可折叠核对 |
| 口径可查 | 语义层 12 个指标定义，命中即在界面列出 |
| 四道安全闸 | 只读连接、表白名单（SQLite authorizer）、强制 LIMIT、10s 超时 |
| 意图闸 | "帮我删掉账单"这类写操作**直接拒绝**，不静默改成查询 |
| 歧义分级 | 营收/近三月 → 先反问；在网/月费/SLA → 按默认口径作答并声明 |
| 图表建议 | 规则表推荐（KPI/柱/条/折线/饼/表格），不交给模型 |
| EX 自动评测 | 150 题主集，**零 judge 依赖** |
| trace | 每题落盘：候选 SQL、执行结果、重试次数、耗时、语义层版本 |

## 关键数字

| 项 | 值 |
|---|---|
| 数据 | 6 表 / 8,584 行 / 完全虚构 / seed 20261020 |
| 埋点 | 10 类（重复客户、地市变体、同名产品、空值、未来日期、SLA 矛盾、对账不符、负调整、退订后出账、未响应） |
| 评测集 | 主集 150（40/30/20/30/15/15）+ 歧义 15 + 锚点 20 |
| 安全闸 | 12/12 对抗用例通过 |
| 判定方式 | EX 全自动（列数一致、列名/列序/行序无关、浮点容差 0.01、多解 SQL 都接受） |
| 实测基线（2026-10-21 重跑） | **EX 83.33%（125/150）**；可执行 100%；锚点一致 100%；JOIN 桶 68%；p50/p95 2019/2950ms；db sha `d1f5872e…`（2026-10-20 基线为 84.67% / 2272/5244ms，属不同时点读数，不可直接比） |

## 目录

```
02-nl2sql/
├── db/schema.sql              # 表结构
├── db/EMBEDDED_CASES.json     # 10 类埋点登记 + 检测 SQL
├── data/aicoding.db           # 生成的库（可由 seed 重建）
├── semantic_layer.json        # 指标口径 + 同义词 + 关联规则 + 歧义分级
├── src/                       # db / llm / safety / sqlgen / chart / pipeline / server
├── web/index.html             # 单页前端
├── eval/                      # gold_cases / golden_set / anchor_set / ambiguity_set / run_eval
├── scripts/                   # gen_db / verify_db / build_gold / gen_questions / test_safety / qa_checks
├── docs/                      # 00 口径 / 01 需求 / 10 八环讲解记录
├── SPEC.md  DECISIONS.md  BUILD.md  ENVIRONMENT.md
└── evidence/                  # 带时间戳的实测证据（未随仓库分发）
```

## 快速开始

```powershell
cd cases\02-nl2sql
python -m scripts.gen_db          # 生成库（约 3 秒）
python -m scripts.verify_db       # 11 项完整性断言
python -m src.server              # → http://127.0.0.1:4181
```

> PowerShell 5.1 **不支持** `&&` 串联，请逐行执行（或用 `;`）。

详见 [BUILD.md](BUILD.md)。

## 诚实边界

- 数据完全虚构，**不可用于任何对外口径引用**。
- 主集问句由 LLM 从 gold SQL 反写，与 SQL 结构同源；真实自由提问会更难，锚点集用于校准。
- 未达标项在 `eval/reports/EVAL-REPORT-main.md` 中保留 FAIL，未下调阈值。
- 不做：多轮质量、写操作、跨库、复杂窗口函数、完全离线。

## 文档索引

| 文件 | 内容 |
|---|---|
| [docs/00-数据与口径.md](docs/00-数据与口径.md) | 环 0：EX 八条比对规则、埋点、语义层契约 |
| [docs/01-需求.md](docs/01-需求.md) | 环 1：用户、8 条用户故事、不做清单 |
| [SPEC.md](SPEC.md) | 环 2：10 条 AC、四类契约 |
| [DECISIONS.md](DECISIONS.md) | 18 条决策（含 Rejected、未修项与口径澄清） |
| [docs/10-八环讲解记录.md](docs/10-八环讲解记录.md) | 课堂讲解用（与 ① 同体例：每环 输入/分析/决策依据/门禁产出/要点） |
| [docs/11-操作手册.md](docs/11-操作手册.md) | **功能验证手册**：8 步验证 + 期望值 + 故障表 + 验收清单 |
| review.md（内部评审记录，未随仓库分发） | 第一轮评审（glm-5.3）16 条发现与处置 |
| review-codex.md（内部评审记录，未随仓库分发） | **第二轮评审（codex）19 条发现与处置** |
| [qa-report.md](qa-report.md) | QA 10/10 + EX 分桶与失败归因 |
| retro.md（内部评审记录，未随仓库分发） | 复盘：四个教训、11 条债务、与 ① 的方法对照 |
| [ENVIRONMENT.md](ENVIRONMENT.md) | 能力矩阵与安全闸设计 |
