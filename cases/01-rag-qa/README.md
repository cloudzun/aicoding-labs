# 政企 RAG 问答 · demo（案例 ①）

> 多份制度文档的问答：**答得出、指得准、答不了敢拒**。三个教学案例的第一棒。

## 现在能做什么

| 能力 | 说明 |
|---|---|
| 条款级切分 | 按"第X条"切分（315 chunk / 12 份合成制度） |
| 混合检索 | 密集向量（Qwen3-Embedding-4B，2560 维）+ BM25 → RRF(k=60) → 重排 → top-5 |
| 双闸拒答 | rerank 阈值 0.30 + prompt 规则；无答案问题约 1 秒内拒答且不调模型 |
| 时效/冲突探针 | 确定性正则补入"废止/失效/试行期"条款，解决"旧条款已废止"类问题 |
| 引用校验 | 服务端校验 `[cNN]` 是否存在、是否指向实际 retrieved chunk |
| 流式输出 | SSE：meta → delta → done（含 trace_id、耗时、claim 支撑率） |
| trace | 每题落盘：改写后 query、检索候选、引用、耗时、语义层版本 |

## 关键数字（定稿 v0.2.0.0）

| 项 | 值 |
|---|---|
| 语料 | 12 份合成制度 / **315 chunk** / 2560 维 |
| 评测集 | 主集 **208**（120 单跳 / 48 多跳 / 8 冲突 / 32 无关）+ 拒答 50；分层子集 80 |
| 正确率（facts 口径） | **68.00%**（2026-10-21 重跑；10-20 基线 50.65%；整条口径 40.00% 本次未重跑） |
| Faithfulness | **79.75%**（10-20 基线，本次未重算；A 段修复前 62.34%） |
| claim 支撑率 | **73.31%**（10-20 基线 78.06%；3-gram 下限指标） |
| judge 失败率 | **3.85%**（10-20 基线 2.53%；超 2% 门禁 → 结论 **INCOMPLETE**） |
| Recall@5 | 100%（**题料同源，不可当能力**）；异源冒烟 91.67% |
| TTFT p95 | **3195ms**（10-20 基线 4041ms；阈值 1000ms，**环境依赖缺口**） |
| 功能 QA | **10/10** |

## 快速开始

```powershell
cd project\01-rag-qa
python -m src.server            # → http://127.0.0.1:4180
python scripts/qa_checks.py     # 需先启服务，10 项检查
python -m eval.run_eval --dataset eval/golden_set.jsonl --no-judge
python -m eval.run_eval_v2 --dataset eval/golden_set_v2.jsonl --human-verdicts eval/human_verdicts.jsonl
```

详见 [docs/11-操作手册.md](docs/11-操作手册.md)、[BUILD.md](BUILD.md)。

## 目录

```
01-rag-qa/
├── data/{corpus,index,traces}    # 语料 / 索引 / 追踪
├── src/                          # core/corpus/vector/rag/generate/citations/server/ingest
├── web/index.html                # 单页：提问 + 引用可点 + 合规横幅
├── eval/                         # golden_set / golden_set_v2 / human_verdicts / run_eval(v1,v2)
├── scripts/                      # probe_models / qa_checks / make_gold_* / bench_*
├── docs/                         # 00 口径 / 01 需求 / 03 会审 / 05 处置 / 06 演示
│                                 # 07 SPEC v0.2 / 08 会审 v0.2 / 09 三阶段 / 10 八环 / 11 手册
└── evidence/                     # 42 份证据（评测、探测、评审原文、界面截图）
```

## 诚实边界

- ❌ 数据不出域（嵌入/生成仍经本地网关，上游为云端模型）
- ❌ 深度验收（正确率 **68.00%**，judge 失败率 **3.85%** 超门禁 → INCOMPLETE）
- ❌ TTFT ≤1s（差约 4 倍，需专用推理端点）
- ⚠️ Recall 100% 是题料同源产物；F05 引用语义校验、F14 生成总 deadline 未修

## 文档

| 文件 | 内容 |
|---|---|
| [docs/00-数据与口径.md](docs/00-数据与口径.md) | 指标可判定句、样本量、陷阱识别 |
| [docs/01-需求.md](docs/01-需求.md) | 用户、故事、不做清单 |
| [docs/03-会审记录.md](docs/03-会审记录.md) / [docs/08-会审-v0.2.md](docs/08-会审-v0.2.md) | 两轮会审 |
| [docs/05-评审处置.md](docs/05-评审处置.md) | codex 26 条逐条处置 |
| [docs/09-三阶段结果.md](docs/09-三阶段结果.md) | A/B/C 攻坚与双口径 |
| [docs/10-八环讲解记录.md](docs/10-八环讲解记录.md) | 课堂讲解（326 行） |
| [docs/11-操作手册.md](docs/11-操作手册.md) | 功能验证手册 |
| [review.md](review.md) | codex 独立评审原文（26 条） |
| [qa-report.md](qa-report.md) | 三轮评测对照 + 失败归因 |
| [retro.md](retro.md) | 复盘 |
| [DECISIONS.md](DECISIONS.md) | 22 条决策（D-01～D-22） |

> 已补 `evidence/README.md`（含补丁脚本 ↔ 评审发现对照表）。
>
> **编号说明：** `docs/` 无 02 与 04——02 的内容并入 `00-数据与口径`，04 未产出（SPEC 直接在根目录）。属历史编号，不是丢文件。
