# QUICKSTART：15 分钟跑起来

> 前置：**Python 3.12**（实测 3.12.10；**3.11+** 理论可用，`numpy==2.4.2` 等依赖要求 3.11+）+ 一个 [硅基流动](https://siliconflow.cn) API key（同一个 key 覆盖对话、嵌入、重排）。
> 全部命令在仓库根目录的 PowerShell 中执行。Windows PowerShell 5.1 **不支持 `&&`**，下面每条命令单行执行。

## 第 1 步：安装（约 3 分钟）

```powershell
.\scripts\setup.ps1
```

它会：建 `.venv` → 安装三个案例的依赖 → 为每个案例生成一份 `.env`（优先用该案例自带的 `cases\<案例>\.env.example`，没有才回退根模板）。生成的 `.env` 里已含该案例**未注释的 `PORT`**（4180 / 4181 / 4182），要换端口直接改这一行。

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

逐项输出 `[OK]` / `[WARN]` / `[FAIL]`：Python、`.env`、key、模型名是否在 `/models` 列表、端口占用、索引与数据。
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
.\scripts\verify.ps1              # 离线断言：语法、两案例数据断言、索引（存在则校验）、密钥扫描
.\scripts\verify.ps1 -WithNetwork # 额外做三案例各一次真实模型调用
```

服务启动后（第 4 步的窗口保持运行），还可以跑 `labs\scripts\` 里三个现成的 5 分钟验收脚本——它们直接打 HTTP 接口，逐步打印 `[PASS]` / `[FAIL]`：

```powershell
.\labs\scripts\smoke-rag.ps1        # 案例一 4180：健康 / 检索命中 / 拒答
.\labs\scripts\smoke-nl2sql.ps1     # 案例二 4181：歧义反问 / 只读闸 / 期望值
.\labs\scripts\smoke-contract.ps1   # 案例三 4182：CT001 零风险 / CT003 命中 / 覆盖度
```

端口不是默认值时加 `-Port`，例如 `.\labs\scripts\smoke-rag.ps1 -Port 5180`。脚本只做断言；但案例二/三的 smoke 会确定性重建 `data/aicoding.db` 与 30 份合同，跑完 `git status` 可能出现生成物改动，属正常（生成物已在 `.gitignore`）。全过退出码 0，末尾打印 `RESULT`。

## 停止与重启（后台运行）

`run.ps1` 是前台进程（Ctrl+C 停止）。如果想**后台跑、随时看状态、一键全停**：

```powershell
.\scripts\demo-control.ps1 status      # 端口 / PID / 内存 / 健康 / 运行时长
.\scripts\demo-control.ps1 start       # 后台启动三个案例（缺数据会先生成）
.\scripts\demo-control.ps1 stop        # 只停本项目服务，不会误杀其他 python
.\scripts\demo-control.ps1 restart     # 演示前推荐：干净重启
.\scripts\demo-control.ps1 restart -Case 1
```

实测：本机三个服务合计占内存约 0.14–0.38 GB，空闲 CPU 接近 0；停掉不影响数据（索引、数据库、合同都在磁盘上，下次 `start` 直接可用）。日志在各案例 `evidence/server-out.txt`（不随仓库分发）。

## 手动方式（不用脚本）

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
cd cases\01-rag-qa
pip install -r requirements.txt
copy .env.example .env           # 用案例自带模板（键名与 PORT 都对得上），再填 key
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
