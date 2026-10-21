# QUICKSTART：三个案例的完整启动步骤

> 全程 PowerShell 示例（macOS/Linux 把 `copy` 换成 `cp`、`.\\.venv\\Scripts\\Activate.ps1` 换成 `source .venv/bin/activate`）。
> **前置：** Python 3.12；一个硅基流动（SiliconFlow）key。

## 0. 公共准备（每个案例各做一次）

```powershell
cd <repo>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

每个案例目录都有一份 `requirements.txt` 与 `.env.example`：

```powershell
cd cases\01-rag-qa
pip install -r requirements.txt
copy ..\..\.env.example .env
notepad .env      # 把 SILICONFLOW_KEY 换成你自己的
```

## 1. 案例一：RAG 制度问答（4180）

```powershell
cd cases\01-rag-qa
python -m src.ingest        # 重建索引（315 chunk / 2560 维；需 key）
python -m src.server        # 打开 http://127.0.0.1:4180
```

自检（可选）：

```powershell
python scripts\qa_checks.py     # 10 项实机检查
python -m eval.run_eval         # 全量 208 条（无 judge，约 15 分钟）
python -m eval.run_eval_v2      # 分层子集 80 条（judge，约 12 分钟）
```

**预期：** 健康徽标 `315 chunk / 12 文档 / 2560 维`；问"员工的婚假有多少天？"应**拒答**；问"500 万以上采购项目"应给引用并指出旧条款已废止。

## 2. 案例二：NL2SQL 政企问数（4181）

```powershell
cd cases\02-nl2sql
python -m scripts.gen_db        # 生成 db（8,584 行）
python -m scripts.verify_db     # 11 项断言
python -m src.server            # 打开 http://127.0.0.1:4181
```

自检（可选）：

```powershell
python -m scripts.test_safety   # 12 条安全闸
python -m eval.run_eval         # 150 题主集（约 20 分钟）
```

**预期：** 问"今年的营收是多少"应先**反问口径**；问"删除所有订单"应被**拒绝**。

## 3. 案例三：合同审查（4182）

```powershell
cd cases\03-contract-review
python -m scripts.gen_contracts   # 30 份 docx（约 3 秒）
python -m scripts.verify_data     # 10 项断言
python -m src.server              # 打开 http://127.0.0.1:4182
```

自检（可选）：

```powershell
python -m scripts.qa_checks
python -m eval.run_eval           # 指标评测
```

**预期：** CT001 零风险；CT003 命中 `R19/高`、`R02/中`（开语义再加 `R20/R25`）；点任一发现项，左侧原文面板跳到对应段落。

## 常见问题

| 现象 | 处理 |
|---|---|
| 嵌入维度不是 2560 | 你换过 `EMBED_MODEL`；必须 `python -m src.ingest` 重建索引，否则 `Index.load` 拒绝启动 |
| 案例一答非所问 / 检索为空 | 索引没建或 key 无效；先跑 `src.ingest` 看是否报 `EmbeddingError` |
| 端口被占用 | 设置 `PORT=4181` 等环境变量，或改 `.env` |
| 中文乱码（PowerShell） | 文件均 UTF-8；`chcp 65001` 后重试 |
| 案例三语义规则时有时无 | 语义判定依赖模型，**允许波动**；确定性 21 条稳定 |

## 指标说明

各案例 `qa-report.md` 里的数字是作者环境的一次性读数：**换模型/换网络后不可复现**。仓库只保证"流程与断言可复现"，不保证"数字相同"。
