# SPEC · 政企 RAG 问答 demo（v1）

> **环次：** 第 2 环 `/spec`
> **上游：** [环 0 数据与口径](00-数据与口径.md)（已关闭）、[环 1 需求](01-需求.md)（已批准）
> **本 SPEC 的门禁：** 每条验收标准都必须能映射到一个可执行的测量方式；无法自动判定的显式标注"人工判定 + 判定人"。

---

## 1. 目标

一个可在 Windows 本机一键启动的政企制度问答系统：上传/预置制度文档 → 结构化切分 → 混合检索 + 重排 → 流式生成 → **答案可点回原文段落**，并在资料不足时**明确拒答**。

## 2. 系统边界

### 2.1 In scope

| 编号 | 能力 | 说明 |
|---|---|---|
| S1 | 文档入库 | 支持 `.md` `.txt` `.pdf`（文本型）、`.docx`（若装了 python-docx）；按条款切分，保留 `doc_id/page/clause_no` |
| S2 | 混合检索 | dense（bge-m3）+ BM25（jieba）→ RRF 融合 → rerank（bge-reranker-v2-m3）→ top-5 |
| S3 | 流式生成 | SSE 输出；每段答案带 `[c01]` 式引用编号，映射到来源面板 |
| S4 | 引用定位 | 前端点击引用 → 展示原文段落 + 文档名 + 条款号；支持跨文档 |
| S5 | 拒答 | 检索证据不足或上下文不支持时，明确说"资料不足"，并给转人工建议 |
| S6 | 多轮 | 保留最近 N 轮对话；指代消解（"它/这个规定/上面那条"） |
| S7 | 评测 | 一条命令跑评测集，输出六项指标 + 分桶 + 错误分类的 Markdown/JSON 报告 |
| S8 | 追溯 | 每次回答落一份 trace：检索候选、重排分数、模型与版本、耗时 |
| S9 | 管理 | 极简页面：重建索引、查看索引统计、查看 trace |

### 2.2 Out of scope（与环 1 一致，写死）

权限体系与多租户、扫描件 OCR、文档版本审批流、模型微调、完全离线部署、移动端、多轮纳入指标验收。

## 3. 架构

```
[web/index.html] 浏览器（单页，无构建工具）
        │  POST /api/chat (SSE)
        ▼
[src/server.py] FastAPI
        ▼
[src/rag.py] 管道：问题 → 指代改写 → 检索 → 拒答判定 → 生成 → trace
        ├── [src/vector.py] 混合检索：dense(numpy) + BM25(rank_bm25) → RRF → rerank(硅基流动)
        ├── [src/generate.py] magpie /v1/chat/completions（stream, reasoning_effort=none）
        └── [src/store.py] 索引与缓存持久化（jsonl + npy）
[src/corpus.py] 解析与切分：.md/.txt/.pdf/.docx → 条款级 chunk
[src/ingest.py] 离线建库 CLI
[eval/run_eval.py] 评测 CLI → eval/reports/*.json + EVAL-REPORT.md
```

### 3.1 目录契约

```
01-rag-qa/
├── .env / .env.example         # 配置（.env 不入库）
├── ENVIRONMENT.md              # 环境基线与实测证据（已完成）
├── SPEC.md  DECISIONS.md  BUILD.md  review.md  qa-report.md  CHANGELOG.md  VERSION  retro.md
├── docs/                       # 00-数据与口径 / 01-需求
├── data/
│   ├── corpus/synthetic/       # 12 份虚构制度 + manifest.json + EMBEDDED_CASES.md
│   ├── corpus/public/          # 公开政策文件（可替换）
│   ├── index/                  # chunks.jsonl / emb.npy / bm25.json / meta.json
│   └── cache/                  # 嵌入缓存
├── eval/
│   ├── golden_set.jsonl        # 主评测集
│   ├── refusal_set.jsonl       # 拒答集
│   ├── hard_cases.jsonl        # 人工精修难例
│   ├── run_eval.py
│   └── reports/
├── evidence/                    # probe-*.json、评测原始输出
├── scripts/                     # probe_models.py、make_golden_set.py
├── src/
└── web/
```

## 4. 数据契约

### 4.1 chunk 记录（`data/index/chunks.jsonl`，一行一条）

```json
{
  "chunk_id": "zdcg-2023-001#c012",
  "doc_id": "zdcg-2023-001",
  "doc_title": "明州数智服务有限公司采购管理办法",
  "category": "采购管理",
  "status": "现行",
  "effective_date": "2023-04-01",
  "section": "第四章 审批权限",
  "clause_no": "第十二条",
  "page": null,
  "text": "第十二条 单笔采购预算金额在 200 万元以上至 400 万元的……",
  "char_count": 168,
  "prev_id": "zdcg-2023-001#c011",
  "next_id": "zdcg-2023-001#c013"
}
```

**稳定性要求**：同一份文档、同一版本切分器，`chunk_id` 必须可复现（按文档内条款顺序编号，不依赖时间戳）。

### 4.2 索引元信息（`data/index/meta.json`）

```json
{
  "built_at": "2026-10-20T10:00:00+08:00",
  "chunk_count": 214,
  "embed_model": "BAAI/bge-m3",
  "embed_dim": 1024,
  "corpus_sha256": "…",
  "chunker_version": "1.0"
}
```

### 4.3 回答契约（`POST /api/chat`，SSE）

事件序列：

```
event: meta      data: {"trace_id":"...","sources":[{"idx":"c01","chunk_id":"...","doc_title":"...","clause_no":"...","score":0.83}]}
event: delta     data: {"text":"根据"}
event: delta     data: {"text":"……"}
event: done      data: {"answer":"完整答案","elapsed_ms":2143,"refused":false,"model":"opencode-go/gpt-6-luna"}
```

`sources[].idx` 与答案里的 `[c01]` 一一对应。**答案中的引用编号只能来自 sources 列表**，不得凭空生成。

### 4.4 trace（`data/traces/<trace_id>.json`）

必含：`question`、`rewritten_query`、`dense_candidates`、`bm25_candidates`、`reranked`（id+score）、`selected`、`refused`+理由、`model`、`reasoning_effort`、`prompt_tokens`、`completion_tokens`、`ttft_ms`、`total_ms`、`index_meta` 快照。

## 5. 关键实现约定

| 项 | 约定 | 理由 |
|---|---|---|
| 切分 | 以"第X条"为最小单位；单条 >800 字按句号二次切分并加 overlap 1 句 | 条款是引用与验收的自然单位 |
| 检索 | dense top-30 与 BM25 top-30 取并集 → RRF(k=60) → 取前 20 → rerank → top-5 | 混合检索覆盖语义与术语精确匹配 |
| 拒答 | **双闸**：① max rerank 分数 < 0.30 直接拒答（不调模型）；② 模型被要求"上下文不足则拒答" | ①防模型硬答，②防证据不足但有字面匹配 |
| 引用 | prompt 要求每个论断后标 `[cNN]`；服务端校验引用编号必须存在于 sources，非法引用即降级告警 | 防"假引用" |
| 模型 | 默认 `opencode-go/gpt-6-luna` + `reasoning_effort=none`；`deepseek-v4.1-flash/low` 作质量对照 | 实测 p50 1.48s / 2.74s |
| 超时 | 单次生成 15s 熔断，超时返回已生成部分 + 明确标注"生成超时" | 防演示卡死 |
| 缓存 | 嵌入按 `sha1(model+text)` 缓存；重复建库不重复计费 | 省成本、可复现 |
| 日志 | 不记录用户原文以外的敏感信息；trace 本地存储 | 最小必要 |

## 6. 验收标准（逐条映射环 0）

| 编号 | 验收标准 | 测量方式 | 阈值 | 证据文件 |
|---|---|---|---|---|
| AC-01 | Chunk-ID Recall@5 | `python -m eval.run_eval --metric recall` | ≥0.90 | `evidence/eval-recall.json` |
| AC-02 | 答案正确率（160 题） | 人工 + LLM judge 双轨，多跳分桶单列 | ≥0.85 | `evidence/eval-accuracy.json` |
| AC-03 | Faithfulness（1−幻觉率） | 断言级判定（LLM judge + 人工抽检 20%） | ≥0.90 | `evidence/eval-faithfulness.json` |
| AC-04 | 应拒答率（70 题） | 正确拒答数/70 | ≥0.90 | `evidence/eval-refusal.json` |
| AC-05 | 误拒率 | 有答案题被误拒比例 | ≤0.05 | `evidence/eval-refusal.json` |
| AC-06 | 引用可定位率 | 引用编号→chunk→原文段落命中 | ≥0.95 | `evidence/eval-citation.json` |
| AC-07 | TTFT p95 | 流式测量，200 题×1 轮，并发=1 | ≤1.0s | `evidence/eval-latency.json` |
| AC-08 | 完成 p95 | 同上 | ≤5.0s | `evidence/eval-latency.json` |
| AC-09 | 每次回答留 trace | 抽查 5 条 trace 字段完整 | 100% | `data/traces/` |
| AC-10 | 演示不崩 | 断网/超时/空库三种异常场景各有明确提示 | 3/3 | `qa-report.md` |

**明确标注为人工判定的项：** AC-02 与 AC-03 的最终值需要人工抽检确认（抽检比例 20%，抽检人：Lead；客户抽检 20% 作为验收演示）。

## 7. 交付物清单（九件套对齐）

1. 脱敏/合成数据集（12 份合成 + 公开文件）
2. Golden set（主集 + 拒答集 + 难例集）
3. 一条命令的评测脚本 `python -m eval.run_eval`
4. 六类负例集（无答案/知识库外/时效冲突/版本冲突/相似无关/越权接口位）
5. 指标报告模板（`EVAL-REPORT.md`）
6. 离线启动说明（`BUILD.md`：无容器、本机直跑）
7. 权限矩阵与审计字段（本次单租户，仅留接口位与 trace 字段）
8. 降级/回滚方案（模型超时熔断、嵌入不可用明确报错）
9. "不做事项"清单（见 §2.2）

## 8. 风险与对策

见 [01-需求 §8](01-需求.md) 与 [ENVIRONMENT §4](ENVIRONMENT.md)。SPEC 新增两条：

| 风险 | 对策 |
|---|---|
| LLM judge 与被测模型同族，评分自利 | 用 `deepseek-v4.1-flash` 作 judge（与被测 `gpt-6-luna` 不同模型），并要求输出判定依据 |
| 自动生成的评测题与语料同源，虚高 | 报告披露"自动生成 N 条 / 人工精修 M 条"，并单列人工难例分桶结果 |

## 9. 验收门禁（本 SPEC 自检）

- [x] 每条 AC 都有可执行测量方式（唯一例外 AC-02/AC-03 的最终值，已标注人工判定人）
- [x] 数据契约（chunk/meta/SSE/trace）字段齐全
- [x] 引用编号与来源列表的强约束写进契约（防假引用）
- [x] 双闸拒答与超时熔断是硬要求，不是"建议"
- [x] 明确不做项与九件套对齐
- [x] 两个自利风险（judge 同族、题料同源）有对策且要求披露
