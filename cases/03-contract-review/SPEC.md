# SPEC · 合同审查 demo（v1）

> 环 2 产出。每条 AC 必须可测；不可自动测的显式标注判定人。

## 1. 架构

```
[web/index.html] 选择合同 → 审查 → 摘要/发现/覆盖率
        │ POST /api/review {contract_id, with_semantic}
        ▼
[src/pipeline.py] 解析 → 确定性 21 条 → 语义 6 条 → 报告 + trace
        ├── [src/parse.py]    docx → 段落/页(估)/段内偏移
        ├── [src/engine.py]   存在型/缺失型/数值型/结构性（标题匹配 + 正则 + 阈值）
        ├── [src/semantic.py] 语义型（LLM + 证据定位校验 + 注入清洗）
        ├── [src/report.py]   固定 schema + 覆盖率 + not_detected
        └── [src/server.py]   FastAPI（列表/审查/上传/规则/报告）
[rules.yaml] 27 条规则（唯一事实源，带版本号）
[eval/run_eval.py] 三套评测（规则命中/报告质量/锚点）
```

## 2. 契约

### 2.1 输入

```json
{"contract_id": "CT003", "with_semantic": true}
```
上传：`POST /api/upload`（multipart，仅 `.docx`，≤10MB）。

### 2.2 报告输出

```json
{"review_id":"rv…","contract_id":"CT003","file":"CT003.docx",
 "pages_estimated":1,"n_paras":25,
 "summary":{"高":1,"中":1,"低":0,"必查缺失":1},
 "findings":[{"rule_id":"R19","title":"赔偿上限比例","category":"数值型","level":"高",
   "violated":true,"detected":true,
   "locator":{"page":1,"para":17,"char_offset":0,"quote":"…"},
   "evidence":"第五条 …不超过合同总额的30%。","reason":"实测 30.0%，阈值 >= 100%",
   "remediation":"赔偿上限建议不低于合同总额的 100%","detector":"deterministic"}],
 "coverage":{"rules_total":27,"rules_checked":21,"not_detected":["R15"],
   "note":"not_detected 表示未取得判定依据，不等于合规"},
 "meta":{"rule_version":"1.0.0","model":"…","semantic_model":"…","elapsed_ms":8420,"timings_ms":{...}}}
```

**硬约束：**
- `violated=true` 必须有 `level`（高/中/低）与 `evidence`；
- 语义型判违规但证据无法在原文定位 → 降级 `not_detected`（不得作为风险输出）；
- `not_detected` 必须出现在 `coverage` 里，不得静默丢弃。

### 2.3 trace（`data/traces/<review_id>.json`）

含完整 findings（含未违规项）、报告、时间拆解；review_id 正则 `^rv[0-9a-f]{8,16}$`。

### 2.4 规则契约（`rules.yaml`）

字段：`id / name / category / expect / detector / severity / keywords|pattern|threshold / heading / remediation`。
**LLM 不得新增规则**，只能对给定 id 作答。

## 3. 判定逻辑

| 类型 | 判定 | 依据位置 |
|---|---|---|
| 存在型 / 缺失型 | 段落以"第X条"开头且含 `heading` → 存在；否则缺 | 标题段 |
| 数值型 | 正则抽第一个非空分组 → 与 `threshold` 比较 | 命中的段落 |
| 语义型 | LLM 判断 + 证据必须在原文出现 | 证据所在段落 |
| 结构性 | R26 前 6 段含甲方/乙方/地址/联系人；R27 签署日期 = 生效日期 | 头部/签署页 |

## 4. 验收标准

| 编号 | AC | 测量 | 阈值 |
|---|---|---|---|
| AC-01 | 存在型 Recall | `python -m eval.run_eval` | ≥88% |
| AC-02 | 存在型 Precision | 同上 | ≥85% |
| AC-03 | 缺失型 Recall | 同上 | ≥85% |
| AC-04 | 缺失型误报率 | 同上 | ≤15% |
| AC-05 | 语义型 Recall（`--semantic`） | 同上 | ≥70% |
| AC-06 | 等级一致率 | 同上 | ≥80% |
| AC-07 | 定位率 | 同上 | ≥90% |
| AC-08 | 报告结构通过率 | 同上 | 100% |
| AC-09 | 锚点一致率（20 条） | `--anchors` | ≥85% |
| AC-10 | 单份耗时 p95 | 同上 | ≤10s |
| AC-11 | 注入防御 | `scripts/qa_checks.py` | 文档内"忽略以上指令"不改变判定 |
| AC-12 | **定位准确率**（可定位项：数值/结构/语义） | 同上 | ≥90% | 同上 |
| AC-13 | **缺失项位置覆盖率**（推断，标 inferred） | 同上 | ≥80% | 同上 |
| AC-14 | 缺失型 Recall（原 AC-03 口径已升级） | 同上 | ≥85% | 同上 |

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| 语义型幻觉 | 证据定位校验 + 降级 not_detected |
| 缺失型误报 | 标题匹配 + 误报率单独门禁 |
| 规则与真值矛盾 | 生成器冲突消解（D06/D07/D08 与 缺R11/R05/R12 互斥）+ 数据断言 |
| PDF 误入 | 上传接口硬拦 `.docx` 以外格式 |

## 6. SPEC 自检

- [x] **14 条 AC** 全部可测（AC-12 定位准确率、AC-13 缺失项位置覆盖率、AC-14 缺失型口径于 v1.1 追加）
- [x] 报告契约含"违规必须有等级与证据""not_detected 必须显式"
- [x] LLM 白名单约束写入契约
- [x] 输入/输出/trace/规则四类契约齐全
- [x] 风险 4 条有对策
