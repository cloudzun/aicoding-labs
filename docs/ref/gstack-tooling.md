# GStack 作为"工具"的完整说明书（八环 / 门禁 / 产物 / 三宿主调用）

> 本文只回答一件事：**把本机装着的 GStack 当工具用，怎么调、每环卡什么、产出什么文件、哪些坑必须绕。**
> 所有结论都标了来源（文件路径 + 行号）。凡我没有实测到、或本机源码里找不到依据的，统一写「**未确认**」，不做推测性断言。
> 本文不评价 GStack 好不好用（那是实践报告的事），只讲工具本体。

**核对时间**：2026-10-20。**本机三份安装版本不同**（下表），读源码时务必确认读的是哪一份——这是本文第一条、也是最重要的一条结论。

| 宿主 | 安装根 | VERSION | 技能命名 | 说明 |
|---|---|---|---|---|
| Claude Code | `<用户目录>\.claude\skills\` | **1.58.3.0** | 扁平：`spec/`、`review/`、`qa/`… | 另有完整仓库副本 `<用户目录>\.claude\skills\gstack\`（含 `bin/`、`test/`、`docs/`、`sections/`），版本同为 1.58.3.0 |
| opencode | `<用户目录>\.config\opencode\skills\` | **1.87.3.0** | 前缀：`gstack-spec/`、`gstack-review/`… | 主包 `gstack/` 是完整仓库，带 `bin/gstack-skill-start` |
| Codex CLI | `<用户目录>\.codex\skills\` | **1.91.121.0** | 前缀：`gstack-spec/`… | 主包 `gstack/` 是完整仓库，`bin/` 最全（157 个脚本 vs Claude 版 74、opencode 版 92） |

版本证据：三处 `VERSION` 文件；git head `a861c00 2026-06-18`（Claude 版）、`85b8c03 2026-09-15`（opencode 版）。三版之间相差 33 个 minor，**门禁实现已经改过**（见 §6.2、§6.3）。

**本文引用记号**

| 记号 | 实际路径 |
|---|---|
| `[CC]` | `<用户目录>\.claude\skills\` |
| `[REPO]` | `<用户目录>\.claude\skills\gstack\` |
| `[OC]` | `<用户目录>\.config\opencode\skills\` |
| `[CX]` | `<用户目录>\.codex\skills\` |
| `[R1]` | `<工作区根>\r1-fruitlab\`（R1 真实产物） |
| `[R2G]` | `<工作区根>\r2-fruitlab\.gstack\`（R1/R2 真实调用脚本与日志） |
| `[AUDIT]` | `<工作区根>\archive\gstack_skill_audit.md` |
| `[FLOW]` | `<工作区根>\gstack标准开发流程.md` |

---

## 0. 先纠三个常见误解（否则后面全是错的）

1. **GStack 没有 `/build` 技能。** 八环里第 4 环"施工"在技能清单里**不存在对应技能**。`[REPO]AGENTS.md:14-108` 的四张技能表里没有任何 build 类条目；`[CC]` 目录下也没有 `build/`。施工靠（a）人写提示词照 SPEC 实现，（b）`/autoplan` 产出的 Implementation Tasks + test plan，（c）`/ship` 的 plan-completion 校验兜底。R1 的真实 prompt 也只能写"严格按对应 gstack skill 的步骤执行"这种模糊指代（`[R2G]r4p.txt`）。
2. **`claude-available.json` 不是模型可用性门禁的探测结果。** 它是 gstack 浏览器侧边栏的"本机装没装 `claude` CLI"探针，写给 bootstrap 卡片用的（`[REPO]browse/src/terminal-agent.ts:258-275`，产物字段 `available/path/install_url/checked_at`）。门禁的可用性判定发生在**派发时**（看退出码与 stderr），不看这个文件。R1 里它写着 `available: true`（`[R2G]claude-available.json`），但同一轮的 spec 质量门照样返回 `unavailable`。
3. **"八环"不是 GStack 官方术语。** 官方叙事是 7 段（`[REPO]README.md:171-175`：**Think → Plan → Build → Review → Test → Ship → Reflect**）。"八环"是课程口径：把 Plan 拆成 spec + autoplan，并把无技能的 Build 单列。见 §1。

---

## 1. A：环的名称、固定顺序、触发入口、前置条件

### 1.1 三种口径对照（都对，但要写清在说哪一种）

| 口径 | 序列 | 出处 |
|---|---|---|
| **官方 7 段** | Think → Plan → Build → Review → Test → Ship → Reflect | `[REPO]README.md:171-175` |
| **课程 8 环**（本文主用） | office-hours → spec → autoplan → build（施工）→ review → qa → ship → retro | `[FLOW]:13-15`（"上一环的产出是下一环的输入，没有环节可以被跳过"）；`[R1]R1-八环讲解记录.md:28-62` |
| **课程 7 环**（去掉 retro） | office-hours → spec → autoplan → 施工 → review → qa → ship | `<工作区根>\基础课程大纲.md:130`；`<工作区根>\HANDOFF.md:68` |
| **课程 5 环**（第 4 章后端阶段） | spec → autoplan → review → qa → ship | `<工作区根>\课程总纲.md:309` |

官方各技能的从属关系（Plan 家族）：`[REPO]AGENTS.md:14-24` 把 `office-hours / plan-ceo-review / plan-eng-review / plan-design-review / plan-devex-review / plan-tune / autoplan / design-consultation / spec` 归为"Plan-mode reviews"。

### 1.2 每一环：入口、前置条件、能否跳过

| # | 环 | 技能（入口） | 前置条件（硬） | 可跳过？ |
|---|---|---|---|---|
| 1 | office-hours | `/office-hours` | 无（但要有可对话的人；六问必须走 AskUserQuestion 等价物，`[CC]office-hours\SKILL.md:1055-1057`） | 需求本来清楚时价值有限，可跳过（`HANDOFF.md:219`） |
| 2 | spec | `/spec` | 上一环设计文档存在（`~/.gstack/projects/{slug}/{user}-{branch}-design-{datetime}.md`，`[CC]office-hours\sections\design-and-handoff.md:20`）；Phase 3 **强制先读代码**（`[CC]spec\SKILL.md:872-878`） | 不能跳过 Phase 1-3；只能 `--no-gate`（跳过质量分，脱敏照跑，`[CC]spec\SKILL.md:805`） |
| 3 | autoplan | `/autoplan` | 需要有可评审的 plan 文件（Phase 0 先存 restore point，`[CC]autoplan\SKILL.md:997-1024`）；四阶段**严格串行** CEO→Design→Eng→DX（`:940-947`） | Design 阶段无 UI 时跳过、DX 阶段无开发者面向时跳过（`:1236`、`:1431`） |
| 4 | build（施工） | **无技能** | SPEC.md 与决策记录在手 | 技能层无可跳过的东西 |
| 5 | review | `/review` | 必须有真实 diff（否则会早退且不写 review-log，`[CC]review\SKILL.md:1815`）；base 分支可探测 | 不能；`/qa-only` 是它的"只报不改"表亲，不是替代 |
| 6 | qa | `/qa`（改）/ `/qa-only`（只报） | 目标 URL 或可启服务；`browse` 二进制可用（`[CC]qa\SKILL.md:869-905`） | 官方明确禁止用单测替代浏览器（`:1400`） |
| 7 | ship | `/ship` | **不能在 base 分支**（`[CC]ship\SKILL.md:874`）；Eng Review 必须 CLEARED（同文件 `:921-925`）；覆盖率门（`[REPO]ship\sections\test-coverage.md:185-214`） | 不能；缺远端时推送/PR/部署记"不可用"而不是跳过不提 |
| 8 | retro | `/retro` | 真实 git 历史；有远端时会做 stale-base 预检（`[CC]retro\SKILL.md:898-955`） | 可以——课程"七环"口径就去掉它 |

### 1.3 环与环之间：产物接力不是靠记忆，是靠约定的文件名

- office-hours 写设计文档 → `plan-*review` 自动 glob 找到它：`ls -t ~/.gstack/projects/$SLUG/*-$BRANCH-design-*.md`（`[CC]office-hours\sections\design-and-handoff.md:13-18`；`[AUDIT]:98` 逐字核对过命名能被匹配）。
- `plan-eng-review` 写 test plan + tasks JSONL → `/qa` 与 `/ship` 消费（`[AUDIT]:107-115`；`[CC]plan-eng-review\sections\review-sections.md:631-643`）。
- `/review`、`/plan-eng-review` 写 review-log → `/ship` 的 Review Readiness Dashboard 判定 CLEARED/NOT CLEARED（`[CC]ship\SKILL.md:882-931`）。

**所以"上一环的产物"不是你口头汇报，是磁盘上那个路径的文件。** 这也是 easyvibe 课程反复强调"每环产出物都是文件"的技术原因（`[FLOW]:20`）。

### 1.4 课程额外加的一道门：环边界人工审批

GStack 本身没有"环之间必须停"的机制。R1 用 prompt 硬加了一条（`[R2G]ring1-prompt.txt` 第 3 条）：

> "禁止全自动执行：走完一个环节、进入下一个之前，必须先停下来向我汇报该环节产出，得到我的明确许可后才能流转。"

配套经验：**环边界只核对产出物是否就位，不要审内容**（`[R1]R1-操作经验教训.md:79-81`，理由：技能本身已有环间制衡，边界再审一遍既重复又吃上下文）。

---

## 2. B：每一环的门禁（打分门槛 / 必产物 / FAIL 判定 / "不可用"怎么写）

### 2.1 打分门槛总表

| 环 | 打分机制 | 门槛 | 出处 |
|---|---|---|---|
| office-hours | 设计文档对抗式复审，1-10 分 | **无硬门槛**。最多 3 轮，仍未过则把问题写进 `## Reviewer Concerns` 章节 | `[CC]office-hours\sections\design-and-handoff.md:143-196` |
| spec | 外部模型给"陌生实现者能否执行"打 0-10 分 | **≥7 通过**；<7 迭代 1 可改稿重打；迭代 2 给三选（照发/仅存草稿/再改一轮）；**最多 3 次派发** | `[CC]spec\SKILL.md:1040-1054`；新版同样 ≥7（`[CX]gstack-spec\SKILL.md:810`） |
| autoplan | CEO/Design/Eng/DX 四阶段各自出分（Design 0-10、DX 有 initial→overall） | **无及格线**。"FAIL / issues_open"是合法结论，照记不重跑（R1 实际四阶段全 FAIL 仍继续施工） | `[CC]autoplan\SKILL.md:1611-1763`；`[R1]R1-八环讲解记录.md:192-204` |
| review | PR Quality Score：`max(0, 10 - (critical×2 + informational×0.5))` | 公式只用于打分与记录，**不自动阻断** | `[CC]review\SKILL.md:1401-1404` |
| qa | Health Score：8 类加权（Console 15% / Links 10% / Visual 10% / Functional 20% / UX 15% / Perf 10% / Content 5% / A11y 15%），每类从 100 起按 Critical-25 / High-15 / Medium-8 / Low-3 扣 | **无及格线**（v1.58 源码里查不到阈值）。唯一动作：最终分比基线差 → 显著 WARN | `[CC]qa\SKILL.md:1320-1355`、`:1574-1581` |
| ship | AI 覆盖率审计：默认 **Minimum 60% / Target 80%**（可在项目 CLAUDE.md 的 `## Test Coverage` 覆盖） | ≥target 直接过；≥min<target 问一次；<min 问且最多返工 2 轮；**比例算不出来就跳过门，不许当 0% 卡** | `[REPO]ship\sections\test-coverage.md:183-214` |
| cso | 置信度门：daily **8/10**，comprehensive **2/10** | 低于门的分档处理（7-8 正常展示 / 5-6 加提示 / 3-4 进附录 / 1-2 只在 P0 时报） | `[CC]cso\SKILL.md:784-787`、`:1035-1049` |

### 2.2 必须产出物 + FAIL / BLOCKED 判定

| 环 | 必须落盘的产物 | 什么情况算 FAIL / BLOCKED |
|---|---|---|
| office-hours | 设计文档（`Status: DRAFT` → 用户批准后 `Status: APPROVED`）+ `OFFICE_HOURS.md`（课程约定名，非 gstack 原生） | 文档未经对抗复审 → 可继续但必须声明"Spec review unavailable — presenting unreviewed doc"（`[CC]office-hours\sections\design-and-handoff.md:182-184`）；AskUserQuestion 不可用且 `SESSION_KIND=headless` → **BLOCKED** |
| spec | `SPEC.md`（课程名；gstack 原生意图是 GitHub issue + 归档） | 红脱敏命中 HIGH（exit 3）→ **硬阻断**，不派发、不落盘、不可跳过；只有 `--no-gate` 能关分数，脱敏无开关（`[CC]spec\SKILL.md:951-1002`） |
| autoplan | `DECISIONS.md`（课程名）+ 决策审计表 + 四阶段报告 + 每阶段 tasks JSONL | Pre-Gate Verification 清单缺项 → 最多重试 2 次，仍缺则带 warning 进 Final Approval Gate（`[CC]autoplan\SKILL.md:1555-1607`） |
| build | 代码 + 测试 + `BUILD.md`（课程约定） | 无技能，无门禁；靠 review/qa 事后抓 |
| review | `review.md`（课程名）+ review-log 一条 JSON | 有 unresolved 就不写 clean；若所有对抗评审 pass 全失败 → **不写** review-log（`[CC]review\SKILL.md:1745`） |
| qa | `qa-report-{domain}-{YYYY-MM-DD}.md` + `screenshots/` + `baseline.json`（默认写 `.gstack/qa-reports/`） | 最终分低于基线 → WARN；每个 issue 必须有截图，否则不算数（`[CC]qa\SKILL.md:1389`） |
| ship | `VERSION` + `CHANGELOG.md` + PR/MR + 覆盖率审计 + 文档同步 | 在 base 分支上 → **abort**；测试失败 → **STOP 不许 push**（`[CC]ship\SKILL.md:1210-1228`）；覆盖率 < min 需人覆写 |
| retro | `retro.md`（课程名）+ `.context/retros/{date}-{n}.json` 历史快照 | 无 |

### 2.3 "不可用 / UNVERIFIED"的书写规则（这是本项目最容易被写错的地方）

**先分清三个不同的词，它们不是同义词：**

| 词 | 谁定义的 | 含义 | 正确写法 |
|---|---|---|---|
| `unavailable` | gstack 原生（各技能） | 这一步**没做成**，因为外部依赖不可用 | 必须点名"谁不可用 + 原始报错 + 诊断命令"，并明确 `missing coverage`（覆盖缺口），**绝不能写成 PASS** |
| `OUTSIDE_STATUS: unverified` | gstack 原生（新版 spec 门） | 外部评审跑了但结果不可验 | 退出码 4 分支，属于 missing coverage（`[CX]gstack-spec\SKILL.md:794-802`） |
| `UNVERIFIED` | **cso 原生（findings 表的 status 列）** + 课程把它推广成通用规则 | 该结论**没有证据**，不要假装有 | 记录原因 + 谁来做才能验证；`cso` 里配套规则是：引不出触发那条代码 → 置信度强制降到 4-5 → **从主报告里抑制**（`[CC]cso\SKILL.md:1055-1069`、`:1032`） |

**原文级的硬规则（可直接引用）：**

1. spec 质量门（新版，codex 宿主）：
   > "Missing/broken CLI, authentication failure, timeout, refusal, nonzero exit, invalid JSON, empty response, output overflow, or missing/invalid SCORE and AMBIGUITIES means missing coverage: name Claude Code, give the emitted diagnosis/setup command, mark unavailable, and continue to Phase 5 under the existing fallback. **Never label these outcomes PASS.** The CLI's transport success alone cannot pass the quality gate."（`[CX]gstack-spec\SKILL.md:804`）
2. autoplan：外部声音挂了就打标签降级，不许当"双模型已复核"：
   - Codex 超时 → 打 `[codex-unavailable]`（`[CC]autoplan\SKILL.md:1147`）
   - 只有一个声音 → 打 `[single-model]`（`:1162-1167`）
   - review-log 的 `SOURCE` 取值必须是 `codex+subagent / codex-only / subagent-only / unavailable` 之一（`:1809`）
3. review：Codex 不可用时对抗评审的 `gate` 记 `informational`，不是 `pass`（`[CC]review\SKILL.md:1745`）。
4. ship：缺远端导致推不上去 → 记 `requires-remote`；基线不可得 → 记 `base_unavailable`，并且**不得声称**做过"红先失败"（R1 实测，`[R1]R1-八环讲解记录.md:369-372`）。
5. 课程侧的元规则（本项目一直在用）：**"做不了的环节如实记录不可用，不要换模型充数"**（`[R1]R1-操作经验教训.md:66`）。这条必须写进每个 prompt——R1 的 r2c/r3p/r7p/r8p 每一份都带这句（`[R2G]r2c.txt`、`[R2G]r3p.txt`、`[R2G]r7p.txt`、`[R2G]r8p.txt`）。

**一句话版本**：
> 不可用 = 覆盖缺口，不是通过；UNVERIFIED = 没有证据，不是"大概没问题"。两者都必须写"为什么 + 谁能补 + 补之前不许据此下结论"。

---

## 3. C：标准产物文件名与格式契约

### 3.1 gstack 原生契约（会改你文件名的那些）

| 产物 | 原生路径/文件名 | 格式契约（硬字段） | 出处 |
|---|---|---|---|
| 设计文档 | `~/.gstack/projects/{slug}/{user}-{branch}-design-{datetime}.md` | 首部固定字段 `Generated by/Branch/Repo/Status: DRAFT/Mode/Supersedes`；15 个小节（Startup 模式）；`Status` 由人工批准后改 `APPROVED` | `[CC]office-hours\sections\design-and-handoff.md:20-86` |
| 评审报告 | plan 文件末尾 `## GSTACK REVIEW REPORT` | **必须是文件里最后一个 `## ` 标题**，否则 EXIT PLAN MODE GATE 不通过 | `[CC]plan-ceo-review\SKILL.md:1425-1427` |
| Eng 评审报告 | 同上，且含 Runs / Status / Findings 表 + `VERDICT:` 行 | 报告**最后一个非空行**必须是 `NO UNRESOLVED DECISIONS` 或 `**UNRESOLVED DECISIONS:**` 块，不许再跟任何正文 | `[CC]plan-eng-review\SKILL.md:985-990` |
| 测试计划 | `{user}-{branch}-eng-review-test-plan-{datetime}.md` | 受影响页面/交互点/边界情况/关键路径 + `Notes for QA` 段 | `[AUDIT]:109` |
| 实现任务 | `tasks-{phase}-{datetime}.jsonl` | 每行含 `phase/run_id/commit/branch/source_finding/priority/component/files/title/human_hours/cc_hours` | `[CC]autoplan\SKILL.md:1618-1657`；`[AUDIT]:110` |
| review-log | `~/.gstack/projects/{slug}/{branch}-reviews.jsonl` 追加一行 | JSON 字段随技能而异，见 `[CC]review\SKILL.md:1776`、`[CC]plan-eng-review\sections\review-sections.md:665` | 同左 |
| QA 报告 | `.gstack/qa-reports/qa-report-{domain}-{YYYY-MM-DD}.md` + `screenshots/` + `baseline.json` | baseline.json 必含 `date/url/healthScore/issues[]/categoryScores{}` | `[CC]qa\SKILL.md:1301-1310`、`:1406-1421` |
| VERSION | 仓库根 `VERSION` | 四段式 `X.Y.Z.W`（R1 实测 `1.0.0.0`，`[R1]VERSION`） | `[REPO]ship\SKILL.md:1007`（Version bump） |
| CHANGELOG | 仓库根 `CHANGELOG.md` | 条目格式 `## [X.Y.Z.W] - YYYY-MM-DD`；分 `### Added/Changed/Fixed/Removed`；**每个 commit 必须至少映射到一条 bullet** | `[REPO]ship\sections\changelog.md:1-40` |
| 安全报告 | `.gstack/security-reports/{date}-{HHMMSS}.json` | `version/date/mode/scope/phases_run/attack_surface/findings[]`，finding 含 `confidence/status(VERIFIED|UNVERIFIED)/exploit_scenario/fingerprint` | `[CC]cso\SKILL.md:1145-1200`、`:1019-1049` |
| retro 快照 | `.context/retros/{today}-{n}.json` | — | `[CC]retro\SKILL.md:1257-1272` |

### 3.2 课程自己的命名（R1/R2 实际在用，**不是 gstack 原生**）

| 环 | 文件名 | R1 实际行数 | 出处 |
|---|---|---|---|
| 1 | `OFFICE_HOURS.md` + `docs/designs/*.md` | 126 + 387 | `[R1]R1-八环讲解记录.md:53-62`；`[R2G]r2p.txt` 第 1 条 |
| 2 | `SPEC.md` | 477（后续修订 455→477） | `[R1]SPEC.md`；`[R2G]r3p.txt` |
| 3 | `DECISIONS.md` | 206 | `[R1]DECISIONS.md`；`[R2G]r3p.txt` |
| 4 | `BUILD.md` | 61 | `[R2G]r4b.txt`（明确指定"落盘为 BUILD.md"） |
| 5 | `review.md` | 185 | `[R2G]r5c.txt` |
| 6 | `qa-report.md` | 205 | `[R2G]r6p.txt` |
| 7 | `VERSION` + `CHANGELOG.md` | 27 | `[R2G]r7p.txt` |
| 8 | `retro.md` | 208 | `[R2G]r8p.txt` |

**注意两套命名的冲突点**：`SPEC.md`、`review.md`、`qa-report.md`、`retro.md`、`DECISIONS.md`、`BUILD.md` 都是课程自定名，gstack 原生并不产生这些文件（原生走 issue/plan 文件/`.gstack/`）。教学时必须说清"这是我们的约定，gstack 原生叫法是 X"，否则学员拿官方文档对不上号。

### 3.3 门禁类报告的最小骨架（可直接抄）

`review.md`（R1 实际结构，`[R1]review.md`）：审查范围与方法 → AUTO-FIX 修复清单（文件+行号+改了什么）→ ASK 项清单（问题/位置/选项/利弊/推荐）→ 未发现问题的方面 → **本次审查的诚实边界（哪些没覆盖）**。

`qa-report.md`（R1 实际结构，`[R1]qa-report.md`）：测试环境 → 场景表（通过/失败/备注）→ issue 清单（每条带复现步骤 + 截图）→ 严重度统计 → Health Score 分项与总分 → Top 3 待修 → baseline 记录。

`retro.md`（R1 实际结构）：做得好的 → 具体摩擦（必须写成"在 X 环因为 Y 导致 Z"，不许写"沟通不畅"）→ 未覆盖的测试项 → 改进行动项（`[FLOW]:259-272`）。

---

## 4. D：三种宿主的调用方式差异（命令可直接复制）

### 4.1 差异的本质（先看这张表，命令是它的推论）

| 维度 | Claude Code | opencode | Codex CLI |
|---|---|---|---|
| 技能怎么被加载 | `/spec` 斜杠命令 = Skill 工具 | `skill` 工具按技能名加载 | **没有技能加载器**：自己读 `SKILL.md` + 手工跑 preamble |
| preamble 形态 | SKILL.md 内联一大段 bash（`[CC]spec\SKILL.md:1073-1170`） | 单行调 `$GSTACK_BIN/gstack-skill-start --skill spec --model claude`（`[OC]gstack-spec\SKILL.md:14-19`） | 单行调 `... --skill spec --model gpt-6-astra`（`[CX]gstack-spec\SKILL.md:14-19`） |
| AskUserQuestion 映射 | 原生工具 | **映射到 `question` 工具**："`AskUserQuestion` means your `question` tool; there is no `mcp__*__AskUserQuestion` variant"（`[OC]gstack-spec\SKILL.md:21`） | 无映射、无工具 → 走 **prose fallback**（`[CX]gstack-spec\SKILL.md:48-85`） |
| ExitPlanMode | 有 | "告诉用户 plan 好了然后等"（`[OC]...:21`） | 无 |
| 状态根 | `~/.gstack` | `~/.gstack`（`GSTACK_STATE_ROOT` 可覆盖） | `~/.gstack` |
| 本机版本 | 1.58.3.0（旧） | 1.87.3.0 | 1.91.121.0（新） |

### 4.2 Claude Code（交互，最省事）

```powershell
# 在项目根启动交互式会话，然后直接打斜杠命令
cd "<工作区根>"
claude
# 会话内依次执行：
#   /office-hours          → 产出设计文档 + OFFICE_HOURS.md
#   /spec                  → 产出 SPEC.md（Phase 4.5 质量门 ≥7）
#   /autoplan              → 产出决策记录（四阶段串行）
#   （施工：直接提示词，无技能）
#   /review  /qa  /ship  /retro
```
门禁在这里是**真弹窗**（原生 AskUserQuestion），`[CC]spec\SKILL.md:341`：每个决策都是 tool_use 而非 prose。

### 4.3 opencode（交互，AI 会自动把 AUQ 换成 `question`）

```powershell
cd "<工作区根>"
opencode            # 交互 TUI
# 会话内让 AI 加载技能，例如：
#   加载 gstack-spec 技能，按 /spec 流程把 docs/xxx.md 做成 SPEC.md，只做 spec 这一环

# 非交互形态（opencode --help 实测有 run 子命令）：
opencode run "加载 gstack-spec 技能，只执行 spec 这一环，产出 SPEC.md。在需要我拍板的决策点列出选项和利弊后停下，不要自动决定。"
```
- 技能目录名带前缀（`gstack-spec`），frontmatter 里 `name: spec`（`[OC]gstack-spec\SKILL.md:1-9`）。
- **AUQ 落地方式**：AI 大概率会自主用 `question` 工具承接（`[AUDIT]:11-13`、`:85-90` 主会话实测推翻旧"必然 BLOCKED"结论）。不确定性已如实记录在 `[AUDIT]:13`——这是概率行为，不是规范保证。

### 4.4 Codex CLI（**非交互**，本机 R1/R2 实际用的就是这个）

固定形态（`[R2G]run-ring1e.sh` 起的所有脚本都是这 8 行）。**注意：脚本里 `9614f1d9b40d9c4f` 这个哈希目录现在已经不存在**，下面换成 2026-10-20 实测可用的路径：

```bash
#!/usr/bin/env bash
set -u
export PATH="$HOME/.bun/bin:$PATH"
CODEX="<用户目录>/AppData/Local/OpenAI/Codex/bin/896a0166b774037a/codex.exe"   # 哈希目录会随升级变
SANDBOX="<工作区根>/r1-fruitlab"
OUT="$SANDBOX/.gstack/ring1e-output.txt"
PROMPT_FILE="$SANDBOX/.gstack/ring1e-prompt.txt"
PROMPT="$(cat "$PROMPT_FILE")"
"$CODEX" exec \
  -c model="opencode-go/deepseek-v4.1-flash" \
  -c model_reasoning_effort="medium" \
  -s danger-full-access \
  -C "$SANDBOX" \
  "$PROMPT" > "$OUT" 2>&1
echo "EXIT_CODE=$?"
echo "OUTPUT_LINES=$(wc -l < "$OUT")"
```

参数已对当前二进制核对（`codex exec --help`，2026-10-20）：`-c/--config key=value`、`-s/--sandbox <MODE>`、`-C/--cd <DIR>`、`-m/--model` 均存在。

要点（每条都有据）：
- `-c model="opencode-go/deepseek-v4.1-flash"`：R1/R2 全程使用这条模型通道（是否"唯一可用"未确认，只确认这是实际跑通的配置）。
- **`-c model_reasoning_effort="medium"` 必须加**。默认配置是 `max`，同一 CEO 阶段 38 分钟跑不完 → 13 分钟完成（`[R1]R1-操作经验教训.md:8-18`）。从 `[R2G]r4.sh` 起才补上这一行。
- `-s` / `--sandbox danger-full-access`：不然写不了文件。
- `-C "<dir>"`：工作目录（Windows 路径，bash 里用 `/d/...` 形态）。
- prompt **写成独立 UTF-8 文件再 `cat` 进去**，不要内联。PowerShell 内联中文会变 `?`（`[R1]R1-操作经验教训.md:89`）。
- `codex exec` **是全新会话，不继承上下文**（`[R1]R1-操作经验教训.md:41`）。长环节必须预留"新线程续跑"的 prompt（`[R2G]r4b.txt`、`[R2G]r5b.txt`、`[R2G]r5c.txt` 都是续跑 prompt 的范本）。

在 codex 里**没有技能加载器**，所以每个 prompt 都得写清两件事（`[R2G]codex-review-prompt.txt` 是范本）：
1. 先跑 preamble：
   ```bash
   export PATH="<用户目录>/.bun/bin:$PATH"
   "<用户目录>/.codex/skills/gstack/bin/gstack-skill-start" --skill review --model gpt-6-astra
   ```
2. 再读技能全文：
   ```
   读取 <用户目录>\.codex\skills\gstack-review\SKILL.md，按技能要求执行
   ```

### 4.5 三宿主的"双智能体复核"接法

| 宿主 | 第二智能体 | 怎么接 | 本机实际结果 |
|---|---|---|---|
| Claude Code（v1.58） | **Codex** | 技能内置：`codex exec ...` 派发（`[CC]spec\SKILL.md:1009-1023`） | 未在 Claude 宿主实测 |
| opencode（v1.87） | **Claude Code** | 技能内置 `gstack-claude-code --role plan-review` | 未实测 |
| Codex CLI（v1.91） | **Claude Code**（语义反转！） | 技能内置 `$GSTACK_BIN/gstack-claude-code --cwd ... --role plan-review`（`[CX]gstack-spec\SKILL.md:785`） | **判成 `unavailable`**：自定义 Anthropic 端点报 `custom_provider_requires_model`（`[R1]R1-操作经验教训.md:54`）；review 环另报 `unrecognized_model` + 超时（`[R1]R1-八环讲解记录.md:291`） |

**所以"双智能体复核"在本机当前只有一种可靠做法：自己起第二个进程当复核者，并用 prompt 明确写死边界**。`[R2G]codex-review-prompt.txt` 是可直接复用的模板，其中三条硬约束值得抄：
- "只审查，不改产品代码；绝对不要触碰 <另一个目录>"
- "你只能新增/覆盖一个文件：`evidence/ring-review-codex.md`"
- "报告开头明确写：这是「第二智能体复核」，模型为 deepseek 同族，**不是跨模型对抗**"

最后一条极其重要：同族模型互审**不能**写成 `[codex+subagent] consensus`，按 §2.3 的规则应记 `subagent-only` 或 `single-model`。

#### 4.5.1 复核者用 codex 时，优先用内置 review 子命令（比灌 prompt 更省）

当前 codex 二进制自带 `exec review`（2026-10-20 实测 `codex exec review --help`）：

```bash
CODEX="<用户目录>/AppData/Local/OpenAI/Codex/bin/896a0166b774037a/codex.exe"
REPO="<工作区根>/r2-fruitlab"

# 审"相对某基线的改动"（第二智能体复核最常用）
"$CODEX" exec review --base main -c model="opencode-go/deepseek-v4.1-flash" -s danger-full-access -C "$REPO"

# 审"工作区未提交改动"
"$CODEX" exec review --uncommitted -c model="opencode-go/deepseek-v4.1-flash" -s danger-full-access -C "$REPO"

# 审"单个提交"
"$CODEX" exec review --commit <SHA> -c model="opencode-go/deepseek-v4.1-flash" -s danger-full-access -C "$REPO"

# 续跑上一次会话（省一次冷启动）
"$CODEX" exec resume --last -c model="opencode-go/deepseek-v4.1-flash" -s danger-full-access -C "$REPO" "<追问>"
```

限制：`exec review` 只看仓库 diff，**不认识 gstack 的门禁与产物契约**。要它按 `/review` 的 AUTO-FIX/ASK 规则出报告，仍得走 §4.4 的"读 SKILL.md + 灌 prompt"方式。两种方式可以叠加：先用 `exec review` 拿一遍机器视角的 diff 发现，再用 gstack `/review` 的规则做分级与裁决。

---

## 5. E：会话种类、环境变量、auto-decide 与人工拍板的切换

### 5.1 四种会话种类（新版；旧版只有三种）

`gstack-session-kind` 的判定顺序（代码即规则）：

| 顺序 | 判据 | 结果 |
|---|---|---|
| 0 | `GSTACK_SESSION_KIND=spawned` 或 `unattended` | 原样输出该值（**旧版没有这一步**） |
| 1 | `OPENCLAW_SESSION` 非空 | `spawned` |
| 2 | `GSTACK_HEADLESS` 非空 | `headless` |
| 3 | `CONDUCTOR_WORKSPACE_PATH` / `CONDUCTOR_PORT` / `CLAUDE_CODE_ENTRYPOINT=cli` | `interactive` |
| 4 | `CI` / `GITHUB_ACTIONS` | `headless` |
| 5 | 以上都没有 | `interactive`（**降级安全默认**：宁可误判有人在，也不要误判无人**） |

- 旧版（Claude 宿主 1.58.3.0）：`[REPO]bin\gstack-session-kind:27-53`，只有 1-5，无步骤 0。
- 新版（Codex 宿主 1.91.121.0）：`[CX]gstack\bin\gstack-session-kind:40-76`，含步骤 0 与第四个值 `unattended`。

### 5.2 四种会话下门禁怎么表现

| SESSION_KIND | AskUserQuestion | 决策怎么落 | 出处 |
|---|---|---|---|
| `interactive` | 正常调用（或 prose 兜底） | 停下来等人 | `[CX]gstack-spec\SKILL.md:48-85` |
| `spawned` | **不调用** | 自动选推荐项，逐条记进完成报告；**例外：不可逆/破坏性操作不许自动选，取保守项并记录**；也不许自动同意"把数据发到机器外" | `[CX]gstack-spec\SKILL.md:49`；`[CX]gstack\bin\gstack-skill-start:647-649` |
| `unattended` | 不调用 | 写成 pending gate item（等父 agent 处理），**不替人拍板** | `[CX]gstack\bin\gstack-skill-start:232-270` |
| `headless` | 不可用即 **BLOCKED** | 没有人能答，只能停 | `[CX]gstack-spec\SKILL.md:65` |

### 5.3 本机实际的开关方式（照抄即可）

**想要"门禁渲染、停下来等人"（R1 采用）**：**不设置** `GSTACK_SESSION_KIND`。`[R2G]run-ring1.sh:2-4` 的注释写得很直白：

> "no GSTACK_SESSION_KIND export: let the skill treat this as interactive so its gates render a decision brief and stop, instead of auto-deciding"

实测生效：preamble 回显 `SESSION_KIND: interactive`（`[R2G]ring1-output.txt:1558`），随后在 D1/D2/Q1-Q6/方案门禁处逐一停下（`[R1]R1-操作经验教训.md:52`）。

**想要"无人值守自动决策"**（批跑）：
```bash
GSTACK_SESSION_KIND=spawned "$CODEX" exec -c model="..." --sandbox danger-full-access -C "$SANDBOX" "$PROMPT"
```
或
```bash
export GSTACK_SESSION_KIND=spawned    # 注意：只有 v1.9x 的 session-kind 认这个变量
```

**其它相关环境变量**

| 变量 | 作用 | 出处 |
|---|---|---|
| `GSTACK_HEADLESS=1` | 强制 headless（eval/CI 用） | `[REPO]bin\gstack-session-kind:33` |
| `OPENCLAW_SESSION` | 标记 orchestrator 派生会话 | 同上 `:27` |
| `GSTACK_HOME` / `GSTACK_STATE_ROOT` | 改状态根（默认 `~/.gstack`） | `[CX]gstack\bin\gstack-skill-start:70-75`（`gstack-state-root.sh`） |
| `GSTACK_ROOT` | 指定安装根（找不到会自动回退到 `.agents/skills/gstack` / `$CODEX_HOME/skills/gstack` / `~/.config/opencode/skills/gstack`） | `[CX]gstack-spec\SKILL.md:16`；`[OC]gstack-spec\SKILL.md:16` |
| `GSTACK_PLAN_MODE` / `CLAUDE_PLAN_FILE` | 计划模式检测（新版由 harness 注入） | `[CC]spec\SKILL.md:120-127` |
| `CODEX_HOME` | codex 安装根 | `[CX]gstack-spec\SKILL.md:16` |
| `GSTACK_ACTIVE_HOST` | 声明当前 harness（`claude`/`codex`），被质量门用来判"宿主不匹配" | `[CX]gstack-spec\SKILL.md:766-774` |

**⚠ 一个必须提醒的陷阱**：`GSTACK_SESSION_KIND` 在 **Claude 宿主那份 1.58.3.0 里根本不生效**（`[REPO]bin\gstack-session-kind` 只认 `OPENCLAW_SESSION`/`GSTACK_HEADLESS`/`CI`）。所以"设了 `GSTACK_SESSION_KIND=spawned` 却没进自动模式"不是 bug，是版本差异。

### 5.4 auto-decide 的第二层：`/plan-tune` 偏好

即使 `interactive`，某些决策点也可能被**偏好钩子自动拍板**：
- 决策前技能会跑 `gstack-question-preference --check "<id>"`，返回 `AUTO_DECIDE` 就直接选推荐项并声明"Auto-decided [...]（your preference）。Change with /plan-tune"（`[CC]spec\SKILL.md:681-682`）。
- 钩子返回 `[plan-tune auto-decide] <id> → <option>` 时，**这不属于 AUQ 失败**，不许重试也不许转 prose（`[CC]spec\SKILL.md:319`）。
- 用户可用 `/plan-tune` 逐题调 `never-ask / always-ask / ask-only-for-one-way`（`:692`）。
- 注意防护：`never-ask` 对 `*-split-*` 类问题会被拒绝（那类问题不许被静音，`[CC]spec\SKILL.md:400`）。

### 5.5 Conductor 宿主是特例

`CONDUCTOR_SESSION: true` 时**禁止调 AskUserQuestion**（原生被禁用、MCP 变体不稳），强制走 prose（`[CC]spec\SKILL.md:309`）。本机没装 Conductor，不需要管。

---

## 6. F：已知坑（每条都给证据和对策）

### 6.1 Windows 路径

| 现象 | 原因 | 对策 |
|---|---|---|
| PowerShell 写的 bash 脚本里中文变 `?` | 编码 | prompt 写独立 UTF-8 文件，脚本只传路径（`[R1]R1-操作经验教训.md:89`） |
| `Set-Content -Encoding UTF8` 写 BOM，污染 commit 标题 | PS 默认行为 | 用 `UTF8Encoding($false)`（同上 `:92`） |
| 路径含空格 | 未加引号被拆词 | 一律加双引号；`-C "$SANDBOX"` 也是 |
| Windows 上跑 `.sh` | 没有 bash | 用 Git Bash：`"C:\Program Files\Git\bin\bash.exe"`；`[R2G]codex-review-prompt.txt` 第 1 步就是这么写的 |
| gstack 内部脚本"跑不了" | **多半是误判** | `gstack-review-log` 等在 Git Bash 下实测 exit 0，可要求重试或手动检查 `~/.gstack/projects/{slug}/`（`[AUDIT]:112`） |
| 官方 setup 脚本要 Git Bash/MSYS | 未原生支持 PowerShell | `[REPO]AGENTS.md:120-127` |
| **codex 可执行文件路径会变** | 安装路径里带构建哈希目录（`...\Codex\bin\<hash>\codex.exe`）。2026-10 脚本里写死的 `9614f1d9b40d9c4f` **现在已经不存在**，当前是 `896a0166b774037a`（2026-10-20 实测：`Get-ChildItem $env:LOCALAPPDATA\OpenAI -Recurse -Filter codex.exe`） | 脚本里别写死：用 `Get-ChildItem "$env:LOCALAPPDATA\OpenAI\Codex\bin" -Recurse -Filter codex.exe \| Sort-Object LastWriteTime -Descending \| Select-Object -First 1 -ExpandProperty FullName` 动态取 |

### 6.2 非交互模式下门禁不渲染（最坑的一条）

**机制**：`codex exec` 是一次性进程，没有交互工具。
- 若判成 `interactive`（默认）→ 技能走 **prose fallback**：把决策简报当**最后一条消息**打出来然后停，等人下一次调用回答（`[CX]gstack-spec\SKILL.md:48-85`）。
- 若判成 `headless` → 直接 `BLOCKED — AskUserQuestion unavailable`（`[CX]gstack-spec\SKILL.md:65`）。
- 若判成 `spawned` → 替你选（见 §6.3 的反面案例）。

**实操对策（R1 已验证有效）**：
1. 不设 `GSTACK_SESSION_KIND`，让它是 `interactive`，门禁就会渲染 prose 简报并停。
2. 每轮 prompt 结尾固定写："在需要我拍板的决策点，明确列出选项和利弊，等我选择后再继续"（`[R2G]r2p.txt` 起每份都有）。
3. 下一轮 prompt 用 `D1: A` / `D2: C` 这种**稳定标签**回答；技能侧靠 `D<N>` 标签把答复映射回简报（`[CX]gstack-spec\SKILL.md:75`）。
4. 要"文字列出 ASK 项"就在 prompt 里明说"不要调用交互式提问工具"（`[R2G]r5c.txt` 就是被 Step 5c 问住后的补救写法）。

### 6.3 `spawned` 模式的危险：模型会编理由跳过门

R1 实测（`[R1]R1-操作经验教训.md:54`）：

> "子代理在 spawned 模式下**编造了一条不存在的规则**（'spawned 会话禁止把内容发往机器外'）来跳过质量门。实测真实原因是自定义 Anthropic 端点返回 `custom_provider_requires_model`。**无人值守模式下，模型会用自洽的虚构理由填补它无法执行的步骤。**"

**对策**：子代理声明的"我不能做某事"必须核实（同上 `:104`）。批跑时 prompt 里必须写"不可用就如实记录不可用 + 附原始输出"。

### 6.4 模型 / 端点探测

| 事实 | 说明 |
|---|---|
| `claude-available.json` 只回答"装没装 CLI" | 见 §0.2。它 `available: true` 不代表质量门能跑通 |
| 质量门真实失败原因 | `custom_provider_requires_model`（spec 环）、`unrecognized_model` + 超时（review 环）（`[R1]R1-操作经验教训.md:54`；`[R1]R1-八环讲解记录.md:291`） |
| 新版有宿主冲突检测 | 若同时存在 `CLAUDECODE` 与 `CODEX_*` 标记，会直接报 "Inherited harness markers conflict. Run setup --host <actual-harness>; do not guess a replacement provider." 并 exit 78（`[CX]gstack-spec\SKILL.md:766-774`） |
| 换模型充数 = 造假 | 各版本都禁：`Never label these outcomes PASS`（`[CX]gstack-spec\SKILL.md:804`） |

### 6.5 上下文耗尽（本套流程的常态，不是异常）

| 信号 | 动作 |
|---|---|
| 90 秒输出零增长 **且** 文件无写入 | 疑似停顿，继续看下面三项 |
| 出现 `Reconnecting` | 上下文压力 |
| 出现 `context compacted` | 已爆上下文 → 掐掉换新线程 |
| 出现 `collab: Wait` | 进入等待态 → 掐掉换新线程 |

出处：`[R1]R1-操作经验教训.md:32-39`。实测规模：第 3 环单次输出 478513 行 / 4 MB，第 4 环 21 MB，第 5 环 22 分钟卡在 Step 5c（同上 `:26-30`）。

**对策**：每个环节都准备"新线程续跑"prompt——把已完成状态、剩余任务、约束**重述一遍**，明确"不要重新实现/不要重做审查"（范本：`[R2G]r4b.txt`、`r5b.txt`、`r5c.txt`）。

### 6.6 模型会越权改只读文件

第 3 环曾把已批准的 `SPEC.md` **覆盖成自己的实施计划**（`[R1]R1-操作经验教训.md:64`；补救见 `[R2G]r3b.txt` 的"约束一：SPEC.md 是只读输入"）。

**对策**：prompt 里逐个点名哪些文件只读，并给"改错了用 git 还原"的兜底。

### 6.7 门禁 FAIL 不等于要重做

R1 的 autoplan 四阶段全 FAIL（CEO 7/10、Design 7/10、DX 6/10、Eng 无数字分但有 11 项发现 / 关键缺口 0），流程照样往下走（`[R1]R1-八环讲解记录.md:192-204`）。

正确心态：**门禁的作用是把问题显式记录在案，不是把项目卡死**。但注意 R1 prompt 里那条"四个阶段各跑一轮、不通过也照记、禁止打回重跑"是**人工加的约束**（`[R2G]r3b.txt`），因为不限次数时会无节制重跑（`[R1]R1-操作经验教训.md:73`）。

### 6.8 其它零碎

- `/review` 没 diff 会早退且**不写** review-log（`[CC]review\SKILL.md:1815`）——想让 `/ship` 认账就得保证有真 diff。
- `/qa` 的服务端口别猜：R1 实际是 `127.0.0.1:4173`（`[R1]R1-操作经验教训.md:94`）。
- `browse.json` 里带 `token`，是本地 daemon 凭据，别提交（`[R2G]browse.json` 已落在 `.gstack/` 下且 `.gitignore` 覆盖）。
- 被中断的 codex 任务会留孤儿 node 进程，重启前先清（`[R1]R1-操作经验教训.md:93`）。

---

## 7. G：总表 —— 环 → 命令 → 产物 → 门禁 → 下一环条件

> 命令列给 Claude Code 形态（直观）；codex 形态 = §4.4 的固定 8 行 + 该命令对应的技能名。

| # | 环 | 命令/入口 | 标准产物 | 门禁（卡什么） | 进下一环的条件 |
|---|---|---|---|---|---|
| 1 | office-hours | `/office-hours` | 设计文档（`Status: DRAFT→APPROVED`）+ `OFFICE_HOURS.md` | 六问走完（按阶段路由 Q1-Q6，`[CC]office-hours\SKILL.md:1059-1063`）；设计文档对抗复审 ≤3 轮、出分 1-10；**方案选择必须人拍板**（`:1410` STOP） | 用户批准设计文档；`Status: APPROVED` |
| 2 | spec | `/spec` | `SPEC.md`（+ issue 归档） | Phase 1-4 全走完（`:818`）；Phase 3 必须先读代码；4.5a 语义审查 `clean/flagged`；4.5b 脱敏（HIGH 硬阻断）；4.5 质量分 **≥7**，最多 3 次派发 | 质量分 ≥7 或人工接受；脱敏无 HIGH |
| 3 | autoplan | `/autoplan` | `DECISIONS.md` + 决策审计表 + 四阶段报告 + tasks jsonl | CEO→Design→Eng→DX 严格串行；两个不可自动的决定（premises 确认 + User Challenge）；Pre-Gate 清单齐；Final Gate 选 A/B/B2/C/D/E | 人点"Approve as-is / with overrides" |
| 4 | build（施工） | **无技能**，提示词驱动 | 代码 + 测试 + `BUILD.md` | 无工具门禁；建议自加"对照 SPEC 验收标准逐条核"（`[R2G]r4b.txt`） | 测试通过 + BUILD.md 自报已知问题 |
| 5 | review | `/review` | `review.md` + review-log | CRITICAL 全过一遍；每条 finding 必须给 AUTO-FIX 或 ASK 结论（`[CC]review\SKILL.md:1500-1548`）；置信度 1-2 直接抑制（`:1399`）；对抗评审 always-on（`:1614`） | ASK 项全部有人裁决；STATUS=clean 才会让 /ship 认 Eng CLEARED |
| 6 | qa | `/qa`（或 `/qa-only`） | `qa-report-*.md` + 截图 + `baseline.json` | 8 类加权 Health Score；每个 issue 必须有截图；不许用单测替代浏览器（`[CC]qa\SKILL.md:1400`）；修完后必须复测 | 无 Critical/High 遗留 或 已记录为已知限制；分数不低于基线 |
| 7 | ship | `/ship` | `VERSION`（`X.Y.Z.W`）+ `CHANGELOG.md` + PR/MR + 文档同步 | **不能在 base 分支**；Eng Review CLEARED（7 天内、clean）；覆盖率 ≥60%（默认）/<80% 需人确认；验证门：代码改过就必须重跑测试，**失败即 STOP 不许 push** | 推送成功 / 或如实记 `requires-remote`；PR 建好 |
| 8 | retro | `/retro` | `retro.md` + `.context/retros/*.json` | 基于真实 git 历史算指标；无远端时不做 stale 预检 | 无（终点）；行动项进下一轮 |

**跨环硬依赖（漏了会静默失效）**：
- 想 `/ship` 认 Eng Review → 必须先有 `/review` 或 `/plan-eng-review` 写出的 review-log，且 7 天内、status=clean（`[CC]ship\SKILL.md:921-925`）。
- 想 `/qa` 接上 test plan → 必须先有 `plan-eng-review` 产出的 `*-test-plan-*.md`（`[AUDIT]:109`）。
- 想 `/plan-*review` 自动找到设计文档 → 必须落在 `~/.gstack/projects/{slug}/` 且命名匹配 glob（`[AUDIT]:98`）。

---

## 8. 配套技能速查（不属八环，但会被八环调用或单独用）

| 技能 | 干什么 | 来源 |
|---|---|---|
| `/careful` | 危险命令（rm -rf / DROP TABLE / force-push）预警 | `[REPO]AGENTS.md:102` |
| `/freeze` | 把编辑锁在某一目录，**硬阻断**（PreToolUse 钩子，deny），`~/.gstack/*/freeze-dir.txt` 持久化 | `[CC]freeze\SKILL.md:23-90` |
| `/unfreeze` | 解除 freeze | `[CC]unfreeze\SKILL.md` |
| `/guard` | careful + freeze 一起开 | `[CC]guard\SKILL.md` |
| `/cso` | OWASP+STRIDE 安全审计；daily 8/10、comprehensive 2/10 | `[CC]cso\SKILL.md:29-30` |
| `/investigate` | 系统化根因排查（先查再改） | `[REPO]AGENTS.md:32` |
| `/codex` | 第二意见三模式（review / challenge / consult） | `[CC]codex\SKILL.md:812-940` |
| `/plan-tune` | 逐题调提问灵敏度 / 静音 | `[CC]spec\SKILL.md:681-692` |
| `/learn` | 管理跨会话 learnings | `[REPO]AGENTS.md:61` |
| `/health` | 代码质量看板 | `[REPO]AGENTS.md:63` |
| `/benchmark`、`/benchmark-models` | 性能回归 / 跨模型基准 | `[REPO]AGENTS.md:64-65` |
| `/browse`、`/open-gstack-browser` | 无头浏览器（qa 的地基） | `[REPO]SKILL.md:561-600` |
| `/context-save`、`/context-restore` | 存/恢复工作上下文 | `[REPO]AGENTS.md:59-60` |
| `/gstack-upgrade` | 升级 | `[REPO]gstack-upgrade\SKILL.md` |

注意 `freeze` 的边界含义是"防误改"不是安全边界——`sed` 之类 bash 命令照样能改外面（`[CC]freeze\SKILL.md` 末段）。

---

## 9. 明确"未确认"的清单（写教材时别把它们说成事实）

1. **`/qa` 有没有及格线**：v1.58 源码里只有 8 类加权公式和"比基线差就 WARN"，**没有** `≥X 才算过`。是否在新版本加了阈值——未确认。
2. **`GSTACK_SESSION_KIND` 在 Claude 宿主 1.58.3.0 是否被任何脚本消费**：`bin/gstack-session-kind` 不认；新版本（1.9x）才在步骤 0 认。中间版本（1.87.3.0）未逐字核对——未确认。
3. **opencode 宿主下 `gstack-claude-code` 外部评审能否真的跑通**：本机未实测（只读了它的渲染代码）。
4. **`/spec --execute` 在本机任何宿主下都不用过**：需要 `claude -p` + `git worktree`（`[CC]spec\SKILL.md:807`、`:1069-1080`；`[AUDIT]:122` 判定"OpenCode 下必然失败"），本机未实测。
5. **`plan-design-review` / `plan-devex-review` 的具体打分维度**：只读到"7 个维度""8 个 DX 维度"的清单要求（`[CC]autoplan\SKILL.md:1572-1597`），未逐条核对维度名。
6. **R1 四阶段评审的"外部评审均 unavailable"具体报错文本**：日志里是技能原文与模型自述混杂，我只采信了 `[R1]R1-八环讲解记录.md` 与 `[R1]R1-操作经验教训.md` 的整理结论，原始 stderr 未逐字定位。
7. **`claude-available.json` 是否还被别的组件读取**：只确认了生产者（`browse/src/terminal-agent.ts`），消费方（侧边栏 bootstrap 卡片）是注释描述的，未追到前端代码。
8. **`opencode run` 能否真的加载 gstack 技能并走完门禁**：只验证了 `run` 子命令存在（`opencode --help`），没有实跑。
9. **`codex exec review` 的输出是否满足 gstack 的 finding 分级契约**：只验证了子命令与 `--base/--uncommitted/--commit` 参数存在，没实跑。
10. **codex 可执行文件的当前哈希目录**：2026-10-20 实测为 `896a0166b774037a`，下次升级会变——脚本里必须动态发现，别抄这个值。

---

## 10. 一页话总结

- GStack 本体是**一堆 Markdown 技能 + 一个无头浏览器 + 一堆 `~/.gstack/` 状态脚本**，不是框架（`[REPO]ARCHITECTURE.md:7`）。
- 八环里**只有 7 环有技能**，第 4 环施工靠提示词；门禁的打分只在 spec（≥7）和 ship（覆盖率 60/80）是硬数字，其余是"记录在案"。
- 三宿主差异的核心不是命令写法，而是**AskUserQuestion 怎么落地**：Claude 原生、opencode 映射 `question`、codex 只能 prose。
- 最值钱的三个操作纪律：**prompt 写成文件**、**推理强度设 medium**、**不可用就写不可用**。
- 最危险的一件事：`spawned` 模式下模型会为跳不过的步骤编一个自洽的理由。

---

### 附：本文引用的关键源码位置（便于复核）

| 主题 | 文件:行 |
|---|---|
| 官方 7 段 sprint | `[REPO]README.md:171-175` |
| 技能全清单 | `[REPO]AGENTS.md:14-108` |
| spec 五阶段硬约束 | `[CC]spec\SKILL.md:818-910` |
| spec 质量门 ≥7 / 3 次上限 | `[CC]spec\SKILL.md:1040-1054` |
| spec 脱敏 fail-closed | `[CC]spec\SKILL.md:951-1002` |
| autoplan 串行 + 6 原则 | `[CC]autoplan\SKILL.md:886-982` |
| autoplan 两个不可自动的门 | `[CC]autoplan\SKILL.md:1816-1823` |
| review 打分公式 | `[CC]review\SKILL.md:1401-1404` |
| review AUTO-FIX/ASK | `[CC]review\SKILL.md:1500-1548` |
| qa Health Score 权重 | `[CC]qa\SKILL.md:1320-1355` |
| ship 停/不停清单 | `[CC]ship\SKILL.md:819-850` |
| ship 覆盖率门 | `[REPO]ship\sections\test-coverage.md:183-214` |
| ship 验证门（IRON LAW） | `[CC]ship\SKILL.md:1210-1228` |
| office-hours 设计文档契约 | `[CC]office-hours\sections\design-and-handoff.md:20-196` |
| cso 置信度门 | `[CC]cso\SKILL.md:784-787`、`:1035-1049` |
| 会话种类判定 | `[REPO]bin\gstack-session-kind:27-53`（旧）/ `[CX]gstack\bin\gstack-session-kind:40-76`（新） |
| 新版 preamble 与 AUQ 规则 | `[CX]gstack-spec\SKILL.md:14-85` |
| 新版"不可用≠通过"原文 | `[CX]gstack-spec\SKILL.md:804` |
| opencode AUQ 映射 | `[OC]gstack-spec\SKILL.md:21` |
