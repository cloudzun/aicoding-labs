# BUILD · 运行与构建说明

> 目标：在 **Windows 本机**、**无容器**条件下，从零把 demo 跑起来。
> 依赖：Python **3.12 实测；3.11+ 理论可用**（`numpy==2.4.2` 需 ≥3.11）、一个硅基流动 API key（**默认档 A：公网** `https://api.siliconflow.cn/v1`，覆盖生成 + 嵌入 + 重排）。
> 内网 magpie（`127.0.0.1:3425`）为**可选档 B**：仅当你有该网关时启用，见 `.env.example` 的档 B 注释块；**没有它也能完整跑通**。

## 一、首次启动（4 步）

```powershell
cd cases\01-rag-qa

# 1) 配置（.env 不入库）
copy .env.example .env
#   填入 SILICONFLOW_KEY（默认档 A：公网硅基流动）；内网 magpie 见档 B 注释块

# 2) 依赖（均已在本机安装；如缺失则装）
pip install fastapi uvicorn httpx numpy jieba rank-bm25 pymupdf python-docx

# 3) 建库（约 10 秒；嵌入有缓存，重复建库不重复计费）
python -m src.ingest

# 4) 启动
python -m src.server          # → http://127.0.0.1:4180
```

浏览器打开 `http://127.0.0.1:4180`，右下角健康徽标应显示 `索引就绪：315 chunk / 12 文档 / 2560 维`。

## 二、评测

```powershell
python -m scripts.make_golden_set        # 首次：生成评测集（约 3–5 分钟）
python -m eval.run_eval                  # 全量：召回/正确/忠实/拒答/引用/延迟
python -m eval.run_eval --limit 40 --no-judge   # 冒烟：只测召回/拒答/延迟
python -m eval.run_eval --dataset eval/refusal_set.jsonl --refusal
```

报告输出：`eval/reports/EVAL-REPORT.md` + `eval/reports/eval-<时间>.json`，同一份同时写入 `evidence/`（**未随仓库分发**，本地生成）。

## 三、目录与关键文件

| 路径 | 作用 |
|---|---|
| `src/corpus.py` | 解析 `.md/.txt/.pdf/.docx` → 条款级切分（`chunk_id = doc_id#cNNN`） |
| `src/vector.py` | 嵌入（`Qwen/Qwen3-Embedding-4B`，2560 维）+ BM25 + RRF + 重排（`Qwen/Qwen3-Reranker-4B`）+ **废止探针** |
| `src/rag.py` | 双闸拒答、prompt、引用校验、trace 落盘、SSE 事件流 |
| `src/generate.py` | OpenAI 兼容流式/非流式调用（默认硅基流动，可选 magpie）、超时熔断、独立模型 judge |
| `src/server.py` | FastAPI：`/api/chat`(SSE)、`/api/health`、`/api/trace/{id}` |
| `web/index.html` | 单页前端（无构建）：引用高亮、合规横幅、来源面板 |
| `data/index/` | `chunks.jsonl` / `emb.npy` / `meta.json`（重建即覆盖） |
| `data/traces/` | 每次回答的检索与耗时记录（本地，可清理） |
| `evidence/` | 探测与评测的原始证据（带时间戳；**未随仓库分发**） |

## 四、常见问题

| 现象 | 原因 | 处置 |
|---|---|---|
| 启动提示端口 4180 被占用 | 上次进程未退出 | 关掉占用进程，或改 `.env` 的 `PORT` |
| 健康检查显示 `SILICONFLOW_KEY 未配置` | `.env` 缺 key | 填 key 后重启 |
| 建库报 `嵌入失败（已完成 N/315）` | 网络中断/限流 | 已完成批次已缓存，恢复后重跑即可续跑 |
| 问答返回"资料不足"但明知库里有 | 检索分数低于阈值 0.30 | 看 `data/traces/*.json` 的 `max_score`；可下调 `.env` 阈值或改进问法 |
| 生成很慢/超时 | 模型侧首 token 抖动（实测单次可 >15s） | 默认模型 `Qwen/Qwen2.5-72B-Instruct`（judge 读 `MODEL_REASONER`）；超时 15s 熔断返回部分答案 |
| `.docx` 解析报错 | 未装 python-docx | `pip install python-docx` |
| 扫描件 PDF 无内容 | 未做 OCR（明确不做） | 换文本型 PDF 或先用外部工具 OCR |

## 五、降级与安全边界（演示时必须说明）

1. **嵌入、重排与生成默认都走公网**（硅基流动），断网即无法建库/检索/生成；若启用可选档 B 的内网 magpie，其上游仍是云端。
2. **不能宣称"数据不出域"**：当前仅用虚构语料演示，真实制度需先解决本地嵌入与私有化模型。
3. 页面顶部固定横幅声明上述边界（对应会审 C-01 / OB-05）。
4. trace 仅本地保存，可用 `python scripts/purge_traces.py --days 7` 清理（对应 OB-06）。
