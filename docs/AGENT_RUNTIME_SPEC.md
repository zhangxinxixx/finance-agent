# Agent Runtime Spec

## 目标

定义 finance-agent 中 Agent 系统的角色边界、任务流转、安全约束和执行纪律。本文档是 `AGENTS.md` 中 Agent 行为准则的正式展开。

## 系统架构

```text
                          ┌─────────────────┐
                          │   用户请求/飞书    │
                          └────────┬────────┘
                                   ▼
                          ┌─────────────────┐
                          │  Hermes Agent   │ ← 任务识别、路由、复核、沉淀
                          │  (主控/编排)      │
                          └───┬──────┬──────┘
                    ┌─────────┘      └─────────┐
                    ▼                          ▼
          ┌─────────────────┐        ┌─────────────────┐
          │   Codex CLI     │        │  Analysis Agent │
          │   (代码执行)      │        │  (分析执行)      │
          └────────┬────────┘        └────────┬────────┘
                   │                          │
     ┌─────────────┼─────────────┐   ┌────────┼────────┐
     ▼             ▼             ▼   ▼        ▼        ▼
  Collector    Parser     Frontend  Macro   Options  Risk
  (数据采集)   (解析)    (前端页面)  (宏观)  (期权)  (风险)
                   │                          │
                   └──────────┬───────────────┘
                              ▼
                     ┌─────────────────┐
                     │ Report Renderer │
                     │ (报告生成)       │
                     └─────────────────┘
```

## 角色定义

### 1. Hermes Agent（主控 / 编排器）

**负责**：
- 识别任务类型（代码任务 vs 分析任务 vs 采集任务）
- 加载项目上下文（AGENTS.md、Skill、Mem0、Obsidian）
- 选择领域 Skill 和工作流
- 拆解复杂任务为可执行步骤
- 派发代码任务给 Codex，分析任务给 Agent
- 复核输出质量（是否满足业务目标）
- 沉淀关键结论到 Obsidian / Mem0

**不负责**：
- 直接大规模修改代码 → 交给 Codex
- 直接调用 LLM 做分析 → 交给 Analysis Agent
- 直接采集外部数据 → 交给 Collector
- 执行真实交易订单 → 永远禁止

**输出格式**：
```text
1. 任务识别：代码 / 分析 / 采集
2. Skill 匹配：gold-daily-analysis / cme-options-analysis / frontend-page-refactor
3. 执行计划：步骤 1 → 步骤 2 → 步骤 3
4. 派发：Codex Task Brief 或 Agent Input
5. 复核：检查输出是否满足验收标准
6. 总结：changed files / key findings / next steps
```

### 2. Codex CLI（代码执行器）

**负责**：
- 读取代码文件
- 定位调用链
- 最小 diff 修改
- 运行 lint / test / build
- 输出 diff 摘要

**不负责**：
- 判断交易方向
- 编造数据源
- 跳过验证直接声称完成
- 读取密钥、token、cookie
- 安装新依赖（除非明确授权）

**执行纪律**（Fable5 三段式）：
```
1. view（读文件、定位唯一片段）
2. patch（小步替换，不做整文件重写）
3. verify（lint / test / build，失败则回退）
```

**验证闭环**：
- 前端修改 → `npm run lint` + `npm run build`
- 后端修改 → `pytest` 或至少启动 check
- SQL 修改 → 说明方言差异 + 字段口径

### 3. Collectors（数据采集器）

**负责**：
- 抓取官方数据（FRED、Treasury、Fed、CME、BEA、BLS、EIA）
- 下载 PDF/CSV
- 接收 webhook（金十、飞书）
- 保存 raw data 到 `storage/raw/`
- 记录采集时间和 source_refs

**不负责**：
- 数据解析 → 交给 Parser
- 指标计算 → 交给 Features
- 直接输出报告结论

### 4. Parsers（解析器）

**负责**：
- PDF 文本/表格提取
- OCR 图片识别
- HTML/Markdown 解析
- 字段归一化

**不负责**：
- 编造缺失字段
- 对解析结果做业务判断

### 5. Analysis Agents（分析代理）

分析代理只做 **只读推断**，不直接修改数据。

| Agent | 模块 | 触发条件 | 输出 |
|-------|------|----------|------|
| `macro_liquidity_agent` | macro | 宏观 / 利率 / 流动性 | AgentOutput + market_phase |
| `cme_options_agent` | options | CME / Gamma / GEX | AgentOutput + wall 数据 |
| `risk_agent` | risk | 风险 / 波动 | AgentOutput |
| `market_odds_agent` | market | 方向概率 | AgentOutput |
| `synthesis_agent` | synthesis | 最终汇总 | 合成结论 |
| `jin10_report_analysis_agent` | jin10 | 金十日报 | LLM 分析输出 |
| `fact_review_agent` | fact_review | 事实核查 | 规则检查结果 |

**分析代理的读写边界**：

| 操作 | 允许 | 说明 |
|------|------|------|
| 读取 snapshot / raw / parsed 数据 | ✅ | |
| 计算指标（实际利率、Gamma 等） | ✅ | 确定性计算 |
| 写入 AgentOutput | ✅ | 到 DB / 文件 |
| 修原始数据 | ❌ | |
| 直接下单 | ❌ | |
| 编造缺失数据 | ❌ | |

### 6. Report Renderer（报告生成器）

**负责**：
- Markdown 报告生成
- HTML 可视化
- Excel 导出
- 报告溯源节生成
- Obsidian / 飞书同步

**不负责**：
- 分析推断 → 交给 Analysis Agent
- 覆盖历史报告
- 去掉上游 source_refs

## 任务流转标准

### 标准任务链

```text
用户请求
  → Intent Router（识别任务类型）
  → Context Loader（加载 AGENTS.md / Skill / Mem0 / Obsidian）
  → Skill Router（匹配 domain skill）
  → Task Planner（拆解步骤）
  → Executor（Codex / Agent / Collector）
  → Verifier（lint / test / artifact check）
  → Report Generator
  → Trace Recorder
  → Memory Writer（Obsidian / Mem0）
```

### 任务分类与派发

| 任务类型 | 派发目标 | 输入格式 | 输出格式 |
|----------|----------|----------|----------|
| 代码修改 | Codex | `Codex Task Brief` | diff + test result |
| 黄金日报 | gold-daily-analysis → macro + options + renderer | snapshot | report.md + trace |
| CME 期权 | cme-options-analysis | PDF path | AgentOutput + wall.json |
| 前端重构 | frontend-page-refactor → Codex | 页面路径 + 需求 | diff + build |
| SQL 修复 | sql-dialect-migration → Codex | SQL + 方言 | 改写 SQL + 说明 |
| 数据采集 | Collector | source config | raw data + source_refs |
| 报告生成 | Renderer | analysis outputs | report.md + trace.json |

### Codex Task Brief 格式

派发给 Codex 的任务必须结构化为：

```markdown
# Codex Task Brief

## 任务目标
[一句话描述要做什么]

## 背景
[为什么需要这个改动，用户想要什么效果]

## 相关文件
- `path/to/file1.py` [用途]
- `path/to/file2.tsx` [用途]

## 修改要求
1. [具体修改点 1]
2. [具体修改点 2]

## 约束
- 不引入新依赖
- 不改后端 API 签名（除非明确说明）
- 不删除被其他页面引用的组件

## 验收标准
- [ ] 测试通过
- [ ] build 通过
- [ ] [具体功能验证点]

## 禁止
- [禁止事项]
```

## 安全边界（强制）

### 文件系统权限

| 目录 | 权限 | 说明 |
|------|------|------|
| `storage/raw/` | 只读 | 原始数据归档 |
| `storage/parsed/` | 只读 | 解析后数据 |
| `storage/features/` | 只读 | 特征快照 |
| `storage/outputs/` | 可写 | 报告产物 |
| `tests/fixtures/` | 只读 | 测试样本 |
| `scripts/` | 可执行 | 运维脚本 |
| `.env` / 密钥 / token | 禁止 | 安全敏感 |
| 浏览器 cookie / 登录态 | 禁止 | 隐私敏感 |

### 网络权限

| 目标 | 权限 | 说明 |
|------|------|------|
| FRED / Treasury / Fed API | 只读 GET | 官方数据 |
| CME Group | 只读 GET | PDF 下载 |
| Jin10 API | 只读 GET | 行情/快讯 |
| OpenBB / yfinance | 只读 GET | 市场数据 |
| 本地 PostgreSQL | 读写 | 应用数据 |
| 本地 Redis | 读写 | 缓存/队列 |
| 真实交易接口 | 禁止 | MT5/Bybit 等 |
| 第三方登录态站点 | 禁止 | VIP 付费内容抓取 |

### 交易权限分层（防御性）

```text
分析 Agent：只读行情和报告                          ← 当前阶段
策略 Agent：只输出策略卡片，不执行                    ← 当前阶段
模拟盘 Agent：可执行，但需要日志                      ← 暂不做
实盘 Agent：必须人工确认，不允许自动下单               ← 暂不做
```

**当前阶段不接任何真实交易接口。**

## 执行纪律（通用）

### 修改代码前
1. 读取相关文件，不凭印象
2. 定位调用链（rg / git grep）
3. 说明计划（改什么、为什么、影响范围）

### 修改代码中
1. 最小 diff，不做无理由整文件重写
2. 不改不相关的文件和逻辑
3. 不改没有被任务指定的模块

### 修改代码后
1. 复查变更文件
2. 运行验证命令（lint / test / build / 至少启动检查）
3. 如果失败 → 先定位原因，不盲目继续改
4. 汇总 diff

### 验收前
1. 确认验证命令输出正常
2. 确认没有引入新依赖
3. 确认没有破坏现有功能
4. 声称「完成/通过」前必须跑过验证

## Skill 路由规则

详见 `AGENTS.md` 6.4 节。核心原则：

- **领域 Skill**（`gold-daily-analysis`、`cme-options-analysis`、`frontend-page-refactor`）定义执行口径
- **工程 Skill**（`git-workflow-and-versioning`、`test-driven-development`、`code-review-and-quality`）定义过程纪律
- **验收 Skill**（`finance-agent-live-acceptance`、`finance-agent-report-artifact-qa`）定义完成标准
- 领域 Skill 不处理工程问题，工程 Skill 不做领域判断

## 测试分层

```text
unit（默认）：速度快，用 mock，不连外部服务     → pytest -m unit
integration：允许连本地 DB/Redis/文件系统      → pytest -m integration
live smoke：允许连真实外部数据源                → pytest -m live（必须显式执行）
```

详见 `tests/conftest.py` 和 `pyproject.toml` 的 pytest markers。

## 报告产物规范

每个报告生成后，必须同时产出三个文件：

| 文件 | 用途 | 格式 |
|------|------|------|
| `xxx_report.md` | 人类可读的分析报告 | Markdown（含溯源节） |
| `xxx_trace.json` | 机器可读的溯源记录 | JSON（见 TRACE_SCHEMA.md） |
| DB 记录 | 持久化存储 | PostgreSQL（report_items 表） |

## Obsidian / Mem0 写入时机

- **Obsidian**：长期事实（架构决策、路线图、版本记录）
- **Mem0**：短期摘要和约束（执行偏好、当前卡点）
- **hermes/**：当前会话的临时计划和 prompt

详见 `AGENTS.md` 第 8 节。
