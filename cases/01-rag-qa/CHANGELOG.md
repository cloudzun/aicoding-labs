# CHANGELOG

## [Unreleased] - 2026-10-21（会话一：虚构主体改名）

> 版本号未动（冻结纪律：`VERSION` 保持 `0.2.0.0`）。

### Changed

- 虚构主体改名：`浙东省通信服务有限公司` → **`明州数智服务有限公司`**（12 篇制度语料与元数据同步；`EMBEDDED_CASES.md` 一并更新）。
- 界面合规横幅同步改名（`web/index.html` 原先仍显示旧名，2026-10-21 17:20 修正）。
- 重建索引：`python -m src.ingest` → 315 chunk / 2560 维；`corpus_sha256` 由 `78fedbd8…` 变为 **`1f0487bc…`**。
- 重新冻结：`evidence/frozen-manifest-rag-meta.json` 与 `frozen-manifest-rag-corpus.json` 更新；旧快照保留为 `*.pre-rename.bak.json`。
- 金标准答案文本（`golden_set*.jsonl`、`subset_judged.jsonl`）同步替换公司名。
- 重跑评测（`run_eval` 与 `run_eval_v2`），数字见 `qa-report.md` 头部。

### Note

- 语料业务词（“网络割接”“网络安全”等制度标题）**未改**（用户选择只改公司名）；检索与判定逻辑未变。


## [0.1.0.0] - 2026-10-20

首个可运行版本（环 4 施工完成 + 环 5 评审修复）。**未经完整验收**：延迟门禁未通过，详见 `qa-report.md`。

### Added

- **语料**：12 份虚构制度（采购 4 / 财务 3 / 人力 2 / 网维 3，共 315 个条款级 chunk）、`manifest.json`、`EMBEDDED_CASES.md`（8 个难例埋点逐条登记：2 处版本冲突、2 处数字不一致、2 处条款缺失、2 处时效失效）。
- **解析与切分**（`src/corpus.py`）：支持 `.md/.txt/.pdf/.docx`；以「第X条」为最小单位；`chunk_id = doc_id#cNNN` 稳定可复现；保留 `section/clause_no/status/effective_date/doc_number`。
- **混合检索**（`src/vector.py`）：bge-m3 dense（1024 维）+ BM25（jieba）→ RRF(k=60) → bge-reranker-v2-m3 → top-5；嵌入按 `sha1(model+text)` 缓存。
- **废止/时效探针**：对已选中文档做确定性正则扫描，把"废止/失效/试行期/过渡期"声明补入上下文（限 2 条，仅在决定作答时并入）——解决"A1 场景废止声明藏在他文件附则、语义检索召不回"的实测缺陷。
- **生成与拒答**（`src/generate.py`、`src/rag.py`）：magpie 流式 SSE；`reasoning_effort=none`；双闸拒答（rerank 阈值 0.30 + prompt 指令）；15s 单次读超时熔断并标记 `timed_out`。
- **引用**：prompt 强制 `[cNN]`；服务端正则规范化（`c1`→`c01`）、非法引用从答案中移除、记录 `cited/invalid/missing`。
- **多轮**：近 4 轮历史；检索前做启发式指代改写并落盘 `rewritten_query`。
- **服务**（`src/server.py`）：`POST /api/chat`(SSE)、`GET /api/health`、`GET /api/trace/{id}`；端口 4180。
- **前端**（`web/index.html`）：单页无构建；引用点击定位原文；来源面板标注"示例文本"；顶部合规横幅。
- **评测**（`eval/run_eval.py`）：六项指标 + 分桶 + 错误分类 + INCOMPLETE 门禁；报告同时写 `eval/reports/` 与 `evidence/`。
- **评测集生成**（`scripts/make_golden_set.py`）：单跳/多跳由 LLM 从真实条款反推，冲突与时效 8 条人工手写，无关题由 LLM 生成；构建末尾做规模断言。
- **工具**：`scripts/probe_models.py`（能力与延迟探测）、`scripts/smoke_chat.py`、`scripts/purge_traces.py`。

### Changed

- TTFT 指标从"模型首 token"改为**用户感知端到端首字**（含检索），另保留模型侧数值。
- 送入 prompt 的每条 chunk 截断 500 字；引用仍指向完整 chunk。
- 拒答阈值与探针策略：探针只作为候选返回，由上层按"是否作答"决定是否并入（避免无答案问题被无关条款污染）。

### Fixed

| 编号 | 严重度 | 问题 |
|---|---|---|
| F01 | Critical | `# 标题` 落入正文块导致元数据永不解析：修复前 327 个 chunk 的 `status/effective_date` 全为空、`c001` 为标题块且被出题池选中；修复后 315 chunk，**缺失元数据 0 条、空条款号 0 条** |
| F02 | High | rerank 失败降级返回 RRF 分数（量纲 ~0.03）导致全部拒答 → 归一化到 [0,1]×0.55 |
| F03 | High | prompt 层拒答未回填 `refused`，拒答指标失真 |
| F04 | High | 引用正则只认两位数字、非法引用未清洗、缺失引用不判 |
| F06 | High | 多轮检索仍用代词原句 → 启发式改写 |
| F07 | High | 材料未与指令隔离 → 加显式数据边界声明（judge 侧未修） |
| F08 | High | `/api/trace/{id}` 路径穿越 → 白名单正则 |
| F09 | High | trace_id 毫秒时间戳并发覆盖 → UUID |
| F10 | High | 嵌入数量异常静默错位、索引加载不校验 → 三重校验 |
| F11 | High | 评测集被标题 chunk 污染、规模静默缩水 → 出题池过滤 + 数量断言 |
| F12 | High | 正确率分母排除拒答、未测项可输出 PASS → 新分母 + INCOMPLETE |
| F13 | High | judge 失败被当作"忠实" → 仅有效判定计入 |
| F15 | High | BM25 空 token 注入任意 chunk → 空候选 |
| F20 | Medium | trace 缺 `rewritten_query/reasoning_effort/index_meta` → 补齐 |

### Known issues

- **TTFT p95 未达标**：门禁 ≤1000ms，实测约 3.4s（详见 `qa-report.md`，根因为模型侧排队抖动 + 串行检索）。**未下调门禁**。
- **F05 未修**：引用只校验编号存在，未校验该 chunk 是否支持该论断。
- **F14 未修**：15s 为单次读超时，非整体 deadline。
- 评测集实际规模：单跳 118 / 多跳 N / 冲突 8 / 无关 32（见 `eval/golden_manifest.json`），低于 SPEC 设计的 200 条，报告中已披露。
- 公开政策语料目录 `data/corpus/public/` 为空（当前仅合成库）。

## [0.2.0.0] - 2026-10-20

三阶段攻坚（A prompt / B 口径 / C 模型 A/B）。**仍未达标**：结果见 `docs/09-三阶段结果.md`。

### Added

- `src/citations.py`：claim 级引用支撑校验（字符 3-gram Jaccard，阈值 0.15，**下限指标**）；回答契约新增 `claim_support_rate` / `unsupported_claims`。
- `eval/run_eval_v2.py`：facts 口径评测（AC-02 改最小事实点覆盖、AC-11 claim、AC-12 judge 可信度门禁，超限自动判 INCOMPLETE）。
- `eval/golden_set_v2.jsonl`（77/80 有 facts，冲突题 8 条人工手写）、`eval/human_verdicts.jsonl`（8 条人工判定）、`eval/human_questions.jsonl`（20 条人工无偏问题）。
- `scripts/make_gold_facts*.py`、`scripts/bench_providers.py`、`scripts/bench_embeddings.py`。
- `docs/07-SPEC-v0.2增量.md`、`docs/08-会审-v0.2.md`、`docs/09-三阶段结果.md`。

### Changed

- prompt 增加"逐子问题作答"与"禁止推断未写明时效"两条硬约束。
- judge 输出增加 `missing_facts` 并强制字段齐全；`max_tokens` 800 → **2500**。
- 嵌入/重排统一切到 magpie 网关：Qwen3-Embedding-4B（2560 维）/ Qwen3-Reranker-4B；硅基流动直连降为备用通道。

### Fixed

- **judge JSON 截断**：`max_tokens=800` 被 deepseek 思维链（约 450 token）吃光，曾导致 26%–42% 判定失败。修后失败率 7.5% → 2.53%。
- **claim 校验切分 bug**：按句号切分把 `[cNN]` 切到下一段，导致支撑率恒为 0；改为以引用为锚点回看前文。

### Results（同集合 80 条，不可跨口径比较）

| 项 | 数值 |
|---|---|
| Faithfulness（A 段同口径 before→after） | 62.34% → **79.75%**（+17.4pp） |
| 误拒率 | 3.75% → 1.25% |
| 正确率（旧口径 → facts 口径） | 40.00% → **50.65%**（口径修正 +10.65pp） |
| claim 支撑率 | 78.06% |
| judge 失败率 | 2.53%（超 2% 门禁 → INCOMPLETE） |
| TTFT p95 / 完成 p95 | 4041ms / 5591ms（均未达标） |

### Known issues

- AC-02（50.65%）、AC-11（78.06%）、AC-07、AC-08 均未达标；AC-12 超门禁使结论为 INCOMPLETE。
- `refused` 误标（R-29）：答案开头含"资料不足"会被记为拒答，影响 h-07。
- 20 条无偏集对嵌入 A/B 无区分度（12 份语料太小），嵌入选型无法据数据决定。
