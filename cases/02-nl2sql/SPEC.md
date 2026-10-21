# SPEC · NL2SQL 问数 demo（v1）

> 环 2 产出。每条 AC 必须映射到可执行测量方式；无法自动判定的显式标注人工判定人。
> 上游：[环 0 口径](docs/00-数据与口径.md)、[环 1 需求](docs/01-需求.md)

## 1. 目标

中文问句 → 受约束的 SQL → 执行 → 结果表 + 图表建议 + SQL 与口径展示；口径歧义时反问；越权/写操作/超时被确定性拦截。

## 2. 系统边界

### 2.1 In scope

| 编号 | 能力 |
|---|---|
| S1 | 全量 schema + 语义层入 prompt（6 表，不做 schema 检索） |
| S2 | 生成单条 `SELECT`，提取并规范化 SQL |
| S3 | **四道安全闸**：只读连接、表/列白名单（authorizer）、强制 LIMIT、10s 超时 |
| S4 | 执行失败或校验失败 → 最多 2 次纠错重试（每次重过安全闸） |
| S5 | 结果表（≤200 行展示）+ 图表建议（规则表） |
| S6 | 前端展示：SQL 可折叠、口径清单、耗时、trace_id |
| S7 | 歧义识别：命中歧义词表时先给口径选项（反问），不直接出数 |
| S8 | trace 落盘：问题、SQL、重试、行数、耗时、口径引用 |
| S9 | EX 自动评测（150 主集 + 15 歧义 + 20 锚点） |

### 2.2 Out of scope

多轮追问（仅演示）、写操作、跨库、复杂窗口函数、完全离线、图表交互（仅建议类型）。

## 3. 架构

```
[web/index.html] 单页：问句 → SQL 折叠 → 结果表 → 图表建议 → 口径
        │ POST /api/ask (JSON，含 stages)
        ▼
[src/server.py] FastAPI
        ▼
[src/pipeline.py] 编排：歧义闸 → 生成 → 提取 → 安全校验 → 执行 → 纠错(≤2) → 图表 → trace
        ├── [src/sqlgen.py]  prompt（schema + 语义层 + few-shot）+ 调 magpie + 提取 SQL
        ├── [src/safety.py]  authorizer 白名单 / LIMIT 包装 / 超时 / 多语句拒绝
        ├── [src/execute.py] 只读执行 + 列名 + 行数 + 耗时
        ├── [src/chart.py]   规则化图表推荐
        └── [src/db.py]      schema dump / 连接 / 元数据
[scripts/verify_db.py]  数据完整性断言（环 0 门禁）
[eval/run_eval.py]      EX 全自动评测
```

## 4. 契约

### 4.1 输入契约（`POST /api/ask`）

```json
{"question": "杭州的制造行业客户数量是多少？", "history": []}
```

### 4.2 输出契约

```json
{
  "trace_id": "q1750000000000",
  "question": "...",
  "clarification": null,
  "sql": "SELECT COUNT(*) AS cnt FROM dim_customer WHERE city = '杭州' AND industry = '制造'",
  "columns": ["cnt"],
  "rows": [[12]],
  "row_count": 1,
  "truncated": false,
  "chart": {"type": "kpi", "x": null, "y": "cnt", "reason": "单值指标"},
  "metrics_used": ["客户数按 customer_id 去重"],
  "attempts": 1,
  "timings_ms": {"generate": 1234, "execute": 3, "total": 1500},
  "rejected": null
}
```

**硬约束：**
- `sql` 必须是通过安全闸的最终 SQL（不是模型原始输出）；
- `rejected` 非空时不得返回 rows；
- `clarification` 非空时不得返回 sql/rows（歧义优先于作答）。

### 4.3 trace（`data/traces/<id>.json`）

必含：`question / candidates[] / final_sql / validation / attempts / row_count / elapsed_ms / model / effort / schema_version / semantic_layer_version`。

### 4.4 语义层（`semantic_layer.json`）

结构：`metrics[]`（id/name/definition/sql_hint）、`synonyms`（词→标准实体）、`joins`（推荐关联键）、`ambiguities[]`（歧义词→候选口径）。

**版本化**：`version` 字段进 trace；改口径必须升版本并重跑基线。

## 5. 关键实现约定

| 项 | 约定 | 理由 |
|---|---|---|
| 安全闸顺序 | 只读连接 → authorizer → LIMIT 包装 → 超时 | 任一失败立即返回，不进执行 |
| LIMIT | 外层包 `SELECT * FROM (sql) LIMIT 1000`；SQL 自带更小 LIMIT 时保留 | 统一截断，防全表扫描 |
| 超时 | `set_progress_handler` 每 1000 步检查，超 10s 中断 | SQLite 无原生超时 |
| 多语句 | 检测 `;` 后仍有内容即拒绝 | 防注入 |
| 纠错 | 携带上次 SQL 与错误信息，最多 2 次 | 防无限循环与绕过 |
| 歧义 | 先查歧义词表（营收/近三月/客户数/SLA/在网/金额），命中即反问 | 与 RAG 的"拒答"同构，是"先问再答" |
| 图表 | 规则表：单值→KPI；1 维+1 度量→柱/条；时间→折线；占比≤6→饼 | 可解释、可测试 |

## 6. 验收标准

| 编号 | AC | 测量 | 阈值 | 证据 |
|---|---|---|---|---|
| AC-01 | EX（主集 150） | `python -m eval.run_eval` | ≥85% | `evidence/eval-ex.json` |
| AC-02 | 可执行率 | 同上 | ≥95% | 同上 |
| AC-03 | 单表桶 EX | 同上 | ≥90% | 同上 |
| AC-04 | JOIN 桶 EX（两表+三表） | 同上 | ≥80% | 同上 |
| AC-05 | 聚合/时间/否定桶 EX | 同上 | ≥80% | 同上 |
| AC-06 | 歧义识别率（15 题，按 expected：指出问题即算对，含 blocking/advisory） | 自动比对 expected | ≥60% | `evidence/eval-ambiguity-*.json` |
| AC-07 | 安全闸 4/4 生效 | `scripts/qa_checks.py` 负例集 | 100% | `evidence/qa-*.json` |
| AC-08 | 首次返回 p95 / 完成 p95 | 逐题计时 | ≤2s / ≤4s | `evidence/eval-latency.json` |
| AC-09 | 锚点一致率（20 题） | 自动 EX vs 人工判断 | ≥85% | `evidence/eval-anchor.json` |
| AC-10 | 每题留 trace | 抽查 5 条字段完整 | 100% | `data/traces/` |

**人工判定项：** AC-06（歧义反问）与 AC-09 的人工侧，判定人 Lead，客户抽检 20% 待安排。

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| 模型写出越权 SQL | 只读连接 + authorizer 双保险（提示词被绕过也写不进去） |
| JOIN 放大（产品同名/重复客户） | 语义层明确按 ID 关联；专项题在 EX 分桶里体现 |
| 歧义被硬答 | 歧义闸在生成前触发，不依赖模型自觉 |
| 模型延迟抖动 | 单次生成 30s 超时；失败返回明确错误而非空结果 |

## 8. SPEC 自检

- [x] 10 条 AC 全部有可执行测量
- [x] 四类契约（输入/输出/trace/语义层）字段齐全
- [x] 输出契约含"歧义优先于作答""rejected 不得返回 rows"两条硬约束
- [x] 安全闸顺序与实现方式写死
- [x] 人工判定项标注判定人
- [x] 风险 4 条有对策
