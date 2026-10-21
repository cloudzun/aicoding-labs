# ENVIRONMENT · 环境基线（合同审查）

> 锁定：Python 3.12.10｜python-docx｜PyYAML 6.0.3｜FastAPI｜端口 **4182**｜语义模型 `deepseek-ai/DeepSeek-V3`（默认硅基流动公网；确定性规则不需要模型）

## 1. 能力矩阵

| 能力 | 来源 | 状态 | 说明 |
|---|---|---|---|
| docx 解析 | python-docx | ✅ | 段落 + 段内偏移；页号为估算（每 40 段 ≈ 1 页） |
| PDF 解析 | — | ❌ **不支持** | v1 明确排除，避免解析质量污染指标 |
| 确定性规则 | 本地正则/标题匹配 | ✅ | 21 条，单份 ~1–3ms |
| 语义规则 | LLM `deepseek-ai/DeepSeek-V3`（默认硅基流动；内网档 B 为 `opencode-go/deepseek-v4.1-flash`） | ✅ | 6 条，单份 5–15s |
| 数据库 | 无 | — | 纯文件处理，无状态 |
| GPU/容器 | — | ❌ | 不需要 |

**与 ② 的关键差异：** ③ 重新依赖 LLM（语义规则），因此必须带 **judge 自检/证据定位校验**；② 是零 judge。

## 2. 数据基线

| 项 | 值 | 证据 |
|---|---|---|
| 合同 | 30 份 docx（3 类 × 10） | `data/contracts/` |
| 判定单元 | 810（27×30） | `data/truth/units.jsonl` |
| 有缺陷 / 正常 | 24 / 6 | `data/manifest.json` |
| 植入违规 | 111（= 真值风险数） | `evidence/data-verify.json` |
| 规则覆盖 | 27 条每条至少被违反 1 次 | 同上 |

## 3. 安全与合规

| 项 | 实现 |
|---|---|
| 上传格式 | 仅 `.docx`，其它 400（防 PDF/图片混入导致"假通过"） |
| 上传大小 | ≤10MB |
| 提示注入 | 文档正文包在分隔符内 + "忽略以上指令"类文本清洗 + 输出必须过 schema |
| 语义幻觉 | 判违规必须有原文引用，且引用必须能在原文定位，否则降级 `not_detected` |
| 原文外泄 | trace 只存定位与 ≤200 字引用，不存全文 |
| 合规声明 | 首页固定横幅：合成虚构文本 + 上游云端 + 不构成法律意见 |

## 4. 已知限制

- 页号是估算，不是真实分页（python-docx 不含分页信息）。
- 表格内文字未纳入解析（模板合同暂不含表格）。
- 语义规则 6 条较粗，未做"偏离度升级"。
- 单份 10 页以上未实测（当前 30 份均为 1 页估算）。

## 5. 复现

```powershell
cd cases\03-contract-review
python -m scripts.gen_contracts     # 30 份 docx + 810 单元（约 2 秒）
python -m scripts.verify_data       # 10 项断言
python -m src.server                # → http://127.0.0.1:4182
python -m eval.run_eval             # 确定性 21 条（约 5 秒）
python -m eval.run_eval --semantic  # 含语义 6 条（约 5–8 分钟）
```

## 6. v1.1.0.0 变更（2026-10-20 诊断轮）

| 项 | 变更 | 影响 |
|---|---|---|
| 标题匹配 | 只匹配标题部分（heading_part） | 缺失型 recall 76.67% → 100% |
| 标题别名 | rules.yaml 支持 heading_aliases | 真实合同泛化预留；合成语料未触发 |
| 缺失项定位 | infer_missing_locator，标 inferred=true | 缺失项覆盖率 100%，但**位置是推断** |
| 指标 | 定位准确率 + 缺失项位置覆盖率（旧口径对照） | 旧 47.62% 与新 100% 不可混用 |

**仍不支持：** PDF/表格、>6000 字符合同的分块审查。
**v1.2 新增：** `rules.yaml: stance`（甲方视角）已注入语义 prompt——语义精确率 51.79% → 100%。
