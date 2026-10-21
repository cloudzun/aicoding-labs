# 实验手册总览（`project/labs/`）

> **定位：** 学生向的**可复现操作手册**。三本手册与教材第五章配套：手册回答"怎么敲"，教材回答"为什么"。
> **上位依据：** `project/HANDOFF-三案例教学化.md`（§2.5 环境、§4.1 端点与 smoke 脚本、§5 手册体例）。
> **状态：** 体例已定稿（`00-手册编写体例.md`）；三本手册待写。

---

## 一、三本手册一览

| 手册 | 对应案例 | 端口 | 时长 | 配套教材 | 状态 |
|---|---|---|---|---|---|
| `L1-RAG问答实验手册.md` | 案例一 政企 RAG 问答（`v0.2.0.0`） | 4180 | 90 min | 单元5.2 | 待写 |
| `L2-NL2SQL实验手册.md` | 案例二 NL2SQL 问数（`v1.0.0.0`） | 4181 | 90 min | 单元5.3 | 待写 |
| `L3-合同审查实验手册.md` | 案例三 合同审查（`v1.2.0.0`） | 4182 | 90 min | 单元5.4 | 待写 |

---

## 二、各手册必须覆盖的实验点

| 手册 | 必做实验点（缺一不合格） | 逐字可核对的"已知答案" |
|---|---|---|
| L1 | 无答案拒答（不调模型，看耗时）；冲突题并列；引用点开原文；改 `MIN_RERANK_SCORE` 观察误拒变化 | 健康 `/api/health` → `index.chunk_count=315`、`embed_dim=2560`；"婚假" → `done.refused=true` 且含"资料不足" |
| L2 | 四道安全闸 12 例对抗；歧义 blocking vs advisory；EX 评测（FAIL 也是结果）；JOIN 桶 68% 归因 | `541252.34` / `57` / `35`；`rejected.gate=write_intent`；安全 12/12 |
| L3 | CT001 零风险 vs CT003 命中；`not_detected` ≠ 合规；注入不改变判定；关闭语义看 coverage | CT001 `summary` 全 0；CT003 含 `R02`（中）与 `R19`（高）；数据断言 10/10 |

---

## 三、接口速查（写手册时直接用）

| 案例 | 端点 | 请求体 | 关键返回 |
|---|---|---|---|
| L1 | `POST /api/chat`（SSE） | `{"question":"...","history":[]}` | 事件 `meta`/`delta`/`done`；`done.refused`、`done.trace_id` |
| L1 | `GET /api/health`、`GET /api/trace/{id}` | — | `index.chunk_count`、`index.embed_dim` |
| L2 | `POST /api/ask` | `{"question":"...","clarify":true}` | `sql`、`columns`、`rows`、`row_count`、`chart`、`clarification`、`rejected` |
| L2 | `GET /api/health` | — | `tables`（6 张） |
| L3 | `POST /api/review` | `{"contract_id":"CT001","with_semantic":true}` | `summary`、`findings`、`coverage`、`review_id` |
| L3 | `GET /api/contracts`、`GET /api/rules`、`POST /api/upload` | — | 30 份合同 / 27 条规则（含 `stance`） |

> 中文请求体的 PowerShell 坑：JSON 存 UTF-8 无 BOM 文件，用 `--data-binary "@q1.json"`，勿直接 `-d` 拼中文。

---

## 四、目录约定

```
project/labs/
├── README.md                 # 本文件
├── 00-手册编写体例.md         # 8 段体例 + 模板 + 正反例 + 自检清单
├── L1-RAG问答实验手册.md
├── L2-NL2SQL实验手册.md
├── L3-合同审查实验手册.md
├── scripts/                  # 三个 5 分钟 smoke 脚本（smoke-rag.ps1 等）
└── assets/                   # 截图与录屏（首页、关键结果、失败示范）
```

---

## 五、写作顺序建议

1. 先写 **L3**（最完整：确定性 21 条满分、语义层有立场故事、数据全离线可生成）。
2. 再写 **L2**（接口最简单，但 EX 概念需要解释）。
3. 最后写 **L1**（SSE 流式接口最复杂，且依赖检索与拒答两套机制）。

每写完一本：按手册从零跑一遍 → 记录"卡住的步骤" → 回改手册 → 再跑一遍。

---

## 六、禁止事项

1. 不写未实跑的期望输出。
2. 不出现真实密钥（统一 `<MAGPIE_KEY>`）。
3. 不把"未达标"写成"达标"：L2 的 EX 是 **83.33%（2026-10-21 重跑；10-20 基线 84.67%，两版都是 FAIL）**，L3 是 PASS 但有未修项。
4. 不重复教材原理；教材不重复手册步骤。
5. 正文不用带圈数字（①–⑩）。
