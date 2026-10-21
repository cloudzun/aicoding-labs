# 政企 RAG 问答 + NL2SQL 问数：业界实践、评测口径与 Demo 最小可行方案

> **文档定位**：为明州数智"政企 RAG 问答"（demo1）与"NL2SQL 问数"（demo2）两个教学 demo 提供业界对标、评测口径校准与选型建议。
> **调研方法**：本文所有关键数字均来自联网检索后**实际打开原文**核对（RAGAS 官方文档与原始论文、MLPerf Inference v6.1 规则原文、OmniDocBench 榜单、Spider/Spider2.0/BIRD/CSpider/DuSQL/CHASE 官方页面与论文、各开源项目 README 原文）。凡未能打开原文核实的，一律标注"未找到"或"未核实"，不做记忆性补全。
> **时间基准**：2026-10-20。榜单会滚动更新，复现时请以当日页面为准。
> **客户原始验收指标（5 项）**：
> RAG 召回 ≥90% / 准确 ≥85% / 幻觉 ≤10% / 单轮 ≤3s；NL2SQL 解析准确 ≥85% / 响应 ≤2s。

---

## 0. 结论速览：客户 5 个指标的现实性判定

| # | 客户指标 | 判定 | 一句话结论 | 关键依据 |
|---|---|---|---|---|
| 1 | RAG 召回 ≥90% | **口径成立才算现实** | 若定义为"gold chunk 的 ID 召回"（Recall@k），90% 在 demo 语料规模下完全可达；若定义为 RAGAS `Context Recall`（按 reference claim 覆盖率），90% 是很高的门槛且测量噪声大 | [RAGAS Context Recall 公式](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_recall/) |
| 2 | RAG 准确 ≥85% | **有风险** | "准确"若指端到端答案人工判定正确率：demo 语料可控时 85% 可期；但若沿用业界多跳 RAG 基准，最权威的 MLPerf E2E-RAG 工作负载在 FRAMES 上 LLM-judge 仅约 35%（oracle 68%） | [MLPerf Inference 规则（E2E-RAG 段）](https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc) |
| 3 | 幻觉 ≤10% | **口径成立才算现实** | 换算为 `1 - Faithfulness ≤ 10%`，即 faithfulness ≥ 0.90。这是 RAGAS 三个指标中**与人类判断一致性最高**的一个（0.95），因此可达也可测；若客户指"人工发现的错误陈述比例"，需另立流程 | [RAGAS 论文 Table 1](https://arxiv.org/html/2309.15217v2) |
| 4 | 单轮 ≤3s | **对"完整长答案"不现实；对"首字延迟"现实** | 以 MLPerf 交互档 SLO（TTFT 450–500ms、TPOT 30–40ms/token）反推，3s 内若含 500ms 首字，只剩 2.2s ≈ 70 token ≈ 50 汉字，装不下一条政策解读。必须改写为"首字 ≤1s + 流式"或"限长答案" | [MLPerf Inference 规则（TTFT/TPOT 约束表）](https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc) |
| 5 | NL2SQL 解析准确 ≥85% / 响应 ≤2s | **准确率有风险；响应 2s 只在"零重试"路径成立** | 中文 NL2SQL 的客观上限：CSpider 榜首 test Exact Set Match 仅 62.1；CHASE（中文跨库多轮）最佳方法整体 EM 仅 40%、序列级 16%。2s 只在"单次生成 + SQL ≤60 token + schema 已注入缓存 + 不触发自纠错"时成立 | [CSpider 榜单](https://taolusi.github.io/CSpider-explorer/)、[CHASE 论文摘要](https://aclanthology.org/2021.acl-long.180/)、[Spider 1.0 榜单](https://yale-lily.github.io/spider) |

**给客户的一句话建议**：把 5 个指标从"结果指标"改写为"**可复现口径 + 测试集定义 + 分位数口径**"三件套，否则验收当天双方会对同一个数字给出不同解释（详见 §1.3.2 与 §2.3.1）。

---

# 第一部分 政企 RAG 问答

## 1.1 业界怎么做

### 1.1.1 企业级 RAG 参考架构（六层）

业界成熟方案已经收敛为固定的六层链路，RAGFlow 的官方架构描述基本代表了这一共识：

```
① 接入层   PDF/DOCX/XLSX/扫描件/网页/结构化数据源
     ↓
② 解析层   版式分析 + OCR + 表格识别 + 阅读顺序还原（DeepDoc / VLM）
     ↓
③ 切分层   模板化/语义化 chunking，保留 page、bbox、层级标题
     ↓
④ 检索层   向量召回 + 全文/BM25 召回 → 融合（RRF / 加权）→ cross-encoder 重排
     ↓
⑤ 生成层   上下文拼装（含"黄金段落优先"）+ 强约束提示词 + 流式输出
     ↓
⑥ 溯源层   [N] 角标 → chunk → 原文页码/坐标 → 高亮回跳
```

RAGFlow 官方 README 明确列出这几项能力：Deep document understanding 解析复杂版式、Template-based chunking、Multiple recall paired with fused re-ranking、**Grounded citations with reduced hallucinations**（chunk 可视化干预 + 可追溯引用）、以及 Agentic Retrieval（多步检索）。同时说明开源版 DeepDoc 的版式分析、OCR、表格识别走 **CPU 推理**——这是延迟预算里必须提前算进去的一笔。[RAGFlow README](https://github.com/infiniflow/ragflow)

**关键判断：政企场景的 RAG 质量瓶颈不在"用哪个向量库"，而在解析层与切分层的保真度。** 解析错一个字（尤其"不得""不低于""除外"这类否定/限定词）就会让答案南辕北辙，而这类错误在 retrieval 指标上完全不可见。所以 §1.2 把解析工具单列一张表。

### 1.1.2 中文政企文档解析：难点与工具实测口碑

政企文档的四类硬骨头：**PDF 版式（多栏、页眉页脚、跨页表格）、红头文件（版式固定但印章/水印干扰）、表格（合并单元格、无线表、三线表）、扫描件（低 DPI、倾斜、印章遮挡）**。

业界已有公开、可复现的横评基准 **OmniDocBench**（CVPR 2025）：1651 个 PDF 页面，覆盖 10 类文档、5 类版式、5 种语言，含 28 类块级 + 4 类行内标注、阅读顺序标注，并提供端到端评测代码。总榜 Overall 的定义是：

$$\text{Overall}=\frac{(1-\text{Text Edit Distance})\times 100 + \text{Table TEDS} + \text{Formula CDM}}{3}$$

**OmniDocBench v1.6 端到端实测（截至 2026-10 页面）关键行**（分数越高越好，Edit 越低越好）：

| 方案 | 路线 | 参数量 | Overall↑ | Text Edit↓ | Table TEDS↑ | 说明 |
|---|---|---|---|---|---|---|
| TeleOCR | 专用 VLM | 1.2B | **96.91** | 0.0267 | 96.82 | 当前榜首 |
| PaddleOCR-VL-1.6 | 专用 VLM | 0.9B | 96.34 | 0.0326 | 94.76 | 中文生态成熟 |
| **MinerU2.5-Pro** | 专用 VLM | 1.2B | **95.75** | 0.036 | 93.42 | 开源可自部署，中文支持好 |
| GLM-OCR | 专用 VLM | 0.9B | 95.22 | 0.044 | 92.83 | — |
| Gemini 3 Pro | 通用 VLM | — | 92.91 | 0.064 | 89.15 | 闭源 API |
| GPT-5.2 | 通用 VLM | — | 86.59 | 0.114 | 82.95 | 闭源 API |
| **MinerU-Pipeline** | 传统流水线 | — | **86.47** | 0.055 | 81.88 | 旧版 pipeline 路线 |
| **Marker** | 传统流水线 | — | **78.44** | 0.157 | 65.77 | — |

来源：[OmniDocBench README / v1.6_full 榜单](https://github.com/opendatalab/OmniDocBench)

**两个可直接用于选型结论的事实**：
1. **专用小 VLM（0.9–1.2B）全面优于传统 pipeline，Overall 差距约 9–18 个点**（MinerU2.5-Pro 95.75 vs MinerU-Pipeline 86.47 vs Marker 78.44）。这对 demo 的意义是：**别自己写 pdfplumber/正则流水线**，直接用 MinerU 或 PaddleOCR-VL。
2. **MinerU2.5-Pro 与榜首只差 1.2 个点，但可私有化部署**——政企数据不出域，这是决定性因素。MinerU 的许可是 **Apache 2.0 + 附加条件**（MinerU Open Source License），商用前必须读 LICENSE.md 原文。[MinerU README - License](https://github.com/opendatalab/MinerU)

> **注意（许可红线）**：OmniDocBench 数据集本身的版权声明为"**for research purposes only and not for commercial use**"，可以用来做内部评测，不能进交付物。[OmniDocBench 版权声明](https://github.com/opendatalab/OmniDocBench)
>
> **未找到**：Docling 与 Unstructured 在 OmniDocBench **v1.6 总榜**上的最新公开分数（README 更新日志记载二者曾被评测、模型信息表也列出，但 v1.6_full 榜单中未列此行）。给客户讲时请勿引用二者的 OmniDocBench 分数，只能说"传统规则/流水线路线在同类基准上显著低于 VLM 路线"。

**MinerU 对"可点回原文"的直接价值**：MinerU 的 locator 机制给出稳定的 `doc:{id}/tier:{tier}/page:{n}/block:{m}` 定位串，并可 `--format image` 导出该页/该块的图片用于前端高亮——这正好是段级溯源需要的最小原语。[MinerU README - Agent Contract / Locator](https://github.com/opendatalab/MinerU)

### 1.1.3 检索与重排

- **混合检索已成为默认**：稠密向量 + 稀疏/全文双路召回再融合。pgvector 官方便给出与 Postgres 全文检索组合、用 **Reciprocal Rank Fusion（RRF）或 cross-encoder** 合并结果的示例。
- **bge-m3 一类模型把"混合检索"内建到单个模型**：M3-Embedding 同时支持 dense retrieval、multi-vector retrieval、sparse retrieval 三种检索功能，覆盖 100+ 工作语言，输入粒度到 8192 token。这意味着 demo 里**一个模型同时产稠密与稀疏向量**，不必再单独维护 BM25 索引。[M3-Embedding 论文（bge-m3）](https://arxiv.org/abs/2402.03216)
- **重排（rerank）用 cross-encoder**：query 与候选段落成对打分，精度高于双塔向量召回，但成本随候选数线性增长。工程上标准做法是"召回 50–100 → 重排 → 取 top 5–8 进上下文"。

### 1.1.4 多轮对话记忆与指代消解

业界三种做法，按工程成本排序：

| 做法 | 机制 | 优点 | 风险 |
|---|---|---|---|
| **查询改写（query rewriting）** | 把"它/这个/上面说的第二条"连同最近 N 轮历史，压成一条自包含的检索 query 再检索 | 检索层完全不改，改动最小 | 改写错→检索全错，且需多一次 LLM 调用（延迟 +300ms 起） |
| **会话级记忆摘要** | 滚动摘要历史，拼进 prompt | 省 token | 摘要丢失细节，溯源断链 |
| **结构化会话状态（槽位）** | 抽取话题实体/时间范围/口径作为显式槽位，检索时作为过滤条件 | 可解释、可审计、可复用 | 需领域建模 |

**对政企场景的建议**：指代消解**优先规则+槽位**（"第二条"→ 指上一轮回答中的第 2 条引用），**兜底才用小模型改写**。原因是政企问句的指代高度模式化，规则准确率远高于 LLM 改写，且零延迟。

> **未找到**：可引用的、专门评测中文政企多轮 RAG 指代消解准确率的公开基准。CHASE 是多轮中文 text-to-SQL（见 §2.3），不能直接迁移到 RAG。

### 1.1.5 段级 citation（可点回原文）的工程实现

这是"可视化交互 + 段落级溯源"的技术核心。业界最直接可抄的实现是 LlamaIndex 的 **CitationQueryEngine**，其源码揭示了完整机制：

1. 检索拿到 node（可能是整页/整节）后，**再按 512 字符、20 字符重叠切成 citation chunk**（`DEFAULT_CITATION_CHUNK_SIZE = 512`，`DEFAULT_CITATION_CHUNK_OVERLAP = 20`）；
2. 每个 chunk 前面拼上 `Source N:` 编号；
3. 提示词强制模型"**只依据给定来源作答，引用时必须用对应编号，且每个答案至少包含一个引用**"，并给出 few-shot 示例（`Answer: Water will be wet when the sky is red [2], which occurs in the evening [1].`）；
4. 生成后把 `[N]` 反查回 chunk → 再反查回原文位置。

关键源码注释还暴露了一个**极易踩的坑**：切分时它主动丢弃了原 node 的 `id_`、`start_char_idx`、`end_char_idx`，因为切分后这些字段已不描述新 chunk——**这意味着"可点回原文"必须由你自己额外携带 `(doc_id, page_no, bbox, char_offset)` 元数据**，不能依赖框架默认字段。[LlamaIndex citation_query_engine.py](https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/query_engine/citation_query_engine.py)

**渲染链路（可点 → 高亮的完整闭环）**：
```
[3] 角标
  → citation_id → {doc_id, page_no, block_no, bbox, char_start, char_end}
  → 前端：PDF.js 跳 page_no + 叠加 bbox 半透明高亮
  → 或：MinerU 导出的该 block 截图（mineru read ".../block:7" --format image）
```
RAGFlow 的做法与此一致：chunk 可视化 + 可追溯引用。[RAGFlow README](https://github.com/infiniflow/ragflow)

### 1.1.6 延迟预算：3 秒目标在什么条件下能达成

**先给业界公认的"交互式"延迟门槛**。这是目前能找到的最权威、最可引用的公开 SLO——MLPerf Inference v6.1 对每个 LLM 工作负载规定了两档延迟约束（Server/Conversational 档 vs Interactive 交互档），两项指标定义为：TTFT（首 token 延迟）与 TPOT（每输出 token 平均间隔）：

| 工作负载 | 模型 | Conversational 档 TTFT/TPOT | **Interactive 档 TTFT/TPOT** |
|---|---|---|---|
| Summarization | Llama3.1-8B | 2000 ms / 100 ms | **500 ms / 30 ms** |
| Question Answering | Llama2-70B | 2000 ms / 200 ms | **450 ms / 40 ms** |
| Reasoning | DeepSeek-R1 | 2000 ms / 80 ms | **1500 ms / 15 ms** |
| Text Generation | GPT-OSS-120B | 3000 ms / 80 ms | **2000 ms / 20 ms** |

来源：[MLPerf Inference Rules — Scenarios/Benchmarks 表](https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc)（原文：`mlcommons/inference_policies/inference_rules.adoc`）

**用这张表反推 3 秒目标的可行性**（以下为基于上述阈值的算术推演，非实测）：

设交互档 TTFT = 500 ms、TPOT = 30 ms/token，检索+重排合计留 300 ms：

```
可用生成时间 = 3000 - 500(TTFT) - 300(检索重排) - 100(网络/渲染) = 2100 ms
可生成 token 数 = 2100 / 30 = 70 token ≈ 50 个汉字
```

**结论：一条 50 汉字以内的短答复能在 3s 内完成；一条 200–300 字的政策解读（≈250–400 token）需要 500+250×30ms ≈ 8s。** 换言之：

- ✅ **"单轮 ≤3s"在下列条件下成立**：答案受控在 ~50 汉字内；或指标定义为"**首字延迟（TTFT）≤1s + 流式输出**"；或用更小的模型 + 更快的 TPOT（如 10 ms/token，则 3s 可容纳约 220 token ≈ 150 汉字）。
- ❌ **"单轮 ≤3s 且答案是完整政策解读"不成立**，任何厂商宣称做到，都要追问"答案长度是多少、是否流式、TTFT 还是 TTLT"。

**分环节延迟量级（工程经验值，标注来源）**：

| 环节 | 量级 | 性质 |
|---|---|---|
| 查询改写/指代消解 | 0–150 ms（规则）/ 200–500 ms（小模型） | 工程估计 |
| 向量检索（HNSW，万–百万 chunk） | 5–50 ms | 依据 pgvector HNSW 机制与默认参数；MLPerf E2E-RAG 用 FAISS HNSW `efSearch=100` |
| 全文/BM25 召回 | 5–30 ms | 依据 pgvector 全文检索集成 |
| RRF 融合 | <5 ms | 工程估计 |
| Cross-encoder 重排（50 候选） | 50–300 ms（GPU / CPU 差异极大） | **未找到公开 p95 基准**，需自测 |
| LLM TTFT | 450–500 ms | MLPerf Interactive 档 |
| LLM 解码 | 15–40 ms / token | MLPerf Interactive 档 |

> **诚实标注**：截止本次调研，**未找到**同时给出"检索 + 重排 + 生成"三段 p95 的端到端中文 RAG 公开延迟基准。MLPerf 虽然在 v6.1 引入了 **E2E-RAG** 工作负载（见 §1.3.5），但它只要求 Offline 场景，**没有设定延迟约束**，因此不能作为 3s 目标的依据。demo 阶段必须自建埋点实测。

---

## 1.2 主流工具对比表

### 表 1-1 应用编排 / RAG 引擎层

| 工具 | 定位 | 关键能力（原文核对） | 许可 | 适用判断 |
|---|---|---|---|---|
| **RAGFlow** | 开源 RAG 引擎（含 Agent） | DeepDoc 深度文档理解；模板化 chunking；**多路召回 + 融合重排**；**Grounded citations**（chunk 可视化 + 可追溯引用）；Agentic Retrieval（Low/Medium/High/Ultra 思考档）；Knowledge Compilation（Wiki/Graph/Tree/PageIndex/思维导图/时间线） | Apache 2.0 | **政企 RAG 首选**：citation 与解析是内置能力，不用自己造 |
| **Dify** | LLM 应用开发平台 | 可视化 Workflow 画布；Prompt IDE；RAG Pipeline（PDF/PPT 等开箱解析）；Agent + 插件市场 + MCP；LLMOps 观测 | Dify Open Source License（Apache 2.0 + 附加条件） | 适合快速搭"可演示的产品外壳"，解析深度不如 RAGFlow |
| **LlamaIndex** | 代码级 RAG 框架 | `CitationQueryEngine` 提供 citation 全链路原语；可自由替换 retriever/reranker/splitter | MIT（生态包许可各异） | **需要完全掌控链路时选它**；demo 里做"可点回原文"最省事 |
| **LangGraph** | 有状态 Agent 编排 | 图状态机，适合多轮 + 工具调用 + 自纠错循环 | MIT | 只有"多轮 Agent 化"才需要；单纯 RAG 属过度设计 |
| **FastGPT** | 知识库问答应用 | 知识库 + 工作流编排 | 见仓库 LICENSE（**本次未逐条核对**） | 与 Dify 同质，选一个即可 |

### 表 1-2 文档解析层

| 工具 | 路线 | 中文/表格表现 | 可私有化 | 许可 | 备注 |
|---|---|---|---|---|---|
| **MinerU** | 专用 VLM（MinerU2.5-Pro 1.2B） | OmniDocBench Overall **95.75**、Table TEDS 93.42 | ✅ 支持 vLLM/LMDeploy/llama.cpp，有 Docker | Apache 2.0 + 附加条件 | **推荐**；提供 page/block locator，天然支撑溯源 |
| **PaddleOCR / PaddleOCR-VL** | 专用 VLM | PaddleOCR-VL-1.6 Overall **96.34** | ✅ | Apache 2.0（**生态组件许可需逐项确认**） | 中文 OCR 生态最成熟；PP-StructureV3 为流水线版 |
| **docling** | 文档转换（IBM） | 本次**未取得 v1.6 榜单公开分数** | ✅ | MIT（**未逐条核对**） | 轻量、易嵌入，但高难版式需自测 |
| **Unstructured** | 规则/启发式 + 模型分区 | 本次**未取得 v1.6 榜单公开分数** | ✅ | Apache 2.0（开源版） | 适合结构规整文档；复杂表格需自测 |
| 传统 pipeline（MinerU-Pipeline / Marker） | 规则 + 小模型串联 | Overall 86.47 / 78.44 | ✅ | — | **不建议新项目采用** |

> 引用来源：[OmniDocBench 榜单](https://github.com/opendatalab/OmniDocBench)、[MinerU README](https://github.com/opendatalab/MinerU)

### 表 1-3 向量/混合检索存储

| 方案 | 定位 | 与政企相关的关键机制 | 许可 | 选型建议 |
|---|---|---|---|---|
| **pgvector** | Postgres 扩展 | 支持精确/近似检索；HNSW 与 IVFFlat 两种索引（HNSW 默认 `m=16, ef_construction=64`，查询 `hnsw.ef_search` 默认 40）；`vector` 上限 2000 维 / `halfvec` 4000 维 / 二值量化 64000 维；**ACID、PITR、JOIN、行级权限天然可用**；可与全文检索组合做 hybrid + RRF | 开源（PostgreSQL License） | **政企 demo 首选**：权限过滤、审计、事务都是现成的 |
| **Milvus** | 分布式向量数据库 | 面向十亿级向量的水平扩展 | Apache 2.0 | 只有向量规模到亿级才需要；demo 属过度设计 |
| **Qdrant** | 向量数据库 | 强过滤、payload 索引 | Apache 2.0 | 中等规模、过滤条件复杂时的选择 |

> ⚠️ **pgvector 的一个必须知道的坑（直接决定"按部门/密级过滤"能不能用）**：README 明确写了——近似索引下**过滤是在索引扫描之后才应用**。"若某条件匹配 10% 的行、HNSW 默认 `ef_search=40`，则平均只有 4 行会命中"；需开启 `hnsw.iterative_scan = strict_order / relaxed_order` 才能自动扩大扫描，或用 partial index / 分区。**政企 RAG 几乎一定要按文档密级/部门过滤，这一条必须在选型会上讲清楚。** [pgvector README - Filtering / Iterative Index Scans](https://github.com/pgvector/pgvector)

### 表 1-4 模型层（中文）

| 组件 | 作用 | 关键事实 | 来源 |
|---|---|---|---|
| **bge-m3（M3-Embedding）** | 嵌入模型 | **单模型同时支持 dense / multi-vector / sparse 三种检索**；100+ 语言；最长 8192 token | [arXiv:2402.03216](https://arxiv.org/abs/2402.03216) |
| **bge-reranker 系列** | cross-encoder 重排 | 输入 query–doc 对输出相关性分数（模型卡：[BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3)）。**其官方延迟基准本次未取得，需自测** | — |

---

## 1.3 评测口径与真实基线

### 1.3.1 RAGAS 四指标的精确定义（逐条抄自官方文档）

| 指标 | 官方公式 | 含义与坑 |
|---|---|---|
| **Faithfulness** | $\frac{\text{response 中被 context 支持的主张数}}{\text{response 中主张总数}}$ | 先让 LLM 把答案拆成 statement，再逐条判"能否由检索上下文推出"。**"幻觉率"最标准的自动代理就是 `1 - Faithfulness`** |
| **Context Recall** | $\frac{\text{reference 中被检索上下文支持的主张数}}{\text{reference 中主张总数}}$ | **注意：它不比对 chunk id，而是拿 reference answer 的 claim 反查检索内容**。所以它是"信息覆盖度"，不是"文档召回率"，很容易被答非所问的宽泛检索"骗"到高分 |
| **Context Precision** | $\frac{\sum_{k=1}^{K}(\text{Precision@}k \times v_k)}{\text{top-}K\text{ 中相关项总数}}$，$v_k\in\{0,1\}$ | 衡量"相关 chunk 是否排在前面"。官方示例：同一组两个 chunk，无关 chunk 排第 2 位时分数 0.9999，排第 1 位时掉到 0.4999 |
| **Answer Relevancy** | $\frac{1}{N}\sum_{i=1}^{N}\cos(E_{g_i},E_o)$，默认 $N=3$ | 用 LLM **反向生成 3 个问题**，再与原始问题算 embedding 余弦相似度。**它完全不含事实性**，只测"答得切题不切题" |

来源：[Faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/)、[Context Recall](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_recall/)、[Context Precision](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/)、[Answer Relevancy](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/answer_relevance/)

> **版本演进提示**：RAGAS 2023 原始论文里的第三个指标叫 **Context Relevance**，公式是 $\frac{\text{被抽取的相关句子数}}{\text{上下文总句子数}}$，与现在的 Context Precision@k **不是同一个东西**。跨版本对比数字前必须确认指标版本。[RAGAS 论文 §3](https://arxiv.org/html/2309.15217v2)

> **降本选项**：Faithfulness 第二步可用 **Vectara HHEM-2.1-Open**（T5 分类器）替代 LLM judge，官方文档明确支持，适合大批量回归评测。[RAGAS Faithfulness 文档](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/)

### 1.3.2 业界怎么定义"召回率"和"幻觉率"——以及我们该选哪个

**"召回率"有三种互不等价的定义，必须让客户指名是哪一种：**

| 定义 | 计算 | 可复现性 | 适用 |
|---|---|---|---|
| A. **Chunk ID Recall@k** | 命中的 gold chunk id 数 / gold chunk id 总数 | ⭐⭐⭐ 完全确定 | **验收首选**。RAGAS 也提供 `IDBasedContextRecall`，公式为 $\frac{\text{retrieved 中出现过的 reference id 数}}{\text{reference id 总数}}$ |
| B. **RAGAS Context Recall** | 见上表 | ⭐ LLM judge，有抖动 | 无 gold chunk 标注时的替代 |
| C. **End-to-end 答对率** | 答案正确条数 / 总条数 | ⭐⭐ 人工判定 | 这是"准确率"，不是召回率 |

> 常见误读：拿 C 的 90% 说成"召回 90%"。**召回与端到端准确率之间不存在单调关系**——召回 95% 但重排把金段落挤出 top-5，端到端仍然错。RAGAS 文档把 `IDBasedContextRecall`、`NonLLMContextRecall`、`LLMContextRecall` 分开列，正是在提醒这是三件不同的事。[Context Recall 文档](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_recall/)

**"幻觉率"三种定义：**

| 定义 | 计算 | 适用与代价 |
|---|---|---|
| A. **1 − Faithfulness** | 按 claim 粒度，自动 | **推荐用于 demo 验收**：可规模化、与其他团队可比、与人类判断一致性 0.95 |
| B. **不可回答题上的编造率** | 在"语料中本来没有答案"的题集上，模型未拒答（硬编答案）的比例 | **必须单独建题集**。学界把这项能力叫 negative rejection，是 RAG 四大基础能力之一，且现有 LLM "表现显著挣扎" |
| C. **人工标注的错误陈述率** | 逐句人工判定 | 最贴近客户直觉，但贵、不可高频 |

> B 的理论依据：[RGB 基准](https://arxiv.org/abs/2309.01431)（AAAI 2024）系统评测了 RAG 的四种基础能力——noise robustness、**negative rejection**、information integration、counterfactual robustness，结论是模型在 noise robustness 上尚可，但在**拒绝回答、信息整合、处理假信息三项上明显不足**。这直接说明：如果客户的"幻觉率"指的是"该说不知道时乱说"，那么 faithfulness 测不出来，必须单独设题。

**建议的验收口径（可直接写给客户）**：
- 召回率 ≜ **Chunk-ID Recall@5**（gold 段落被 top-5 覆盖的比例），测试集每条样本都必须人工标注 1–3 个 gold chunk id。
- 准确率 ≜ **端到端答案正确率**（人工按"结论正确且关键数字/条款无错"二元判定），另附 RAGAS faithfulness 作参考。
- 幻觉率 ≜ **max(1 − Faithfulness 均值, 不可回答集编造率)**，两值都要报，取差的那个作为对外口径。

### 1.3.3 golden set 规模惯例

**业界公开的参考点**：
- RAGAS 原始验证集 **WikiEval 只有 50 条**（50 个维基页面各 1 问，2 名标注员，faithfulness/context relevance 标注者间一致率约 95%、answer relevance 约 90%）。[RAGAS 论文 §4](https://arxiv.org/html/2309.15217v2)
- MLPerf E2E-RAG 工作负载用 **FRAMES 数据集 824 题**（QSL Size = 824）。[MLPerf Inference Rules](https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc)

**一个必须让客户看到的算术**（以下为本报告按二项分布计算，非引用）：目标值 p≈0.9 时，95% 置信区间的半宽 ≈ $1.96\sqrt{p(1-p)/n}$：

| golden set 规模 n | 95% CI 半宽（p=0.9） | 能否区分 85% 与 90%？ |
|---|---|---|
| 50 | ±8.3 pp | ❌ 不能 |
| 100 | ±5.9 pp | ❌ 勉强不能 |
| 150 | ±4.8 pp | ⚠️ 边缘 |
| 200 | ±4.2 pp | ⚠️ 可以 |
| 400 | ±2.9 pp | ✅ 可以 |

**结论：如果客户要求"准确 ≥85%"与"召回 ≥90%"这类 5 个百分点量级的判定，golden set 至少要 200 条，最好 400 条。用 50 条做验收，双方会为"是不是 88%"吵一天。** demo 阶段建议 **200 条**，按能力分层：约 60% 单跳可回答、20% 跨文档/多跳、10% 多轮指代、10% 不可回答（用于测 negative rejection）。

### 1.3.4 LLM-as-judge 的可靠性——到了什么程度可以签字

| 证据 | 数字 | 含义 |
|---|---|---|
| RAGAS 与人类判断的一致性（WikiEval，pairwise accuracy） | Faithfulness **0.95** / Answer Relevance **0.78** / Context Relevance **0.70** | **Faithfulness 可信；Context Relevance 只有 0.70，不能用来卡 85% 的验收线** |
| RAGAS vs 两个基线（同一数据集） | GPT Score 0.72/0.52/0.63；GPT Ranking 0.54/0.40/0.52 | RAGAS 的"拆句 + 逐条核验"设计显著优于"直接打分/排序" |
| 通用 LLM-as-judge（MT-Bench / Chatbot Arena） | GPT-4 类强判官与人类偏好一致率 **>80%**，与人类之间的一致率同量级 | 可作为规模化评测工具，但**不是金标准** |
| 已知偏差 | **位置偏差、冗长偏差、自我增强偏差、推理能力有限** | 必须做：随机化候选顺序、双向评测、给判官换模型 |

来源：[RAGAS 论文 Table 1 / §4–5](https://arxiv.org/html/2309.15217v2)、[Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena（NeurIPS 2023）](https://arxiv.org/abs/2306.05685)

**实操建议**：
1. 对外承诺的数字，**必须是人工判定**（200 条，2 人独立标注，分歧仲裁）；RAGAS 数字只作过程指标与回归防线。
2. RAGAS 里**只用 Faithfulness 报对外幻觉率**；Context Precision / Answer Relevancy 只作内部调优信号（0.70–0.78 的可靠性不足以支撑 5pp 的争议）。
3. 判官模型与被测模型不能是同一个（自我增强偏差）。

### 1.3.5 可引用的公开基线（讲给客户听最有力的一组）

**MLPerf Inference v6.1 引入了端到端 RAG 工作负载 E2E-RAG**，这是目前"业界标准怎么测 RAG"的最高权威：

| 项目 | 内容 |
|---|---|
| 数据集 | FRAMES（Wikipedia 多跳问答），QSL 824 |
| 检索 | 稠密向量 + **FAISS HNSW**，固定参数 `M=32, efConstruction=200, efSearch=100` |
| 重排 | **ColBERTv2** |
| 编排 | GPT-OSS-120B 做 query 分解 + 充分性检查；GPT-OSS-20B 做文档相关性评分；GPT-OSS-120B 生成答案 |
| 多跳轮次 | **最多 5 轮**（所有提交者必须设为 5） |
| 评测 | **LLM as a judge**（Llama3.1-8B），质量目标为 FP32 的 97% |
| **实测结果** | **LLM judge 准确率仅约 35%（±3%）**，而 FRAMES 的 oracle 上限是 **68%** |
| 归因（原文） | 向量检索的嵌入质量与近似误差、多跳知识层级与推理难度、重排模型识别相关文档的能力不足、上下文窗口限制；**多轮检索把准确率从 20% 提到约 35%** |

来源：[MLPerf Inference Rules — E2E-RAG FAQ](https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc)

**这组数字的战略价值**：当客户问"为什么不能承诺 95% 准确率"时，最有力的回答不是"很难"，而是"**业界最权威的端到端 RAG 评测，用最强模型 + 最强检索栈，在多跳题上的公开成绩是 35%**"。而 demo 的语料是**封闭域、单跳为主、政策文档结构清晰**，所以 85% 是合理的——**但必须先说清楚"我们的测试集构成与 FRAMES 不同"**，否则 85% 会被当成普遍能力承诺。

**另一组可用基线（中文、四能力诊断）**：RGB 基准（英文 + 中文双语），从 noise robustness / negative rejection / information integration / counterfactual robustness 四个维度诊断 RAG，结论是现有模型在 noise robustness 上尚可、其余三项明显不足。[RGB 论文](https://arxiv.org/abs/2309.01431)

### 1.3.6 延迟基线

见 §1.1.6 的 MLPerf TTFT/TPOT 表。补充要点：
- MLPerf 的 E2E-RAG **只要求 Offline 场景、没有延迟约束**，所以"业界标准"目前并不给 RAG 定端到端延迟线；3s 是客户自定目标，**需要我们自己定义口径才有意义**。
- 唯一可引用的硬门槛是 TTFT 450–500ms（交互档）。**建议对客口径："检索 + 首字 ≤1.2s，全文流式完成 p95 ≤5s（答案 ≤300 字）"**。

---

## 1.4 我们 demo 的最小可行方案（含技术选型）

### 1.4.1 架构选型（一句话：RAGFlow 做骨架，LlamaIndex 做 citation 精细控制，pgvector 做存储）

| 层 | 选型 | 理由 | 备选 |
|---|---|---|---|
| 解析 | **MinerU 2.5（VLM 档）** | OmniDocBench 95.75，可私有化，自带 page/block locator → 直接支撑溯源 | PaddleOCR-VL-1.6（96.34，但生态组件许可需核） |
| 切分 | **按文档结构切（标题层级 + 表格独立成块），512 字 / 20 重叠对齐 citation 粒度** | 与 LlamaIndex CitationQueryEngine 默认值一致，避免二次切分破坏溯源 | RAGFlow 模板化 chunking |
| 嵌入 | **bge-m3**（dense + sparse 同时出） | 单模型搞定混合检索，省一套 BM25 维护 | bge-large-zh + 独立 BM25 |
| 存储 | **pgvector** | 权限过滤、审计、事务、全文检索都在 Postgres 里；demo 数据量（万级 chunk）绰绰有余 | Milvus/Qdrant（规模上来再换） |
| 重排 | **bge-reranker-v2-m3**（cross-encoder） | 精度显著优于双塔，成本可接受 | 无（跳过重排会掉精度） |
| 编排 | **RAGFlow** 起步；需要完全控制 citation 时用 **LlamaIndex** 重写检索-生成段 | 两者都是 Apache/MIT 系，可混用 | Dify（更偏产品外壳） |
| 生成 | 国产/私有化模型（客户环境约束），流式输出 | TTFT 是体验关键 | — |
| 前端 | PDF.js + bbox 高亮；`[N]` 角标点击 → 跳页高亮 | 满足"可视化交互 + 段落级溯源" | MinerU block 截图 |

### 1.4.2 三个必须提前定死的工程点

1. **chunk 元数据契约**（不然后面无法点回原文）：
   ```json
   { "chunk_id": "...", "doc_id": "...", "doc_title": "...", "page_no": 12,
     "block_no": 7, "bbox": [x1,y1,x2,y2], "char_start": 0, "char_end": 512,
     "heading_path": ["第三章","第十二条"], "effective_date": "2026-01-01" }
   ```
   注意上面的坑：LlamaIndex 切分后会**清空** `start_char_idx/end_char_idx`，必须自己维护。
2. **按密级/部门过滤**：pgvector 近似索引的过滤是**后置**的，必须用 `hnsw.iterative_scan=strict_order` 或 partial index / 分区，否则 top-5 可能只剩 4 条。
3. **时效性过滤**：政企政策有"废止/被修订"，离线索引里必须存 `effective_date` 与 `status`，检索时强过滤——否则会拿废止文件回答现行问题，这类错误在 faithfulness 里看不出来。

### 1.4.3 评测方案（可直接落地的验收包）

```
golden set：200 条
├── 120 条 单跳可回答（每条约 1–3 个 gold chunk id）
├──  40 条 跨文档/多跳
├──  20 条 多轮指代（第 2 轮含"它/上面第二条"）
└──  20 条 不可回答（语料中无答案，用于测 negative rejection）

指标：
├── 召回率 = Chunk-ID Recall@5                        （全自动）
├── 准确率 = 端到端答案正确率（2 人人工，分歧仲裁）      （对外承诺用这个）
├── 幻觉率 = max(1 − Faithfulness, 不可回答集编造率)     （自动 + 自动）
└── 延迟   = TTFT p50/p95、TTLT p50/p95、检索/重排分段耗时（埋点自测）
```

**特别注意**：检索分段与生成分段必须分别打点。否则 3s 超标时无法定位是检索慢还是生成慢，而这两者的优化手段完全不同。

### 1.4.4 建议对客改写的指标表述

| 原指标 | 建议改写 | 为什么 |
|---|---|---|
| 召回 ≥90% | **Chunk-ID Recall@5 ≥ 90%**（200 条 golden set） | 可复现、无 LLM 噪声 |
| 准确 ≥85% | **端到端答案正确率 ≥ 85%**（200 条，2 人标注；同时报 RAGAS faithfulness） | 把"准确"锚定到人工判定 |
| 幻觉 ≤10% | **Faithfulness ≥ 0.90 且 不可回答集编造率 ≤ 10%** | faithfulness 是可靠性 0.95 的指标，敢签字 |
| 单轮 ≤3s | **TTFT ≤ 1.0s（p95）+ 全文流式完成 ≤ 5s（p95，答案 ≤300 字）**；若坚持 3s，则限定"答案 ≤50 字"场景 | 见 §1.1.6 算术推演 |

---

# 第二部分 NL2SQL 问数

## 2.1 业界怎么做

### 2.1.1 基准全景（先建立"真实上限"的坐标系）

| 基准 | 规模 | 语言/特点 | 指标口径 | 真实成绩 |
|---|---|---|---|---|
| **Spider 1.0** | 10,181 问 / 5,693 唯一 SQL / 200 DB / 138 领域 | 英文，跨域，train/test 数据库不重叠 | 官方指标自 2020-11 起为 **Test Suite Accuracy**；榜单另列 **Exact Set Match（不含值）** 与 **Execution with Values** | Test：miniSeek **91.2**（exec w/ values）；DAIL-SQL+GPT-4+SC **86.6**；DIN-SQL+GPT-4 **85.3**。而 Exact Set Match 上 DIN-SQL+GPT-4 只有 **60.0** |
| **Spider 2.0** | 632 题（Snow 547 / DBT 68 / Lite 547） | 企业级真实工作流，DB 常 >1000 列，BigQuery/Snowflake 方言，SQL 常超 100 行 | 执行结果比对（CSV 输出） | 论文时代 o1-preview **17.1%**、GPT-4o **10.1%**（对照 Spider 1.0 的 86.6%）；**2026-10 榜单**：榜首 Genloop Sentinel v2 Pro **96.70**，而 Spider-Agent+Claude-4-Sonnet 仅 **25.78** |
| **BIRD** | 12,751 问-SQL 对 / 95 DB / 33.4 GB / 37 领域 | 英文，脏值、外部知识、效率要求 | **EX（Execution Accuracy）** + VES/R-VES（效率） | 人类（数据工程师+DB 学生，有 oracle knowledge）**92.96**；公开榜首 GrainSQL **82.95**（2026-09） |
| **CSpider** | 10,181 问（Spider 全量中译）/ 200 DB | 中文；表名列名仍为英文（增加难度）；中文分词/零代词问题 | Exact Set Match（不含值） | Test 榜首 FastRAT+AST Ranking+GPT-4 **62.1**；Robeta+Seq2SQL 60.6 |
| **DuSQL** | 200 DB / 813 表 / **23,797** 问-SQL 对 | 中文，按真实应用分布构造，含较多行列计算类 SQL | 论文自定 | — |
| **CHASE** | **5,459 个连续问题序列 / 17,940 问+SQL / 280 DB** | 中文**跨库、上下文相关**；仅 35% 问题与上下文无关、28% 为简单 SQL | Exact Match | **最佳方法整体 EM 仅 40%，序列级仅 16%** |

来源：[Spider 1.0 官方站与榜单](https://yale-lily.github.io/spider)、[Spider 2.0 官方站与榜单](https://spider2-sql.github.io/)、[BIRD 官方站与排行榜](https://bird-bench.github.io/)、[CSpider 官方站与榜单](https://taolusi.github.io/CSpider-explorer/)、[DuSQL 论文](https://aclanthology.org/2020.emnlp-main.562/)、[CHASE 论文](https://aclanthology.org/2021.acl-long.180/)

**三个结论，直接决定 demo 的成功标准**：
1. **中文比英文难 20 个点以上**：同一评测体系下 Spider 英文 Exact Set Match 榜首 81.5，CSpider 中文榜首 62.1。所以客户说的"解析准确 85%"若对齐 Spider 英文标准，是超过人类公开水平的数字。
2. **多轮中文更难**：CHASE 最佳 40% EM / 16% 序列级。demo2 若含多轮追问，85% 绝无可能。
3. **Spider 2.0 的 96.70% 与 25.78% 并存，说明"系统编排"比"基座模型"更决定成败**——同一底座模型，agent 编排不同，差距 3–4 倍。这既是风险也是机会：**demo 的分数很大程度由我们设计的链路决定，而不是选的模型**。

### 2.1.2 技术链路（2026 年的主流做法）

```
① 语义层建模（先做，收益最大）
   表/列 → 业务同义词、枚举值映射、指标定义、已认证 JOIN 路径
     ↓
② Schema Linking
   问题 → 相关表/列（不是把所有 DDL 塞进 prompt）
     ↓
③ Few-shot 检索
   从历史"问题-SQL 对"里检索最相似的 k 条作示例
     ↓
④ SQL 生成（+ 结构化输出约束）
     ↓
⑤ 静态校验 → 干跑（dry plan / EXPLAIN）→ 修正
     ↓
⑥ 执行 → 结果集校验 → 失败则带错误信息重试（≤ N 次）
     ↓
⑦ 结果 → 图表类型推荐 → 渲染
```

**各环节的业界证据**：
- **Spider 2.0 榜单的编排差异**：Genloop Sentinel v2 Pro 96.70 vs Spider-Agent+Claude-4-Sonnet 25.78，且 Chat2DB-Agent+Claude-4-Sonnet 38.39——同一底座，四倍差距来自 agent 编排（schema 探查、多候选生成、结果自检）。[Spider 2.0 榜单](https://spider2-sql.github.io/)
- **自纠错的固有风险**：BIRD 团队明确指出 LLM 自纠错受 **self-enhancement bias** 影响，SQL 的声明式语法与简短日志提供的反馈信号有限，其 SHARE 工作通过把 SQL 转成过程化步骤 + on-policy 多 agent 微调来缓解。[BIRD 官方站 News 2025-07-15](https://bird-bench.github.io/)
- **语义层是 2026 年的主流答案**：dbt Semantic Layer 的核心抽象是 semantic model = 实体（primary/foreign/unique/natural）+ 维度（time/categorical）+ 指标（simple metrics，含 agg/expr），由 MetricFlow 生成查询。[dbt Semantic models 文档](https://docs.getdbt.com/docs/build/semantic-models)
- **开源产品已把"语义层 + 干跑校验 + 行限制"做成工程原语**：WrenAI 的 MDL（Modeling Definition Language）以 Git 友好的 YAML/Markdown 定义 models / columns / relationships / views / **cubes / metrics**，并在生成后做 **dry-plan validation、row limits、structured errors with hints**，还有 value profiling。[WrenAI README](https://github.com/Canner/WrenAI)

### 2.1.3 "语义层"到底解决什么（为什么这是 demo 能否过 85% 的关键）

裸 LLM 生成 SQL 的错误大头不在 SQL 语法，而在**业务语义**：同一张表里"在网用户"和"有效用户"是两个口径；"收入"要含税不含税；枚举值 `1/2/3` 分别代表什么状态；哪两张表能 JOIN、通过哪个键 JOIN。

语义层把这些**从"模型每次现场猜"变成"一次性人写、机器复用"**：

| 语义层要素 | 作用 | dbt / WrenAI 的对应物 |
|---|---|---|
| 指标定义 | "政企收入" = 哪个字段、什么口径、含不含税 | dbt `metrics` / WrenAI `cubes & metrics` |
| 实体与 JOIN 路径 | 认证过的 join key，避免笛卡尔积/漏 join | dbt `entities` / WrenAI `relationships` |
| 维度 | 时间粒度、地区、产品线等可切片维度 | dbt `dimensions` / WrenAI `columns` |
| 枚举/值映射 | `status=1` 是什么意思 | WrenAI 的 value profiling / MDL 枚举 |
| 示例与文档 | "上个月"指自然月还是滚动 30 天 | WrenAI 的 `instructions.md` / `queries.yml` |

**给 demo 的结论**：如果 demo2 要讲 85%，**必须建一个最小语义层（哪怕只有 6–10 个指标 + 3 张表）**，并让系统走"指标检索 → 定义驱动生成"，而不是"把 DDL 丢给模型"。这条路顺带解决 2s 延迟（SQL 变短了，见 §2.1.6）。

### 2.1.4 自动纠错的安全边界

这是政企 demo 里**必须显式讲的一页**——因为客户是运营商，误删/误改是红线。

| 边界 | 做法 | 依据 |
|---|---|---|
| **只读账号** | 连接串使用数据库级只读账号（`GRANT SELECT`），而非仅靠应用层判断 | 业界通用实践；WrenAI/Vanna 均默认只做查询 |
| **SQL 白名单/语句类型限制** | 解析 AST，只允许单条 `SELECT`；拒绝 DDL/DML/存储过程/`INTO OUTFILE`/多语句 | WrenAI 的 dry-plan validation 与 structured errors 就是这个思路 |
| **强制 LIMIT** | 自动追加/包裹 `LIMIT N`（如 1000），前端分页 | WrenAI 明确列出 "row limits" 为治理原语 |
| **行级权限（RLS）** | 按用户所属分组自动注入过滤条件，而不是靠提示词约束 | Vanna 2.0 把 row-level security 与 audit logs 做成内建能力：[Vanna README](https://github.com/vanna-ai/vanna) |
| **重试上限** | **≤1 次**（最多 2 次 LLM 调用），且重试必须带"上一次的错误信息 + 参考 schema 片段" | 自纠错有 self-enhancement bias 风险（BIRD 团队结论），且每次重试 +1.5~2s，直接击穿 2s 指标 |
| **超时与熔断** | 单条 SQL 执行超时（如 10s）+ 结果行数上限 + 代价预估拦截（EXPLAIN 预估行数过大则拒绝） | 工程实践 |
| **审计** | 记录 (user, question, SQL, 耗时, 行数, 是否被拦截) | Vanna audit logs |
| **不可执行即降级** | 校验失败不硬猜，返回"我理解为…，请确认"或给出候选口径 | 直接降低幻觉型错误 |

> **一条容易被忽略的原则**：**自动纠错的重试次数与 2s 延迟指标在数学上互斥**。1 次重试意味着 2 次 LLM 调用。所以要么把指标改成"最终结果 ≤6s（含 1 次纠错）"，要么把重试做成"用户点击重试"的手动动作（不计入自动响应时间）。这一条必须在验收口径会上讲明。

### 2.1.5 自动可视化：业界通用的图表推荐规则

业界没有"唯一标准"，但有一个被广泛引用的成熟框架：**Financial Times Visual Vocabulary**。它的组织方式不是"按图表类型分类"，而是**先按"分析意图"分类，再在每类下给候选图表**——这正是图表推荐算法该有的结构：

| 分析意图（purpose） | 何时用 | 推荐图表（FT 原文列举） | 关键规则（原文） |
|---|---|---|---|
| **Deviation** 偏离 | 强调相对某个基准的正负偏离 | Diverging bar / Diverging stacked bar / Spine chart / Surplus-deficit filled line | — |
| **Correlation** 相关 | 展示两个及以上变量的关系 | Scatterplot / Line+Column / Connected scatterplot / Bubble / XY heatmap | 读者会默认因果，需明示 |
| **Ranking** 排名 | 有序列表中位置比绝对值更重要 | Ordered bar / Ordered column / Dot strip plot / Slope / Lollipop | 条形图**排序后**更容易读排名 |
| **Distribution** 分布 | 展示取值分布与频次 | Histogram / Boxplot / Violin / Population pyramid / Cumulative curve | 直方图柱间隙要小以突出形状 |
| **Change over Time** 时间变化 | 强调趋势变化 | Line / Column / Area / Calendar heatmap / Fan chart | 单系列优先用 Column |
| **Part-to-whole** 构成 | 单一实体拆成组成部分 | Stacked column / Pie / Donut / Treemap / Waterfall | **饼图难以精确比较扇形大小**；组件多时用堆叠条 |
| **Magnitude** 量级 | 只比大小 | Column / Bar / Paired bar / Proportional symbol | **Column 必须从 0 起**；类别名长时用 Bar |
| **Spatial** 空间 | 位置/地理pattern 最重要 | Choropleth / Proportional symbol / Flow map | choropleth 应用**比率**而非总量 |
| **Flow** 流向 | 展示量在状态/地点间的流动 | Sankey / Waterfall / Chord / Network | — |

来源：[Financial Times Visual Vocabulary README](https://github.com/Financial-Times/chart-doctor/blob/main/visual-vocabulary/README.md)

**落到 NL2SQL 的推荐规则（可直接实现为规则引擎）**：

| 结果集形态 | 推荐图表 | 触发条件 |
|---|---|---|
| 1 个时间列 + 1 个度量 | **折线图** | 时间列基数 ≥ 3 且有序 |
| 1 个类别列 + 1 个度量，类别数 ≤ 12 | **条形图（按值排序）** | 类别名较长时用横向 bar |
| 1 个类别列 + 1 个度量，类别数 > 12 | **条形图 Top-N + 其他** | 强制 Top 10–15 |
| 2 个类别列 + 1 个度量 | **分组柱状图 / 热力图** | 类别组合数 ≤ 60 用热力图 |
| 1 个类别列 + 1 个度量且构成有意义（≤6 项） | **饼图/环形图** | 仅在"客户明确要占比"时启用（FT 明确提示饼图难以精读） |
| 2 个度量列 | **散点图** | 用于相关性，不用于趋势 |
| 单行单列（KPI） | **数字卡片** | 不硬凑图表 |
| 时间列 + 度量 + 另一度量（率） | **Line + Column 双轴** | 谨慎，需标注轴 |

> **未找到**：中文政企 BI 场景下"图表类型推荐规则"的行业标准文档。FT Visual Vocabulary 是英文媒体/BI 界最接近标准的公开材料，可作引用；不要声称存在"国家/行业标准"。

### 2.1.6 2 秒响应的可行性

**先算账**（以下为按 MLPerf 阈值的算术推演）：一条中等复杂度 SQL 约 **50–80 token**。

| TPOT | 80 token 的纯解码耗时 | 加上 schema 组装(50ms)+校验(30ms)+执行(100–300ms) | 结论 |
|---|---|---|---|
| 15 ms/token（MLPerf 交互档 DeepSeek-R1 级） | 1.20 s | ≈ 1.4–1.6 s | ✅ 可达 |
| 20 ms/token | 1.60 s | ≈ 1.8–2.0 s | ⚠️ 贴线 |
| 30 ms/token（交互档 Llama3.1-8B 级） | 2.40 s | ≈ 2.7–2.9 s | ❌ 超 |
| 40 ms/token | 3.20 s | ≈ 3.5–3.8 s | ❌ 严重超 |
| **触发 1 次自纠错（再来一遍）** | **×2** | **3–6 s** | ❌ 必然超 |

来源（TPOT 阈值）：[MLPerf Inference Rules](https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc)

**结论与对策（按性价比排序）**：

| 手段 | 收益 | 代价 |
|---|---|---|
| **语义层 + 指标模板**（把"生成 SQL"变成"填参数"） | SQL 从 80 token 降到 20–30 token，且准确率提升 | 前期建模成本（但对准确率同样有正收益，一石二鸟） |
| **schema linking 只注入相关表** | 缩短 prompt → 降低 TTFT | 需要检索组件 |
| **缓存**（问题 embedding 近邻命中 → 直接复用 SQL） | 高频指标类问题几乎 0 延迟 | 只对重复问有效 |
| **流式输出**：先吐 SQL 再吐结果 | 用户感知"响应"= 首字，而非 TTLT | 需前端配合 |
| **预编译/物化视图** | 省掉 SQL 执行时间（100–300ms） | 需数据侧配合 |
| **模型选型：小参数 + 高吞吐推理** | TPOT 决定上限 | 需在客户环境实测 |
| **重试改为手动/异步** | 避免 2s 被击穿 | 体验折衷 |

**建议对客口径**：**"首次返回（含 SQL 展示）≤2s（p95）；最终带结果 ≤4s（p95）；若触发自纠错，另计一次。"**

---

## 2.2 主流工具对比表

| 产品 | 定位 | 关键能力（原文核对） | 许可 | 适用判断 |
|---|---|---|---|---|
| **Vanna 2.0** | 自然语言→SQL→答案 的 Agent + 前端组件 | Agent 化架构；流式返回**表格/图表（Plotly）/自然语言总结**；`<vanna-chat>` Web Component；**row-level security、audit logs、rate limiting**；lifecycle hooks；**Context Enrichers（可加 RAG/记忆/文档）**；任意 LLM、任意 DB | **MIT** | **demo2 最省事的起点**：MIT 许可宽松、前后端齐全、安全原语现成 |
| **WrenAI** | 开源 GenBI 引擎（语义层） | **MDL 语义层**（models/columns/relationships/views/cubes/metrics）；Git 化、可 review；**dry-plan 校验、row limits、structured errors**；value profiling；22+ 数据源（Apache DataFusion 引擎）；本地 LanceDB 记忆 + hybrid retrieval；可生成并部署 Dashboard | 核心 **Apache 2.0** | **要讲"语义层"就用它**：这是把 85% 讲圆的最直接工具 |
| **DB-GPT** | Agentic AI 数据分析助手 | 自主写 SQL 与 Python；**沙箱化执行**；AWEL 工作流；Skills 机制；图表/看板/HTML 报告；支持 Text2SQL 微调（DB-GPT-Hub，含 Qwen/LLaMA/GLM 等） | **MIT** | 需要"代码 + SQL 混合分析"或要微调时选它；纯问数偏重 |
| **Chat2DB** | AI 数据库客户端/工作台 | 40+ 数据库；SQL 工作区；AI 助手（自带模型）生成/解释/优化 SQL；看板与图表；MCP CLI | **源码可见许可（Apache 2.0 + 附加条件，5.3.0 起）** | 适合做"人机协作"演示；许可有附加条件，商用需审 |
| **dbt Semantic Layer** | 指标/语义层（商业+开源抽象） | semantic model = 实体 + 维度 + 指标；MetricFlow 生成查询；v1.12 起支持 Apache Ossie 文档 | 见 dbt 许可 | 客户已有 dbt/数仓时优先；demo 里可只借鉴抽象 |

> ⚠️ 许可提示：RAGFlow / Dify / MinerU / Chat2DB 均为 "Apache 2.0 基础上加附加条件" 或 "source-available"，**交付客户前必须逐份读 LICENSE 原文**，不能默认等同 Apache 2.0。

---

## 2.3 评测口径与真实基线

### 2.3.1 Exact Match vs Execution Accuracy：最常见的三个误读

| 指标 | 定义 | 特点 |
|---|---|---|
| **Exact Match（EM / Exact Set Match）** | 把预测 SQL 与 gold SQL 按子句（SELECT/WHERE/GROUP BY/ORDER BY…）分解后做**集合比较**；或整体字符串完全匹配 | 极严：`WHERE a>1 ORDER BY b` 与 `WHERE a>1` 语义可能等价但 EM 判错；对列顺序、别名、`DISTINCT` 冗余敏感 |
| **Execution Accuracy（EX）** | 分别在真实库上执行预测与 gold，**比对结果集是否等价** | 更贴近用户感知；但会被"巧合正确"（结果集碰巧一样）抬高分数 |
| **Test Suite Accuracy** | Spider 官方自 2020-11 采用的指标：用多个小测试库执行，检验 SQL 在所有库上等价 | 比单库 EX 更严格，抵抗巧合 |

**误读一：把 EM 当"准确率"对外承诺。** Spider 1.0 榜单上同一模型 DIN-SQL+GPT-4，Test **EX = 85.3**，Test **Exact Set Match = 60.0**——差 25 个百分点。客户说"解析准确 85%"时，必须问："你说的是 EX 还是 EM？" 若客户心里是"生成的 SQL 和标准答案一致"，那对标的是 EM（60 量级），85% 不现实；若客户心里是"查出来的数对"，对标的才是 EX。[Spider 1.0 双榜](https://yale-lily.github.io/spider)

**误读二：忽略 "with values" 与否。** Spider 的 Exact Set Match 榜是"**without values**"（不预测值），Execution 榜是"**with values**"（要求模型能正确复制/检索条件值）。两者难度不同，混用会得出荒谬结论。

**误读三：拿 Spider 2.0 榜单的 96.70% 说"现在 NL2SQL 已经解决了"。** 必须同时看：① 该榜单位于 agent 化 + 可能有特殊设置（带 `-*` 标记的使用了 ground-truth tables 且不计入排名）；② 同一页面 Spider-Agent + 同款模型只有 25.78%；③ 论文口径下 o1-preview 17.1%。**榜单头部数字反映的是"工程编排 + 可能的信息优势"，不是"模型 SQL 能力"。**[Spider 2.0 榜单](https://spider2-sql.github.io/)

### 2.3.2 Execution Accuracy 的结果集比对规则（可直接实现）

业界通行做法（Spider / BIRD 系）：

1. **列顺序**：比对时忽略列顺序（按列名/位置排序后比）或在 demo 里约定"必须按 gold 的列序"。
2. **行顺序**：**若 SQL 无 `ORDER BY`，则忽略行顺序**；若 gold 有 `ORDER BY`，则必须顺序一致。
3. **数值容差**：浮点比较用相对/绝对容差（如 `abs(a-b) <= 1e-6 * max(1,|b|)`）；金额类统一精度后再比。
4. **NULL 处理**：`NULL == NULL` 视为相等（不同于 SQL 三值逻辑，评测里要显式处理）。
5. **重复行**：`DISTINCT` 语义敏感——结果集作为多重集（multiset）比较，或按 gold 是否含 DISTINCT 决定去重。
6. **空结果**：预测空、gold 空 → 判对；预测空、gold 非空 → 判错（不能算"部分正确"）。
7. **列名/别名**：一般不比对别名，只比对值（除非题面要求"返回名为 x 的列"）。
8. **多候选与"巧合正确"**：为抑制巧合，BIRD 引入 **Soft-F1** 与 **R-VES** 等指标；Spider 用 Test Suite。demo 里可加"**同一问题必须同时在 2 个不同数据切片上执行一致**"的抽样校验。[BIRD 官方站 News（Mini-Dev / Soft-F1 / R-VES）](https://bird-bench.github.io/)

### 2.3.3 "解析准确率"到底怎么定义才站得住

**先说结论：业界没有一个叫"解析准确率"的指标。** 这是个中文圈自造词。必须把它翻译成业界口径之一，否则无法验收：

| 候选定义 | 计算 | 适用场景 | 风险 |
|---|---|---|---|
| A. **SQL 逻辑等价率（EM / Test Suite）** | 预测 SQL 与 gold 语义等价 | 有时刻标准答案、要考核"生成质量" | 过严，会把正确的等价写法判错 |
| B. **执行结果一致率（EX）** | 结果集等价 | **最贴近用户感知**，demo 首选 | 巧合正确；需固定结果集比对规则（§2.3.2） |
| C. **端到端答对数率** | 用户看到的结果/答案是否正确（人工判） | 验收签字 | 贵，需 200+ 样本 |
| D. **分环节正确率** | schema linking 正确率 / join 路径正确率 / 聚合正确率 / 过滤条件正确率 分开报 | 定位问题 | 需结构化标注 |

**建议**：对外承诺用 **B（EX）**，内部诊断用 **D**，验收时抽 20% 做 **C** 复核。同时必须声明测试集来源与规模（见 §2.3.4）。

### 2.3.4 真实基线：什么样的数字才算"好"

| 参照系 | 数字 | 对 demo 的含义 |
|---|---|---|
| Spider 1.0 英文 EX（Test） | 86.6–91.2 | 英文单轮、跨域、学术设定的天花板 |
| Spider 1.0 英文 EM（Test） | 74.0–81.5 | 同任务严格口径下低 7–10 点 |
| **CSpider 中文 EM（Test）** | **62.1** | **中文同任务比英文低约 20 点** |
| BIRD 英文 EX（Test） | 人类 92.96；模型榜首 82.95 | 脏数据 + 外部知识使难度显著上升 |
| **CHASE 中文多轮 EM** | **整体 40% / 序列级 16%** | **多轮中文 NL2SQL 的真实上限** |
| Spider 2.0 企业级 | 论文 10–17%；工程 agent 25–96%（波动极大） | 真实企业库上，单纯"模型能力"远不够 |

**所以 demo2 的合理承诺**：
- **单轮 + 封闭域（3 表以内、已建语义层）+ EX 口径 → 85% 是可达的**（对标 BIRD 模型榜首 82.95 与 Spider EX 86.6，加上封闭域红利）。
- **多轮追问 → 不要把 85% 写进合同**（CHASE 天花板 40%）。
- **跨库关联超 3 表、或需外部业务知识 → 明确排除在测试集外**。

### 2.3.5 延迟基线

见 §2.1.6。核心可引用事实：**MLPerf Interactive 档把"交互式 LLM 应用"的 TTFT 定在 450–500ms、TPOT 定在 30–40ms/token**。这是目前唯一权威的"交互式"定义。2s 端到端对齐的其实是"**很激进的交互式目标**"——需要 TPOT ≤ 15–20ms/token 才能容纳一条 80 token 的 SQL 加校验执行。

---

## 2.4 我们 demo 的最小可行方案（含技术选型）

### 2.4.1 选型：Vanna（外壳）+ 自建最小语义层 + 规则化图表推荐

| 层 | 选型 | 理由 |
|---|---|---|
| 前端 | **Vanna 2.0 的 `<vanna-chat>`** | MIT；开箱流式表格+图表+总结；省 1–2 天 |
| Agent | Vanna Agent 或自研轻量 StateGraph | 需要 ≤1 次重试的确定性控制 → 自研更可控 |
| 语义层 | **自建最小语义层**（借鉴 WrenAI MDL / dbt semantic model 抽象） | 6–10 个指标 + 3 张表 + 枚举映射 + 认证 join 路径。这是 85% 的关键，不能省 |
| Few-shot | 历史"问-SQL 对"向量检索（bge-m3 嵌入） | 20–50 条高质量示例即见效 |
| 校验 | AST 白名单 + `EXPLAIN` 干跑 + 强制 LIMIT | 安全边界（§2.1.4） |
| 图表 | **规则引擎**（按 §2.1.5 的"结果集形态 → 图表类型"表）+ ECharts/Plotly | 不引入 LLM 决策，避免不稳定 |
| 数据集 | 从 BIRD Mini-Dev（500 条，SQLite/MySQL/PG 三方言）改写本地化中文题 | 见第三部分 |

### 2.4.2 评测方案（demo2 版）

```
测试集：150 条（单轮 120 + 多轮追问 30），全部限定 ≤3 表关联
├── 90 条：语义层已覆盖的指标类问题（应全对）
├── 30 条：需要 join 的非指标问题
└── 30 条：多轮追问（仅测"能否沿用上一轮上下文"，不承诺 85%）

指标：
├── EX（结果集一致率）        ← 对外承诺用这个
├── 分环节正确率（schema/join/聚合/过滤）  ← 内部诊断
├── 拦截率 / 误拦截率          ← 安全边界有效性的证明
└── 延迟：TTFT / SQL 生成完成 / 结果返回，各 p50/p95
```

**给客户演示时最有说服力的一页**：不只展示"答对了几个"，而是展示**"被安全边界拦下了几个、拦得对不对"**——这对运营商客户比准确率更能建立信任。

### 2.4.3 建议对客改写的指标表述

| 原指标 | 建议改写 |
|---|---|
| 解析准确 ≥85% | **执行结果一致率（EX）≥85%**，测试集 150 条、单轮、≤3 表、已建语义层；同时报"SQL 逻辑等价率（EM）"作参考（预期 60–70%） |
| 响应 ≤2s | **首次返回（含 SQL）p95 ≤2s；结果完成 p95 ≤4s；含 1 次自纠错时另计** |

---

# 第三部分 可下载的公开数据集清单（供建 golden set）

## 3.1 NL2SQL 数据集

| 名称 | 规模 | 语言 | 许可 | 下载地址 |
|---|---|---|---|---|
| **Spider 1.0** | 10,181 问 / 5,693 SQL / 200 DB / 138 领域 | 英文 | **CC BY-SA 4.0** | [官方站](https://yale-lily.github.io/spider)（Google Drive 直链在页面内）；[代码仓库](https://github.com/taoyds/spider) |
| **CSpider** | 10,181 问（Spider 全量中译）/ 200 DB | **中文**（表列名英文） | **CC BY-SA 4.0** | [官方站](https://taolusi.github.io/CSpider-explorer/)；[代码](https://github.com/taolusi/chisp) |
| **BIRD** | 12,751 问-SQL 对 / 95 DB / 33.4 GB / 37 领域 | 英文 | **CC BY-SA 4.0**（官方 News 2024-04-27 声明） | [官方站](https://bird-bench.github.io/)（Dev set 直链在页面）；[论文](https://arxiv.org/pdf/2305.03111.pdf) |
| **BIRD Mini-Dev** | 500 条，覆盖全部 BIRD 关键字 | 英文 | 同上 | [mini_dev 仓库](https://github.com/bird-bench/mini_dev)（含 Soft-F1 / R-VES 实现，SQLite/MySQL/PG 三方言） |
| **Spider 2.0** | 632 题（Snow 547 / DBT 68 / Lite 547） | 英文 | **未核实**（务必查看仓库 LICENSE） | [官方站](https://spider2-sql.github.io/)；[代码](https://github.com/xlang-ai/Spider2) |
| **DuSQL** | 200 DB / 813 表 / 23,797 问-SQL 对 | **中文** | **未找到明确许可声明** | 论文：[ACL Anthology](https://aclanthology.org/2020.emnlp-main.562/)；**未找到稳定数据直链**，需按论文/官方仓库指引获取 |
| **CHASE** | 5,459 序列 / 17,940 问+SQL / 280 DB | **中文跨库多轮** | **未核实** | 论文：[ACL Anthology](https://aclanthology.org/2021.acl-long.180/)；原 GitHub 仓库 `xjtu-intsoft/chase` 本次访问 404，**数据获取渠道未核实** |
| **BIRD-CRITIC-SQLite** | 500 个真实 SQLite 用户问题（SQL 调试任务） | 英文 | 见 HF 数据集卡 | [HuggingFace](https://huggingface.co/datasets/birdsql/bird-critic-1.0-sqlite) |

## 3.2 RAG 评测数据集

| 名称 | 规模 | 语言 | 许可 | 下载地址 |
|---|---|---|---|---|
| **WikiEval** | 50 条（RAGAS 论文验证集，含 3 维人类判断） | 英文 | **未核实**（见 HF 数据集卡） | [HuggingFace](https://huggingface.co/datasets/explodinggradients/WikiEval) |
| **RGB** | 4 个测试子集（noise robustness / negative rejection / information integration / counterfactual robustness） | **中英双语** | 见论文与仓库 | [论文](https://arxiv.org/abs/2309.01431)；[代码](https://github.com/chen700564/RGB) |
| **FRAMES** | 824 条多跳问答（MLPerf E2E-RAG 采用） | 英文 | **未核实** | MLPerf 规则中引用：[inference_rules.adoc](https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc)（数据集托管地址与许可需另行确认） |

## 3.3 中文文档解析基准

| 名称 | 规模 | 语言 | 许可 | 下载地址 |
|---|---|---|---|---|
| **OmniDocBench** | 1,651 个 PDF 页面（v1.6 又新增 296 页），10 类文档 / 5 类版式 / 5 语言 | **中英混** | ⚠️ **仅限研究，禁止商用**（原文：for research purposes only and not for commercial use） | [HuggingFace](https://huggingface.co/datasets/opendatalab/OmniDocBench)；[OpenDataLab](https://opendatalab.com/OpenDataLab/OmniDocBench)；[代码](https://github.com/opendatalab/OmniDocBench) |

## 3.4 使用许可的注意事项（必读）

1. **CC BY-SA 4.0 有传染性**：Spider / CSpider / BIRD 都是 ShareAlike。若把测试题**改写**进交付物或对外材料，可能触发"衍生作品需同许可"的讨论。**建议**：只把数据集用于**内部**评测；对外只报指标与自建题集，不随交付物分发原始数据。
2. **OmniDocBench 明确禁止商用**：不能进客户交付包，也不能用于商业演示的宣传材料（可用指标数字并注明来源）。
3. **BIRD 的许可变更历史**：官方在 2024-04-27 把许可改为 CC BY-SA 4.0，并声明不对使用后果负责。引用时请以当日页面为准。
4. **"未核实"项必须在立项前核实**：本表中标记"未核实/未找到"的（Spider 2.0、CHASE、DuSQL、WikiEval、FRAMES），**在写进方案书或合同前必须拿到许可原文截图**。
5. **自建 golden set 的版权**：政企政策文件本身可能受著作权保护，内部评测属合理使用范畴；但**不要把这些文档原文放进对外可访问的 demo**，用脱敏/自撰的等价文档替代。

---

# 附录 A：给客户的"指标改写"一页纸

| # | 客户原指标 | 建议正式口径 | 测试集 | 预期可达 | 依据 |
|---|---|---|---|---|---|
| 1 | RAG 召回 ≥90% | Chunk-ID Recall@5 ≥ 90% | 200 条带 gold chunk id | ✅ 可达 | §1.3.2 |
| 2 | RAG 准确 ≥85% | 端到端答案正确率 ≥85%（人工 2 人判定） | 200 条（60/20/10/10 分层） | ⚠️ 封闭域可达，需明确"不含多跳/跨文档复杂推理" | §1.3.5 |
| 3 | 幻觉 ≤10% | Faithfulness ≥0.90 **且** 不可回答集编造率 ≤10% | 200 条 + 20 条不可回答 | ✅ 可达（faithfulness 是可靠性最高的指标） | §1.3.4 |
| 4 | 单轮 ≤3s | TTFT p95 ≤1.0s + 全文流式 p95 ≤5s；或限定"答案 ≤50 字"时 TTLT ≤3s | 压测 ≥200 次 | ⚠️ 原口径不可达，需改 | §1.1.6 |
| 5 | NL2SQL 准确 ≥85% | EX（执行结果一致率）≥85% | 150 条（单轮、≤3 表、有语义层） | ⚠️ 需限定域；多轮不承诺 | §2.3.4 |
| 6 | NL2SQL 响应 ≤2s | 首次返回（含 SQL）p95 ≤2s；结果完成 p95 ≤4s | 压测 ≥200 次 | ⚠️ 零重试路径可达 | §2.1.6 |

# 附录 B：本次调研未找到 / 未核实的点（诚实清单）

1. **Docling / Unstructured 在 OmniDocBench v1.6 总榜的公开分数** —— 未找到（README 更新日志称已评测，v1.6_full 榜单未列该行）。
2. **RAG 端到端"检索+重排+生成"三段 p95 的中文公开延迟基准** —— 未找到。MLPerf E2E-RAG 只规定 Offline 场景、无延迟约束。
3. **bge-reranker 系列的官方延迟基准** —— 未取得，需在客户环境自测。
4. **"解析准确率"的业界统一定义** —— 不存在。业界只有 EM / EX / Test Suite / Soft-F1 / R-VES。
5. **Spider 2.0 数据许可、CHASE 数据许可与获取渠道、DuSQL 数据直链、WikiEval 与 FRAMES 许可** —— 未核实，立项前必须补。
6. **中文政企 BI 的"图表类型推荐"行业标准** —— 不存在。最接近的公开材料是 FT Visual Vocabulary。
7. **FastGPT、docling、dify 的许可附加条款细节** —— 未逐条核对，交付前须读 LICENSE 原文。
