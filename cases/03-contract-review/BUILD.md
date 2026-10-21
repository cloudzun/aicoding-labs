# BUILD · 启动与故障处理（合同审查）

## 1. 环境

- Python 3.12，依赖：`python-docx`、`PyYAML`、`fastapi`、`uvicorn`、`httpx`
- 模型网关：magpie `http://127.0.0.1:3425`（仅语义规则需要）

## 2. 四步启动

```powershell
cd project\03-contract-review
python -m scripts.gen_contracts     # 30 份 docx + 810 单元（约 2 秒）
python -m scripts.verify_data       # 10 项断言
python -m src.server                # → http://127.0.0.1:4182
python -m scripts.qa_checks         # 10 项功能检查
```

## 3. 评测

```powershell
python -m eval.run_eval             # 确定性 21 条（约 5 秒）
python -m eval.run_eval --semantic  # 含语义 6 条（约 8 分钟）
python -m eval.run_eval --anchors   # 锚点 20 条
```

## 4. 故障表

| 现象 | 原因 | 处理 |
|---|---|---|
| `docx=0` | 没生成合同 | `python -m scripts.gen_contracts` |
| 断言"每条规则至少违反 1 次"失败 | 改了缺陷池/随机种子 | 重跑生成器；或调 `DEFECT_POOL` |
| 上传 400 | 非 .docx 或 >10MB | v1 只支持 docx |
| 语义型全为 not_detected | 网关不可达 / 证据定位失败 | 看 `data/traces/<id>.json` 的 findings |
| 语义误报多 | 主题守卫被关 | 检查 `src/semantic.py: TOPIC_WORDS` |
| 页号不准 | 估算值 | 属已知限制，报告标 `pages_estimated` |
| 端口 4182 占用 | 旧进程 | 改 `.env` 的 `PORT` |

## 5. 降级边界

- 不支持 PDF/扫描件；不做法律意见；不修改原文。
- 合成合同不代表真实合同全部风险形态。
- 语义判定为单模型单次，无第二判官。
