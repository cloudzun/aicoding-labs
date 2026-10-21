# CHANGELOG

## [Unreleased] - 2026-10-21（会话一：冻结与演示评审期间，均经用户批准）

> 版本号未动（冻结纪律：`VERSION` 保持 `1.0.0.0`）。本节只记录会话一发生的改动。

### Fixed

- `web/index.html`：`$` 选择器不兼容裸 id（`querySelector('clarCard')` 返回 `null`）→ 点击「查询」抛 `TypeError`、`busy` 永久为 true、请求发不出。改为 `$` 自动补 `#`。

### Added

- `web/index.html`：按后端 `chart.type / chart.x / chart.y` 在页面内渲染图表（`kpi` / `kpi_group` / `line` / `bar` / `bar_h` / `pie` / `scatter`；`table`/`empty` 回落表格）。纯内联 SVG、零依赖；类别 >12 转横向条形并限 15 条且标注；支持负值与 `truncated` 标注。
- `requirements.txt`、`.env.example`（环境声明，属会话一授权新增）。
- `ENVIRONMENT.md` 新增 §0 依赖与运行环境。

### Changed

- `scripts/gen_db.py`：客户名去掉序号，改「城市 + 生造字号 + 行业词 + 公司形式」（如「杭州远信源医疗科技有限公司」）；字号由 `customer_brand(i)` 确定性派生、**不消耗随机数** ⇒ 订单/工单/账单与聚合值逐值不变。
- 因客户名变化，15 道含客户名的金标准重算 `gold_hash/gold_sample`（`golden_set.jsonl`、`gold_cases.jsonl`）。
- 数据重冻结：db sha256 `fb383915…` → `d1f5872e…`；旧快照保留为 `evidence/frozen-manifest-nl2sql.pre-rename.bak.json`。
- 三套评测重跑：EX **83.33%（125/150）**、单表 90%、JOIN 68%、p50/p95 **2019/2950ms**；锚点 100%；歧义 0.40/0.80（不变）。差异归因见 `qa-report.md` §三。

## [1.0.0.0] - 2026-10-20

NL2SQL 问数 demo 首个可演示版本。**指标未全部达标**，如实记录见 `qa-report.md`。

### Added

- **确定性合成库**：`scripts/gen_db.py`（seed=20261020）→ 6 表 / 8,584 行；`data/aicoding.db` sha256 固定，重跑一致。
- **10 类埋点**：重复客户（3 组）、地市写法不一致（10 个取值）、产品同名不同规格（13 组）、等级为空（12 行）、未来日期订单（2）、工单未响应/未解决（116/159）、SLA 标记矛盾（47）、应收对账不符（精确 8 行）、负调整（66）、退订后出账（6）。
- **完整性断言**：`scripts/verify_db.py` 11 项，全 PASS 才允许评测（`evidence/db-verify.json`）。
- **语义层**：`semantic_layer.json` v1.1.3 —— 6 表列注释、14 个指标口径、23 个同义词、7 条关联规则、6 类歧义（分 blocking/advisory）、格式约定。
- **gold 题库**：`scripts/build_gold.py` 先执行 SQL 得标准结果，再由 `scripts/gen_questions.py` 反写 150 条自然问句（40/30/20/30/15/15）。
- **人工集**：`eval/anchor_set.jsonl`（20 条，全部可执行）、`eval/ambiguity_set.jsonl`（15 条）。
- **四道安全闸**：只读连接、SQLite authorizer 表名白名单（**默认拒绝 + 函数白名单**）、外层强制 LIMIT、10s 超时。
- **意图闸**：写操作动词直接拒绝，不静默改成查询。
- **链路**：`src/llm.py`、`src/db.py`、`src/safety.py`、`src/sqlgen.py`、`src/chart.py`（规则化图表推荐）、`src/pipeline.py`（编排 + trace）、`src/server.py`（FastAPI）、`web/index.html`（SQL 可见 + 结果表 + 图表建议 + 口径）。
- **EX 全自动评测**：`eval/run_eval.py`（零 judge，标签归一化、浮点容差 0.01、行序仅题面要求时校验）。
- **独立评审**：`scripts/review_code.py`（分片 + 多模型回退），处置见 `review.md`。

### Fixed（开发期发现）

- 账单不挂 `order_id` → 同客户同产品多订单无法对账，"应收是否算对"不可判定（初版误报 127 行）。
- 客户名组合式生成 → 83 组同名客户污染"客户数"类问题。
- gold SQL 带 `LIMIT` 无 `ORDER BY` → "前 N 条"不可判定（改为有 LIMIT 必须有序）。
- 题面未覆盖 SQL 全部输出列 → 模型"合理地"少给列被判错。
- 模板自带 `ORDER BY` 而题面未要求 → 顺序不同被判错（改为题面驱动）。
- 意图闸含"新增" → 误伤"新增订单数"（4 条）。
- 营收歧义触发词含"金额" → 误伤"月费金额"。

### Results（主集 150）

> 以下为 **2026-10-20（10-20 基线）** 的读数（`evidence/eval-main-20261020-143545.json`）；**当前口径是 2026-10-21 重跑的 EX 83.33%（125/150）**，见 `qa-report.md`。修复前为 EX 80.67%，差 4pp 全来自测量缺陷。

| 指标 | 阈值 | 实测 |
|---|---|---|
| EX | ≥85% | **84.67%（127/150）** ❌（差 0.33pp） |
| 可执行率 | ≥95% | **100%** ✅ |
| 单表桶 | ≥90% | **97.50%** ✅ |
| JOIN 桶 | ≥80% | **68.00%** ❌ |
| 聚合/时间/空值桶 | ≥80% | 86.7% / 93.3% / 93.3% ✅ |
| 锚点一致率 | ≥85% | **100%（20/20）** ✅ |
| 歧义识别（按 expected） | ≥60% | **80%（12/15）** ✅（阻塞式反问 40%） |
| 延迟 p50/p95 | ≤2s / ≤4s | 2272ms / **5244ms** ❌ |
| 安全闸对抗 | 100% | **12/12** ✅ |
| 功能 QA | 10/10 | **10/10** ✅ |

### Known issues

- R2-01 复杂窗口函数未纳入；R2-02 多轮只演示；R2-03 歧义词表硬编码；
  R2-06 `ORDER BY + LIMIT` 无 tiebreaker；R2-07 无生成缓存；R2-08 长输入下部分模型返回空；
  R2-10 eval 连接未套全部闸；R2-11 build_gold 未参数化；R2-12 分号切分 fail-closed；
  R2-13 eval 未捕获 gold 执行异常；R2-14 trace 无清理。
  ~~R2-15 主集未在 authorizer 加固后重跑~~ → **已关闭**：加固后重跑 EX 仍为 80.67%（121/150），无回归。
