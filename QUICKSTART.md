# QUICKSTART：15 分钟跑起来

> 前置：**Python 3.12** + 一个 [硅基流动](https://siliconflow.cn) API key（同一个 key 覆盖对话、嵌入、重排）。
> 全部命令在仓库根目录的 PowerShell 中执行。

## 第 1 步：安装（约 3 分钟）

```powershell
.\scripts\setup.ps1
```

它会：建 `.venv` → 安装三个案例的依赖 → 为每个案例生成一份 `.env`（从根目录 `.env.example` 复制）。

## 第 2 步：填 key（1 分钟）

打开三个文件，把 `<YOUR_SILICONFLOW_KEY>` 换成你的 key：

```
cases\01-rag-qa\.env
cases\02-nl2sql\.env
cases\03-contract-review\.env
```

> `.env` 已在 `.gitignore` 中，不会被提交。

## 第 3 步：体检（30 秒）

```powershell
.\scripts\doctor.ps1
```

逐项输出 `[OK]` / `[WARN]` / `[FAIL]`：Python、`.env`、key、模型可用性、端口占用、索引与数据。
**有 `[FAIL]` 就按提示修**，全部通过再往下走。

## 第 4 步：启动

```powershell
.\scripts\run.ps1 -Case 1     # RAG 制度问答  → http://127.0.0.1:4180
.\scripts\run.ps1 -Case 2     # NL2SQL 问数   → http://127.0.0.1:4181
.\scripts\run.ps1 -Case 3     # 合同审查      → http://127.0.0.1:4182
```

第一次运行 `-Case 1` 会自动建索引（315 chunk，需要 key，约 1 分钟）；`-Case 2/3` 会自动生成数据库与合同（不需要 key）。

端口被占用时：`.\scripts\run.ps1 -Case 1 -Port 5180`。

## 第 5 步：验收（可选）

```powershell
.\scripts\verify.ps1              # 离线断言：语法、两案例数据断言、索引、密钥扫描
.\scripts\verify.ps1 -WithNetwork # 额外做三案例各一次真实模型调用
```

## 手动方式（不用脚本）

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
cd cases\01-rag-qa
pip install -r requirements.txt
copy ..\..\.env.example .env     # 填 key
python -m src.ingest
python -m src.server
```

## 三个案例各看什么

| 案例 | 演示要点 | 预期 |
|---|---|---|
| 01 RAG | 引用与拒答边界 | 问"500 万以上采购"给引用并指出旧条款废止；问"员工婚假"应**拒答** |
| 02 NL2SQL | 歧义反问与只读闸 | 问"营收"先反问口径；问"删除所有订单"被**拒绝** |
| 03 合同审查 | 双引擎 + 定位到原文 | CT001 零风险；CT003 命中 R19/R02（开语义加 R20/R25）；点行左栏高亮原句 |

## 遇到问题

见 **[FAQ.md](FAQ.md)**。本项目为静态教学标本，不接收 PR。
