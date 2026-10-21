# ENVIRONMENT · 环境基线与能力矩阵

> **本文件是证据，不是说明书。** 每个数字都能由 `scripts/probe_models.py` 重跑复现，原始记录在 `evidence/probe-*.json`。
> **锁定项（GStack 版本冻结纪律）：**
> - GStack：`1.91.121.0`（`~/.codex/skills/gstack`，全项目统一，勿混用 1.58.3.0 / 1.87.3.0）
> - Python：3.12.10 ｜ Node：v22.20.0 ｜ OS：Windows（本机直跑，无容器）
> - 生成模型：`opencode-go/gpt-6-luna`（`reasoning_effort=none`；0.2 轮实测环境为内网 magpie，默认档 A 为 `Qwen/Qwen2.5-72B-Instruct`）
> - 嵌入：`Qwen/Qwen3-Embedding-4B`（2560 维，硅基流动）
> - 重排：`Qwen/Qwen3-Reranker-4B`（硅基流动）
> - 历史环境：0.1 轮曾用 `BAAI/bge-m3`（1024 维）/ `bge-reranker-v2-m3`，见 §7 变更表

## 1. 能力来源与实测结论

| 能力 | 服务 | 端点 | 状态 | 实测 |
|---|---|---|---|---|
| 生成（LLM） | magpie（本地网关） | `http://127.0.0.1:3425/v1/chat/completions` | ✅ 可用 | 见下表 |
| 模型清单 | magpie | `/v1/models` | ✅ 15 个模型 | 5 个支持 `reasoning_effort=none` |
| 结构化输出 | magpie | `/v1/systemone` | ❌ **不可用** | `magpie has no Jev provider`（需 Jev provider，本机未配置） |
| 嵌入 | 硅基流动（公网） | `/v1/embeddings` | ✅ 可用 | 10 chunk 0.236s，dim=1024（0.1 轮 bge-m3 实测；0.2 轮起为 Qwen3-Embedding-4B / 2560 维，见 §7） |
| 重排 | 硅基流动（公网） | `/v1/rerank` | ✅ 可用 | 10 doc 0.148s，top1 分数 0.950 |
| magpie 自带嵌入 | magpie | `/v1/embeddings` | ❌ **无模型** | 报错 `knows no model`，仅列聊天模型 |
| 本地大模型（Ollama） | 本机 | `:11434` | ❌ 未安装/未运行 | — |
| GPU | 本机 | `nvidia-smi` | ❌ 不可用 | 无 NVIDIA 驱动/显卡 |

**结论：本机没有"完全离线"的 AI 能力。生成走本地网关但背后是云端 provider，嵌入与重排必须出公网。** 这条必须写进演示材料的"边界声明"，不能对客户说"全私有化"。

## 2. 生成模型实测（n=5，固定短上下文问答）

| 标签 | 模型 | effort | p50 | max | 思维链 token | 备注 |
|---|---|---|---|---|---|---|
| main | `opencode-go/gpt-6-luna` | `none` | **1.48s** | 1.83s | 0 | 当前默认；稳定、最快、答案偏精简 |
| alt | `opencode-go/glm-5.3` | `low` | 1.48s | 3.22s | 0 | 答案更完整；**但不同时段曾出现 p50 17.95s 与整组超时** |
| reasoner | `opencode-go/deepseek-v4.1-flash` | `low` | 2.74s | 4.34s | 455 | 会主动指出"材料未明确恰好 500 万元"，推理质量最好但慢一倍 |

三条硬结论：

1. **`reasoning_effort` 必须显式传。** 不传时模型默认高强度思考：一次只问 3 个字的回复也可能消耗 391 个思维链 token，并把 `max_tokens` 吃光导致答案被截断（实测 `max_tokens=400` 时返回空答案）。
2. **只有 5 个模型支持 `none`**（`opencode-go/gpt-6-luna`、`rocco/gpt-6-luna`、`rocco/gpt-6-sol`、`rocco/copilot-gpt-6-luna`、`rocco/copilot-gpt-6-sol`）。其余模型（deepseek / glm / kimi / hy3 / step）最低只能到 `low`，无法关掉思维链。
3. **延迟波动极大，单次测量无效。** 同一 glm-5.3 在 09:01 的组里 p50 为 17.95s，09:07 的组里为 1.48s。**所以验收口径必须是 p50 + p95 + 成功率，且样本 ≥50 次**（本文 n=5 仅用于选型）。

## 3. RAG 链路延迟预算（实测拼装）

| 环节 | 实测/估计 | 说明 |
|---|---|---|
| 查询嵌入 | ~0.24s | 10 chunk 批量实测；单条更快 |
| 混合检索（本地） | <0.05s | 千级 chunk，numpy + BM25，无网络 |
| 重排 top-20 | ~0.15–0.30s | 10 doc 实测 0.148s，20 doc 约翻倍 |
| 生成（短上下文） | 1.48s p50 / 1.83s max | 约 150 token prompt、30 字答案 |
| 生成（真实 RAG） | 2–4s（估） | 约 5 chunk × 400 token 上下文、200–400 字答案，**待实测** |
| **端到端** | **~2.0–4.5s（估）** | 结论：**"单轮 ≤3s" 只在短答案 + 小上下文下成立**；必须改成 TTFT + 流式口径 |

> 这个预算正好验证了 [轴二文档](../../docs/01-FDE场景与三项目业界借鉴.md) 第 0 节的判断：3 秒不是不可能，但**不能承诺"完整政策解读 3 秒返回"**。

## 4. 已知风险与降级方案

| 风险 | 影响 | 降级方案 |
|---|---|---|
| 嵌入/重排依赖公网 | 演示现场断网即失效；不符合"数据不出域" | ① 演示用脱敏数据并提前声明；② 备选：CPU 版 `bge-small-zh-v1.5`（约 100MB，ONNX）做本地嵌入，质量下降可接受 |
| magpie 背后是云端 provider | 不能宣称私有化 | 明确写"生成走本地网关、模型能力来自云端"；私有化属"后续适配项" |
| 模型延迟抖动（同一模型 p50 从 1.5s 到 18s） | 3 秒指标不可预期 | 多采样 + p95 口径 + 超时降级（切 `main` 模型）；前端流式呈现 |
| 无 GPU | 无法本地跑大模型做对比 | 不做"本地 vs 云端"效果对比，改为"不同模型质量对比" |
| glm 偶发超时 90s+ | 演示卡死 | 默认不用 glm；如需用，加 8s 超时熔断并回退 `gpt-6-luna` |

## 5. 复现方式

```powershell
cd cases\01-rag-qa
copy .env.example .env      # 填入 SILICONFLOW_KEY
python scripts\probe_models.py
# 产出 evidence\probe-<UTC 时间戳>.json，并在控制台打印 p50/max/成功率和答案样例
```

**每次更换模型、更换供应商、或验收前，必须重跑一次并把新证据文件纳入报告。** 旧证据不删除，保留历史以便解释"为什么当时选了这个模型"。

## 6. 变更记录

| 日期 | 变更 | 证据 |
|---|---|---|
| 2026-10-20 | 初版：三条链路打通；确定 main/alt/reasoner 三模型与 p50 基线；记录离线能力缺失与延迟抖动 | `evidence/probe-20261020-090153.json`（早期 n=3，含 glm 18s 异常）、`probe-20261020-090756.json`（n=5，当前基线） |

---

## 7. 0.2 轮变更：统一到 magpie 网关（2026-10-20）

| 能力 | 0.1 轮 | **0.2 轮（当前）** |
|---|---|---|
| 生成 | magpie `opencode-go/gpt-6-luna`（none） | 不变 |
| 嵌入 | 硅基流动直连 `BAAI/bge-m3`（1024 维） | **magpie `siliconflow/Qwen/Qwen3-Embedding-4B`（2560 维）** |
| 重排 | 硅基流动直连 `BAAI/bge-reranker-v2-m3` | **magpie `siliconflow/Qwen/Qwen3-Reranker-4B`** |
| 密钥 | magpie + 硅基流动两套 | **仅 magpie 一套**（硅基流动保留为备用通道） |

**实测（`evidence/bench-embeddings-*.json`、`bench-providers-*.json`）：**

- 检索总耗时：切前 564ms → 切后 **571ms**（无回归也无改善）。
- rerank：Qwen3-4B 0.12s、Qwen3-8B 0.32s、bge-reranker-v2-m3 0.15s。
- 嵌入 A/B（20 条人工无偏问题，doc 召回@5）：Qwen3-4B / Qwen3-8B / bge-m3 **均 100%，无区分度**——语料只有 12 份文档，文档级召回太容易。**因此本轮无法据数据选型，维持 4B。**
- 生成 provider（4 题，p50 端到端，含检索与网关竞争）：luna 4636ms < sol 6008ms < deepseek 7023ms < glm 7633ms < kimi 8688ms。**luna 仍最快。**

**边界不变：** magpie 是网关，上游仍是云端 provider。**"数据不出域"的结论没有改变**，只是少了一个外部入口与一套密钥。

**索引变更：** 因嵌入模型变化，`data/index/` 已重建（315 chunk / 2560 维）；更换嵌入模型必须重建索引，`.npy` 维度与 `meta.embed_dim` 不一致时 `Index.load` 会拒绝启动（F10 修复项）。


## 8. 2026-10-21 变更：虚构主体改名与重跑

- 语料主体 `浙东省通信服务有限公司` → **`明州数智服务有限公司`**（12 篇制度 + `EMBEDDED_CASES.md`）。
- 索引重建：`python -m src.ingest` → 315 chunk / 2560 维；`corpus_sha256` `78fedbd8…` → **`1f0487bc…`**。
- 评测重跑（2026-10-21）：facts 口径正确率 **68.00%**（10-20 基线 50.65%）、claim **73.31%**、judge 失败 **3.85%**、TTFT p50/p95 **2091 / 3194.8ms**（facts 子集 80 题口径；全量 208 题口径为 2006.0 / 3334.0ms；基线 4041ms）。差异归因见 `qa-report.md` §七（模型/判官漂移，非改名功效）。
- 冻结快照已更新；旧快照保留为 `evidence/frozen-manifest-rag-*.pre-rename.bak.json`。