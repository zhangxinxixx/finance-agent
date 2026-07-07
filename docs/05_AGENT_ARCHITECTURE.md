# Agent 架构

## 定位

Agent 层只消费确定性数据快照和结构化输入，不直接修改 raw data，也不绕过 features / analysis 生成策略结论。

当前代码中的 Agent 主要位于：

```text
apps/analysis/agents/
apps/analysis/strategy/
apps/api/services/agent_output_service.py
database/models/analysis.py
```

## 三层模型

规划上的三层：

1. Domain agents
2. Fact review agent
3. Daily market synthesis agent

当前代码事实：

- Domain/coordinator agents 已接入 综合分析链路。
- `fact_review.py`、`synthesis.py` 模块存在，API 也支持 synthesis 读取。
- `fact_review_agent` 和 `daily_market_synthesis_agent` 是否稳定进入每日 premarket 主链，需要按真实 run artifact 进一步验证。

## Domain Agents

目录：`apps/analysis/agents/`

已发现：

- `macro_liquidity.py`
- `cme_options.py`
- `risk.py`
- `technical.py`
- `positioning.py`
- `news.py`
- `market_odds.py`
- `market_regime.py`
- `event_impact.py`
- `jin10_report_analysis_agent` 相关逻辑在 Jin10 analysis/report 模块中体现

职责：

- 读取 analysis snapshot 的对应 section。
- 输出 bias、confidence、key_findings、risk_points、watchlist、invalid_conditions。
- 绑定 `input_snapshot_ids` 和 `source_refs`。

## Coordinator

文件：

- `apps/analysis/agents/coordinator.py`
- `apps/worker/runner.py`

当前 综合分析链路 在 `apps/worker/runner.py` 中调用：

- `analyze_macro_liquidity`
- `analyze_cme_options`
- `analyze_risk`
- `analyze_technical`
- `analyze_positioning`
- `analyze_news`
- `analyze_market_odds`
- `coordinate_agent_outputs`

然后生成：

- final report
- strategy card
- DB `AgentOutput`
- DB `FinalAnalysisResult`

## Fact Review

文件：

- `apps/analysis/agents/fact_review.py`
- `database/models/analysis.py` 的 `ReviewItem`
- `apps/api/services/review_service.py`
- `GET /api/reviews`
- review action APIs

职责：

- 记录低置信、解析异常、Agent 输出冲突等需要人工复核的问题。
- 不直接覆盖历史 AgentOutput。

NEED_VERIFY：

- 当前每日主链是否自动运行 fact review。
- ReviewItem 的来源覆盖率是否已经包含 OCR/VLM、CME parse、Agent conflict、report review。

## Synthesis

文件：

- `apps/analysis/agents/synthesis.py`
- `GET /api/agent-analysis/synthesis/latest`

职责：

- 聚合 domain agents、fact review、reviews，形成日报级 synthesis。

NEED_VERIFY：

- synthesis 是否是每次 premarket 的必经步骤，还是可单独读取已存在 `synthesis_agent` 输出。

## Registry / Prompt Governance

文件：

- `apps/analysis/agents/registry.py`
- `apps/api/schemas/agent.py`
- `database/models/analysis.py` 的 `PromptVersion`、`PromptFeedback`
- `apps/frontend-web/src/adapters/agentRegistry.ts`
- `apps/frontend-web/src/pages/SettingsPage.tsx`

API：

- `GET /api/agents/registry`
- `GET /api/agents/registry/{agent_id}`
- `GET /api/agents/prompts`
- `GET /api/agents/prompts/{agent_id}`
- `GET /api/agents/prompts/{agent_id}/active`
- `POST /api/agents/prompts/{agent_id}`
- `PATCH /api/agents/prompts/{agent_id}/activate`
- `POST /api/agents/feedback`
- `GET /api/agents/feedback`

约束：

- Prompt 版本和反馈是治理数据，不应让 Agent 直接修改 raw source。
- severe feedback 可创建 ReviewItem。

## 持久化

模型：

- `AnalysisSnapshot`
- `AgentOutput`
- `FinalAnalysisResult`
- `PromptVersion`
- `PromptFeedback`
- `ReviewItem`

每个 AgentOutput 应保留：

- `run_id`
- `snapshot_id`
- `input_snapshot_ids`
- `source_refs`
- `payload`
- `payload_sha256`
- LLM metadata（如使用 LLM）
- `prompt_version_id`（如使用 prompt governance）

## 后续整理方向

- 把 综合分析链路 中的 Agent 步骤拆成显式 TaskStep。
- 将 fact review / synthesis 是否进入主链做成可验证状态。
- 统一 AgentOutput schema 与 frontend inspection view。
- 在 Report Detail 中稳定展示 Agent input/output/prompt/version/source trace。
