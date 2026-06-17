# finance-agent / AGENTS.md

## 1. 默认交流与执行风格

- 默认使用简体中文与用户交流，除非用户明确要求其他语言。
- 保留命令、代码、路径、环境变量、接口字段名的原文。
- 回答优先给结论、修改点、关键代码或验证结果；避免重复已说明的背景。
- 原因解释保持简短；不确定时明确说明，不编造不存在的文件、变量、接口或依赖。
- 默认遵循 Karpathy Guidelines：简单直接、外科手术式改动、能验证再扩大范围。
- Conversation Flow：先评估请求复杂度和风险，再决定是否需要 Plan/Spec、澄清或调用专项技能；不要机械化扩大流程。

## 2. 项目定位

这是一个本地可运行、可追溯、可复盘的金融分析系统，不是自动交易系统。

生产主链固定为：

```text
api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output
```

任何新增功能必须挂到这条主链路中，不要新增第二套任务主脑。

## 2.3 Hermes OS 生产级治理规范（v2.1）

### 2.3.1 系统基本原则

```text
原则 1：Single Decision Spine（单一决策中枢）
  → 只有 Core 进行决策（路由 + 规划 + 验收判定）

原则 2：Tool is Passive Executor（工具是被动执行体）
  → Tool / MCP 只能执行，不能参与决策

原则 3：Memory is Passive（记忆是被动系统）
  → Memory 不参与当前决策，只提供上下文参考

原则 4：Execution is Isolated（执行必须隔离）
  → 只有 Executor 可以真正执行工具调用
```

### 2.3.2 Core 控制规则

Core 是系统唯一允许执行以下操作的组件：

- 请求路由（routing）
- 任务规划（planning）
- 任务拆解（decomposition）
- 工具 / MCP 选择
- 验收标准判定

**Core 明确禁止：**

```text
❌ 直接执行工具
❌ 直接写入记忆（由 Memory System 处理）
❌ 修改 Skill 系统结构
```

### 2.3.3 Skill 系统（已降级为模板层）

Skill 定义：

```text
Skill = 无状态工作流模板（stateless workflow template）
```

Skill 仅允许做：
- 输入 → 输出执行流程建议
- 生成结构化步骤
- 提供方法模板

**Skill 禁止行为：**

```text
❌ 不允许参与路由决策
❌ 不允许调用工具
❌ 不允许访问记忆
❌ 不允许改变执行路径优先级
```

Skill Registry = 纯查询表（lookup table），不包含优先级、自动加载、权重系统。

### 2.3.4 Capability Layer（统一能力层，§4 补充说明）

统一调用接口：

```text
tool.call(name, input)
```

能力来源与作用：

| 类型 | 实例 | 作用 |
|------|------|------|
| Built-in Tools | terminal, file_ops, browser, exec_code, session | 原子执行能力 |
| MCP Servers | CodeGraph, Jin10, Lark | 外部能力提供者 |
| External APIs | search, github, docs | 外部信息查询 |

规则：

```text
MCP = 外部能力提供者
Tool = 原子执行能力
统一通过 Capability Layer 调用 → 禁止绕过统一接口直接调用
```

### 2.3.5 Execution Layer（执行层约束，§10 补充说明）

```text
Subagent = Pure Executor（纯执行器）
```

Subagent 允许：执行任务步骤、调用工具、返回结果。

**Subagent 禁止行为：**

```text
❌ 不允许规划任务
❌ 不允许路由决策
❌ 不允许写入记忆
❌ 不允许选择 Skill
```

### 2.3.6 执行隔离机制（安全边界）

```text
Core     → 只负责决策
Executor → 只负责执行
Tool     → 只负责动作
Memory   → 只负责存储
Skill    → 只负责模板
```

### 2.3.7 系统执行流程（单链路）

```text
用户输入
  ↓
Core（意图识别 + 路由）
  ↓
Planner（任务图生成）
  ↓
Executor（选择执行器 → Leaf Subagent）
  ↓
Capability Layer（工具 / MCP 统一调用）
  ↓
Memory 写入（如任务完成 / 状态变化 / 偏好更新）
  ↓
Output Filter（RTK → Caveman full）
  ↓
最终输出
```

### 2.3.8 CodeGraph 一级核心 MCP 规则

```text
CodeGraph = First-class MCP（一级核心 MCP）
```

允许用途：代码结构查询、依赖关系分析、调用链追踪、影响范围分析、符号级搜索。

**硬性规则：**

```text
❌ 在有 CodeGraph 可用的情况下，禁止 grep 全项目定位代码结构
  → 优先使用 codegraph_explore 替代 grep + 逐文件 read
```

### 2.3.9 系统稳定性强制约束

系统必须禁止以下行为：

```text
❌ 多个决策中枢并存
❌ Skill 参与路由决策
❌ Tool 参与规划逻辑
❌ Memory 驱动执行
❌ 隐式 Agent 层级结构（多级嵌套决策）
❌ 同一文件被多个 Agent 同时修改
❌ 不经 Core 审核的自动化任务链
```

### 2.3.10 系统设计目标

```text
Hermes OS v2.1 设计目标：

- 单一控制中枢（Core）—— 唯一决策入口
- 多执行器架构（Executor Pool）—— Leaf Subagent 并行
- 统一能力层（Capability Layer）—— MCP + Built-in 统一接口
- 图结构代码理解（CodeGraph）—— 替代 grep 探索
- 被动记忆系统（Memory Layer）—— 只存储，不决策
- 输出过滤后置（Output Filter）—— 不进入 reasoning 路径
```

### 2.3.11 Reasoning OS 增强规则（多层推理约束）

以下规则适用于需要多步推理的任务（金融分析、架构判断、多步调试）。不另建系统，不加额外 LLM 调用。

#### 推理阶段 Gate

复杂推理任务必须经过显式阶段门控，Core 在每个阶段输出结构化摘要：

```
UNDERSTAND → PLAN → EXECUTE → SELF_VERIFY → OUTPUT
```

- 没有 PLAN 不允许 EXECUTE
- EXECUTE 后必须 SELF_VERIFY
- VERIFY 不通过 → 回 EXECUTE（最多 2 个循环）
- SELF_VERIFY 不调额外模型，只做规则检查：步骤完整性、数值一致性、结论与输入是否冲突

#### Scratchpad 约定

复杂任务开始时，Core 在上下文注入中维护一个 scratchpad 块：

```
## Reasoning Scratchpad
- assumptions: [推理前提出的假设]
- plan: [Plan 阶段输出的步骤列表]
- steps_done: [已完成的步骤]
- tool_outputs: [工具调用结果摘要]
- pending: [待执行步骤]
- self_verify: pass / fail / retry_N
```

Scratchpad 仅在当前任务生命周期有效，任务完成后丢弃。不写入 Mem0、不写入 Obsidian。

#### Tool 调用约束

- 工具只在 EXECUTE 阶段调用，不在 PLAN 或 SELF_VERIFY 阶段调用
- 每次工具输出必须记录到 scratchpad.tool_outputs
- 工具调用链单任务不超过 10 步（防循环失控）

---

## 3. 当前阶段

当前默认阶段是 MVP：

- 官方宏观数据采集。
- CME 官方 Daily Bulletin PDF 下载解析。
- 宏观指标和期权墙计算。
- Markdown 报告和策略卡片。
- 最小 Dashboard。
- 任务日志、失败原因、重试。

暂不做：

- 自动交易下单。
- 多 Agent 生产主脑。
- Prefect Server。
- LangGraph 接管 worker。
- 大规模 ClickHouse。
- 全自动多站点 VIP 登录态。
- 复杂权限系统。

## 4. 架构边界

可以做：

- 补 `collectors`、`parsers`、`features`、`analysis`、`renderer`。
- 补 `api` 只读接口。
- 补 `dashboard` 只读页面。
- 补测试、迁移、脚本、文档。
- 补 CME、FRED、Fed、Treasury 主链。

禁止做：

- 不要让前端自己计算策略。
- 不要让 Agent 直接改原始数据。
- 不要绕过 `task_runs` 和 `task_steps`。
- 不要覆盖历史报告。
- 不要为了重构破坏当前可运行链路。

## 4.1 前端入口规则

当前前端只保留一套主线：

- `apps/frontend-web/src`：一级主线。所有新页面、新组件、新报告展示和 API 对接默认只允许修改这里。
- `apps/frontend-web/`：Vite + React 18 正式前端工程。配置、构建脚本和静态资源仅在服务当前主线时修改。
- `apps/frontend/`：已删除的旧 Next.js 前端，不允许恢复为新需求入口。
- `apps/frontend-web/dashboard.html`：已删除的早期 FastAPI 直出 HTML，不允许恢复或新增能力。

除非用户明确说明兼容修复，否则前端开发不得修改、重建或新增第二套入口。FastAPI `/dashboard` 仅作为兼容跳转，真实页面以 Vite `/dashboard` 为准。

## 5. 数据原则

- `raw`、`parsed`、`features`、`outputs` 分层不能混。
- 原始 API 响应和 PDF 文件必须归档。
- 每个 AI 分析结果必须绑定 `input_snapshot_ids` 和 `source_refs`。
- 缺失数据必须显式标记，不允许补造。
- 手工上传仅作为兜底，不作为 MVP 主流程。

## 6. 代码修改与检索原则

- 修改代码前先概述计划。
- 涉及多个文件时先说明影响范围和验证方式。
- 优先最小改动。
- 优先修复现有链路，而不是重写。
- 不做无关重构。
- 保持现有项目风格，不引入不必要依赖，不改变无关逻辑。
- 优先输出 diff 摘要或关键片段，不整篇重写文件内容。
- 多文件修改按文件路径逐个说明，并标注兼容性风险。
- routes 保持轻逻辑，业务逻辑放到 services/repositories。
- parser 改动必须补样本或回归测试。

### 6.1 精准检索与批量操作

- **优先使用 CodeGraph 定位代码结构**：在已初始化 CodeGraph 的项目中，代码结构探索（符号定位、调用链、依赖关系）优先使用 `codegraph_explore` / `codegraph_search` / `codegraph_callers`，替代全项目 grep + 逐文件 read。
- 禁止为定位问题直接全文遍历项目；先用 CodeGraph 或 `rg` / `git grep` 精准定位影响范围，再读取必要文件。
- 检索和批量操作默认排除 `node_modules`、`.git`、`dist`、`build`、`.venv`、缓存和生成物目录。
- 批量修改前必须先用命令定位影响范围；批量替换前先给匹配结果摘要。
- 影响范围较大时，先给文件清单、修改计划和风险点，再动手。

### 6.2 Plan / Spec 与方案沉淀

- 复杂任务（多文件修改、架构调整、新功能、迁移、批量替换）必须先输出 Plan/Spec。
- Plan 至少包含：目标、理解、待确认问题、方案对比、影响范围、风险点、验证方式。
- 存在多种方案或需求不明确时，先暂停提问，不用猜测推进。
- 整体方案确定后，必须沉淀到 Obsidian vault：`/home/zxx/wiki/Finance-Agent-Knowledge-Vault`，优先更新 `02-项目/金融分析系统/04-开发路线图.md`、`06-任务看板.md`、`07-开发日志/YYYY-MM-DD.md`；涉及架构决策时新建 `03-架构/ADR/ADR-YYYYMMDD-标题.md`。
- Obsidian 执行方案需包含目标、方案、技术栈、目录结构、模块拆分、TODO、风险点、验证方式。
- 后续执行同一方案时优先读取并更新对应 Obsidian 页面，禁止只依赖聊天上下文。
- 仅修正文案、单文件小改、格式调整、规则文件自身维护等低风险任务，可不新建 Obsidian 执行方案，但仍需说明范围和验证方式。
- 复杂任务优先使用 `writing-plans` 技能输出标准化 Plan；若不可用则按上述格式手写。

### 6.3 安全与编码行为

- 输入一律视为不可信；涉及路径、命令、外部参数、上传内容时优先使用白名单和结构化 API。
- 禁止拼接高风险 shell；需要 shell 时保持参数清晰、范围明确，避免隐式通配和不可控输入。
- 先思考再编码，只做当前任务所需的外科手术式修改。
- 不隐瞒不确定性；发现规则冲突、上下文缺失或验证失败时直接说明。
- 业务脚本开发需参考知识库文档：`精品模型字段知识库.md`、`manual_kpi_kb.md`（若相关且存在）。

### 6.4 Skill 协同路由

根据任务风险选择最小必要的 skill 组合；不要为了流程而流程化，但复杂任务必须让 skill 输出约束实际行动。

| 场景 | 推荐 skill 组合 | 触发条件 |
|------|----------------|----------|
| 黄金日报 / 宏观分析 | **`gold-daily-analysis`** → `macro-pipeline` → `macro-snapshot-check` → `cme-options-analysis` → `finance-agent-report-artifact-qa` | 用户要求黄金日报、今日分析、市场状况、做单环境 |
| CME 期权墙分析 | **`cme-options-analysis`** → `cme-bulletin-debug` → `cme-gold-parser-regression` → `finance-agent-report-artifact-qa` | 涉及 CME/COMEX 期权、Gamma/GEX、Call/Put Wall |
| 前端页面重构 | **`frontend-page-refactor`** → `finance-agent-frontend-dev` → `finance-agent-frontend-design-qa` → `finance-agent-live-acceptance` | 页面太乱、模块太多、子页拆分、布局调整 |
| 多文件 / 多阶段开发 | `finance-agent-planning-with-files` -> `repo-map` -> `incremental-implementation` -> `git-workflow-and-versioning` | 需要 Plan/Spec、跨会话、跨模块或需要分块提交 |
| 架构 / API / 数据边界调整 | `finance-agent-grill-with-docs` -> `api-and-interface-design` / `sqlalchemy-db-models` -> `documentation-and-adrs` | 可能影响主链、接口契约、数据层或 Agent 边界 |
| 前端页面 / Dashboard 验收 | `finance-agent-frontend-dev` -> `finance-agent-frontend-design-qa` -> `finance-agent-frontend-visual-polish` -> `frontend-ui-engineering` -> `finance-agent-browser-trace` -> `finance-agent-live-acceptance` | 修改 `apps/frontend-web/src` 或用户反馈页面不可访问/不可用 |
| 报告 / Jin10 / CME / 宏观产物 | `finance-agent-analysis-pipelines` -> 对应项目 skill（`cme-*` / `macro-*`）-> `finance-agent-report-artifact-qa` -> `vault-sync-guard` | 涉及 collector/parser/features/analysis/renderer/output |
| Agent 管理 / Prompt Governance | `finance-agent-agent-governance` -> `security-threat-model` -> `security-best-practices` -> `finance-agent-grill-with-docs` | 涉及 Agent 输出、prompt、反馈、注册表或权限边界 |
| 一次性脚本固化 | `finance-agent-script-hardening` -> `cli-creator`（若已安装）-> `test-driven-development` -> `release-checklist` | 临时脚本要进入 `scripts/` 或成为可复用入口 |
| 全链路验收 / 提交前验收 | `finance-agent-live-acceptance` -> `finance-agent-report-artifact-qa`（若涉及报告）-> `release-checklist` -> `git-workflow-and-versioning` | 用户要求实测、验收、整理提交或分块提交 |

- `finance-agent-planning-with-files` 用于把计划绑定到真实文件清单、API、artifact 和验证命令；临时计划写入 `.codex/plans/<日期>-<slug>/`，长期状态仍按第 8 节写入 Obsidian。
- `finance-agent-frontend-design-qa` 用于前端设计和页面 QA；优先按当前 React/Vite、设计 token、真实数据状态和浏览器证据执行，不直接套用 Vue/Nuxt 社区 skill。
- `finance-agent-frontend-visual-polish` 用于前端排版、视觉层级、typography、spacing、组件状态和美化验收；优先保持金融工作台的低噪声、高密度、可扫描风格。
- `finance-agent-browser-trace` 用于前端验收；页面能打开不等于验收通过，必须补充 API、console、network、DOM 或截图证据。
- `finance-agent-grill-with-docs` 用于复杂改动前的反向质询；优先用 `AGENTS.md`、Obsidian、源码和真实 artifact 回答问题，只有本地事实无法判断时才问用户。
- `finance-agent-live-acceptance` 用于统一 API、Vite 页面、browser evidence 和 artifact 验收证据。
- `finance-agent-report-artifact-qa` 用于检查 Jin10/CME/宏观报告产物的 Markdown/JSON、图片引用、`source_refs`、summary 和数据层边界。
- `finance-agent-agent-governance` 用于 Agent 管理、prompt governance、Agent 输出和只读边界检查。
- `finance-agent-script-hardening` 用于把一次性脚本固化为参数化、可 dry-run、可验证的项目脚本；不合格脚本不提交。
- 若某个推荐 skill 尚未安装或未在当前会话加载，继续使用同等检查清单手工执行，不得因此跳过验收。

### 6.5 防止 Skill 上下文过载

Skill 使用以"防止上下文过载"为优先目标：默认仅启用完成当前任务所需的最小 skill 集；其余 skill 即使可见，也不得因已安装而自动视为默认启用，只有在任务类型明确命中时才按需加载。

**硬性约束：单次会话同时激活的 skill 总数 ≤ 15。** 超出时必须先卸载非当前任务域的 skill 再加载新 skill，优先保留常开集。

默认常开仅保留以下几类（≤ 10 skills）：

- 工程流程与收口：`git-workflow-and-versioning`、`incremental-implementation`
- 仓库理解与约束核对：`finance-agent-grill-with-docs`
- 测试与质量：`test-driven-development`、`code-review-and-quality`
- 后端接口与数据模型：`api-and-interface-design`、`sqlalchemy-db-models`

以下 skill 保留安装，但仅在对应任务场景下启用，不作为默认常开集：

- 前端开发/联调：`finance-agent-frontend-dev`、`frontend-ui-engineering`、`frontend-api-integration-patterns`、`react-best-practices`
- 前端设计/视觉：`frontend-design`、`finance-agent-frontend-design-qa`、`finance-agent-frontend-visual-polish`
- 浏览器验收/自动化：`finance-agent-browser-trace`、`playwright`、`browser-testing-with-devtools`、`webapp-testing`
- 报告/解析/宏观/CME：`finance-agent-analysis-pipelines`、`finance-agent-report-artifact-qa`、`macro-pipeline`、`macro-snapshot-check`、`cme-bulletin-debug`、`cme-gold-parser-regression`、`premarket-smoke-test`、**`gold-daily-analysis`**、**`cme-options-analysis`**
- 前端设计/重构：**`frontend-page-refactor`**、`frontend-ui-engineering`、`finance-agent-frontend-design-qa`、`finance-agent-frontend-visual-polish`
- 提交前验收：`finance-agent-live-acceptance`、`release-checklist`
- Agent 治理/安全：`finance-agent-agent-governance`、`security-threat-model`、`security-best-practices`
- 深度调试：`python-debugpy`、`systematic-debugging`
- 复杂任务规划：`writing-plans`、`planning-and-task-breakdown`、`finance-agent-planning-with-files`
- Obsidian / 知识沉淀：`obsidian-bases`、`obsidian-cli`、`obsidian-markdown`

以下类型默认不应进入当前任务上下文，除非用户明确提出或任务直接需要：

- 演示文档与办公类：`pptx`、`docx`、`xlsx`、`internal-comms`
- 泛设计与创意类：`canvas-design`、`brand-guidelines`、`theme-factory`、`algorithmic-art`
- 通用写作或与当前代码任务无关的工具类：`doc-coauthoring`、`json-canvas`、`web-artifacts-builder`、`idea-refine`、`interview-me`
- skill/插件创作类：`skill-creator`

存在重复能力时，只保留一套主用入口，避免上下文重复注入：

- code review 默认保留 `code-review-and-quality`，不默认启用 `code-reviewer`
- debugging 默认保留 `systematic-debugging`，不默认启用 `superpowers:systematic-debugging`
- TDD 默认保留 `test-driven-development`，不默认启用 `superpowers:test-driven-development`

执行原则：

- 非前端任务不启用前端/视觉/浏览器类 skill。
- 非报告/解析/宏观/CME 任务不启用对应领域 skill。
- 非验收/提交流程不启用 live acceptance / release checklist。
- 非复杂多文件任务不启用 planning 类 skill。
- 非知识沉淀任务不启用 Obsidian 类 skill。
- 若某 skill 与当前任务无直接关系，即使已安装，也不得主动读取其 `SKILL.md` 或将其规则注入当前上下文。
- **Skill 是模板库，提供执行流程；Skill 不参与路由决策、不做优先级排序、不判定验收标准。**

## 7. 命令约定

### Python / uv 环境

本项目 Python 依赖由 `uv` 管理，项目根固定 `.python-version = 3.11`，本地虚拟环境为 `.venv/`。

- 跑项目 Python 代码必须使用：`uv run python ...`，或明确使用 `.venv/bin/python`。
- 不要用裸 `python3 ...` 跑项目模块或脚本；系统 Python 不一定有 `pydantic`、`mem0ai` 等项目依赖。
- 更新 Mem0 项目主线记忆时使用固定入口，不要临时写脚本：

```bash
uv run python scripts/mem0_add_project_memory.py --memory-type frontend_direction --content '...' --verify-query '...'
```

必须优先使用 `rtk` 执行外部命令以减少输出：

```bash
# Git
rtk git status --short
rtk git diff
rtk git log --oneline -10

# Python 测试 / 代码检查
rtk pytest -q
rtk pytest tests/parsers/cme/ -q
rtk ruff check .
rtk ruff format --check .

# 前端构建 / 测试 / 检查
rtk npm test
rtk npm run build
rtk vitest run
rtk tsc --noEmit
rtk lint

# 文件浏览 / 搜索
rtk ls -la
rtk tree -L 2
rtk find . -name "*.py" -type f
rtk grep -r "pattern" --include="*.py"

# 其他
rtk json <file.json>          # 紧凑 JSON 输出
rtk err -- <command>          # 只显示错误/警告
rtk diff <file1> <file2>      # 超紧凑 diff
rtk summary -- <command>      # 运行命令并显示摘要
```

Shell 内建命令、环境变量修改、会话状态使用原生 bash：

```bash
export PATH="$PATH:/home/zxx/.local/bin"
echo $DATABASE_URL
```

不要用 `rtk` 包装 shell 内建命令（如 `rtk export`、`rtk cd`）。

### 7.1 执行 Agent / Mem0 默认规则

- 在 `/home/zxx/workspace/finance-agent` 执行非平凡开发任务前，先读取本文件，并预取项目记忆：

```bash
rtk uv run python scripts/mem0_prefetch_context.py "<task>"
```

- 若命令提示任务未命中检索条件，则继续正常执行；若因 `MEM0_API_KEY` 缺失失败，报告失败并继续，不编造上下文。
- 若上游上下文已注入 `## Mem0 Context`，执行 Agent 不需要重复查询 Mem0。
- 模型策略：简单任务（单文件修改、格式调整）使用轻量模型；复杂推理、架构判断或困难调试使用强推理模型。
- localhost smoke test 或长任务前保留小写：

```bash
export no_proxy=127.0.0.1,localhost,::1
```

- 执行 Agent 任务派发需以真实执行输出、diff、日志或测试结果为准；仅输入框文本或 tmux 注入不算完成。

## 8. Obsidian / 长期记录约定

### 8.1 基本规则

- Obsidian vault 固定为：`/home/zxx/wiki/Finance-Agent-Knowledge-Vault`。
- repo 内 `hermes/` 只保留**当前可执行状态和临时计划**；所有长期规划、架构决策、版本记录、复盘沉淀一律写入 vault。
- Obsidian 是完整文档权威源；Mem0 只存摘要和约束。若 Mem0、聊天记录、旧计划或 repo 侧快照与 Obsidian 当前入口冲突，以 Obsidian 当前入口为准。
- 不要重新创建旧英文目录，如 `02-Projects`、`03-Architecture`、`04-Data-Sources`、`06-Agent-Workflows`、`_system`、`_templates`。
- 不要为同一类状态新增第二入口；新增或维护文档前先检查本节路由，能追加或覆盖现有入口就不要新建平行页面。

### 8.2 唯一跟踪入口

后续维护按“一类信息一个入口”执行：

| 信息类型 | 唯一维护页 | 规则 |
|---------|------------|------|
| 项目首页 / 常用入口 | `02-项目/金融分析系统/00-首页.md` | 只放定位、核心链路、唯一跟踪入口和稳定参考入口 |
| 当前进度 | `02-项目/金融分析系统/02-当前进度.md` | 覆盖更新，只写当前事实、已完成、下一步 |
| 当前任务 | `02-项目/金融分析系统/06-任务看板.md` | 覆盖更新，只写 Now / Done / Later，不写长方案 |
| 开发路线图 | `02-项目/金融分析系统/04-开发路线图.md` | 覆盖更新，只写阶段和方向，不写每日执行细节 |
| 版本/变更记录 | `02-项目/金融分析系统/09-版本记录.md` | 完成一个切片后追加，必须带验证结果 |
| 风险与卡点 | `02-项目/金融分析系统/08-风险与卡点.md` | 覆盖更新，只保留仍会影响后续执行的问题 |
| 知识库整理规则 | `02-项目/金融分析系统/29-知识库整理与归档清单.md` | 覆盖更新，记录目录精简、归档、合并和删除口径 |
| 架构事实 | `03-架构/总体架构.md`、`03-架构/前端页面架构.md`、`03-架构/后端服务架构.md`、`03-架构/任务调度架构.md`、`03-架构/Agent架构.md` | 覆盖更新，只写稳定边界和当前接口，不写临时任务 |
| 每日过程 | `07-开发日志/YYYY-MM-DD.md` | 新建或追加，只记录当天流水和验收，不作为下一步入口 |

禁止把“下一步 / 当前剩余 / 待执行”继续写入旧计划页、源文档页、模块页或每日日志。旧计划如需保留，只在页首标注 `superseded`、`archived`、`source-only`、`legacy` 或 `partial-current`，并指向上表入口。

### 8.3 目录路由

完成改动后，按内容类型写入对应路径：

| 内容类型 | 目标路径 | 写入方式 |
|---------|---------|---------|
| 版本/变更记录 | `02-项目/金融分析系统/09-版本记录.md` | **追加** |
| 当前进度 | `02-项目/金融分析系统/02-当前进度.md` | 覆盖更新 |
| 开发路线图 | `02-项目/金融分析系统/04-开发路线图.md` | 覆盖更新 |
| 任务看板 | `02-项目/金融分析系统/06-任务看板.md` | 覆盖更新 |
| 风险与卡点 | `02-项目/金融分析系统/08-风险与卡点.md` | 覆盖更新 |
| 架构决策（ADR） | `03-架构/ADR/ADR-YYYYMMDD-标题.md` | 新建 |
| 总体架构说明 | `03-架构/总体架构.md` | 覆盖更新 |
| 数据源说明 | `04-数据源/00-数据源总览.md` | 覆盖更新 |
| Agent 工作流 | `06-智能体工作流/00-Agent工作流总览.md` | 覆盖更新 |
| 每日开发日志 | `07-开发日志/YYYY-MM-DD.md` | 新建 |
| 复盘记录 | `10-复盘与优化/YYYY-MM-DD-标题.md` | 新建 |

### 8.4 写入时机

以下情况**必须**写入 vault：

- 完成一个 Phase 或 Task 组（如 P5 架构优化）→ 写版本记录 + 若有架构决策则写 ADR
- 修改了主链架构或模块边界 → 写 ADR
- 发现并解决重要风险/卡点 → 更新风险与卡点页
- 每周或里程碑节点 → 更新当前进度页

### 8.5 写入格式

**版本记录**（追加到 `09-版本记录.md`）：

```markdown
## YYYY-MM-DD - 变更标题

- 类型：feature / fix / arch / refactor / docs
- 范围：[受影响模块]
- 变更：
  - [具体做了什么]
- 验证：[通过的测试/验证命令]
- 影响：[对主链/API/前端的影响]
- 后续：[遗留问题或下一步]
```

**ADR**（新建 `03-架构/ADR/ADR-YYYYMMDD-标题.md`）：

```markdown
---
tags: [ADR, 架构决策]
date: YYYY-MM-DD
status: accepted
---

# ADR-YYYYMMDD：标题

## 背景
## 决策
## 理由
## 影响
## 状态
```

### 8.6 写入命令

优先用 `obsidian` CLI（需桌面端已打开）：

```bash
obsidian append vault="Finance-Agent-Knowledge-Vault" path="02-项目/金融分析系统/09-版本记录.md" content="..."
```

CLI 不可用时直接操作文件系统：

```bash
cat >> "/home/zxx/wiki/Finance-Agent-Knowledge-Vault/02-项目/金融分析系统/09-版本记录.md" << 'EOF'
...内容...
EOF
```

**禁止**写入 `storage/`、`hermes/staging/`、`模板/`、`系统/` 目录，禁止在 vault 存放 `.py`/`.ts` 代码文件。

### 8.7 归档与删除口径

- 旧计划、源文档和历史方案默认只做软归档，不直接删除；重点规划文档先保留，再通过页首状态说明当前是否仍可执行。
- `status: archived` 表示不再参与当前决策；`status: superseded` 表示已被新文档替代；`status: source-only` 表示只能查历史；`status: legacy` 表示模板或骨架保留但不主动使用。
- 可以物理删除的仅限空 README、明确占位且无链接引用的页面、重复导入且内容已被新页完全覆盖的原始文件。
- 删除前必须先查反链或文本引用，确认没有入口页引用；不确定时先软归档。
- 不要重新按前端、后端、解析器、WSL、问题排查等主题拆分开发日志；日常过程统一写入 `07-开发日志/YYYY-MM-DD.md`。

## 9. 验收原则

按改动范围选择验证：

- API：跑 API tests 和 `/health`。
- worker/pipeline：跑 smoke test。
- collector：保存 raw 样本并跑采集测试。
- parser：跑 fixture regression。
- features：跑公式和边界测试。
- renderer/output：检查 Markdown/JSON 非空和字段完整。
- dashboard：打开页面检查只读 API 是否可消费。

完成前必须说明：

- 改了哪些文件。
- 跑了哪些验证。
- 哪些验证没跑，原因是什么。
- 声称「完成/修复/通过」前，优先使用 `verification-before-completion` 技能运行验证命令并确认输出。

## 10. Agent 行为准则

### 10.1 通用三层 Agent 模型（v2 收敛约束）

- **主控 Agent（Core）**：唯一的决策中枢。负责目标定义、架构决策、优先级排序、风险控制、任务派发和最终验收。决不允许 Subagent 或 Skill 替代 Core 做出决策。
- **调度 Agent（Planner）**：纯执行规划。负责读取长文档/代码/日志、压缩上下文、拆解任务、生成子任务包。不得绕过主控自行扩大范围、长期循环调度、合并结果或判定最终验收。
- **执行 Agent（Subagent）**：纯代码执行/命令运行/测试验证。**只执行，不决策。** 每次只处理边界清晰、互不冲突的单个任务包。Subagent 不参与路由、不自行判断完成标准、不做跨任务推理。

### 10.2 任务包规范

执行 Agent 任务包必须写清：任务目标、允许修改范围、禁止修改范围、输入文件、输出要求、验收标准、执行后报告格式。Subagent 必须返回可验证的事实（diff、日志、测试输出），不得只返回文字结论。

### 10.3 delegate_task 子 Agent 调度（v2 约束）

- 子 Agent 角色强制为 `leaf`（纯执行），不允许 `orchestrator` 角色嵌套决策。
- 使用 `delegate_task` 派发独立子任务。默认创建独立上下文的新会话。
- 独立子任务可并行派发，默认上限 3 个并发；多 Agent 不得同时修改同一文件或同一 migration。
- 收到子 Agent 完成通知后，先读摘要行；摘要不足时用 `agent_eval` 拉详细投影；失败时评估是否阻塞主链路。
- **子 Agent 报告为自述信息，其声称的文件修改、命令执行、测试结果等副作用需主控二次验证后才可作为事实采纳。**
- 子 Agent 输出固定由 Caveman full 压缩后返回主控。

### 10.4 通用约束

- 多 Agent 不得同时改同一文件或同一 migration。
- 任何影响主链的大改必须先说明风险和回滚方式。
- Kanban 拆任务时遵循：主控定方向 -> 调度 Agent 读上下文并拟任务包 -> 主控审核/派发 -> 执行 Agent 执行 -> 主控验收/合并。

---

## 11. Output Layer（输出分层）

输出处理仅在后处理阶段执行，不进入 reasoning 路径。

### 11.1 分层顺序

```
Raw Response → RTK（CLI 输出压缩，60-90%）→ Caveman full（自然语言压缩，~75%）→ Final Response
```

### 11.2 硬性约束

- Caveman full 模式在**达到用户 token 阈值或推理深度需求**时才启用；纯指令/代码任务不强制。
- RTK 默认用于 `terminal` 和 CLI 工具输出；`read_file`、`search_files` 等已内置压缩的工具不额外过 RTK。
- 输出层不修改代码、不修改数据、不改变工具调用参数。
- Caveman 压缩不得压缩以下内容：代码块、CLI 命令、路径、API 名、错误信息、函数签名。

---

## 12. Memory Layer（记忆分层，v2 收敛）

### 12.1 两层架构

```
Layer 1: Session Memory（运行时状态）
  - session_search 工具：跨会话事实查询
  - memory 工具：当前会话持久标记
  - 作用域：当前和关联会话的上下文注入

Layer 2: Mem0（长期语义记忆）
  - mem0_search / mem0_conclude
  - 存储偏好、约定、环境事实、经验教训
  - 注入每个 turn 的系统上下文

Obsidian Vault（外部知识归档）
  - 路径：/home/zxx/wiki/Finance-Agent-Knowledge-Vault
  - 用途：计划沉淀、ADR、版本记录、开发日志
  - **不参与 runtime decision** — Obsidian 不是查询层，不是路由输入
```

### 12.2 硬性约束

- Mem0 存储摘要和约束，不存储完整方案或代码。
- 若 Mem0、聊天上下文、Obsidian 入口冲突 → 以 Obsidian 为准（仅限非 runtime 决策）。
- 禁止在 memory 工具中存储任务进度或临时 TODO 状态（用 session_search 查）。
- Obsidian 写入规则见 §8，不在此重复。
