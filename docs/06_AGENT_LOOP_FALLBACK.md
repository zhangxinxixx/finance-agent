# AgentLoop Fallback 质量门控设计

## 背景

当前 Agent 架构已经具备以下基础能力：

- Domain agents 从 `AnalysisSnapshot` 读取结构化输入，输出 `bias / confidence / key_findings / risk_points / watchlist / invalid_conditions`。
- `fact_review_agent` 会审查 claims、source_refs、evidence_refs 与跨 Agent bias 冲突。
- `ReviewItem` 可承接 unsupported / contradicted 等问题，供人工复核。
- `synthesis_agent` 用于综合 domain agents、fact review 与 reviews。

但现有链路更偏向“标记问题 / 降级展示 / 人工复核”，缺少一个明确的闭环：

> 当分析结果或识别结果不准、证据不足、解析异常、Agent 冲突时，不应直接通过主链；需要触发 fallback 分析任务，重新分析后再决定是否进入 synthesis / final report。

## 目标

引入 AgentLoop Quality Gate，使 Agent 主链从一次性执行变为可自我校验、可回退、可重跑的闭环。

核心目标：

1. 不准确、不完整、不可信的分析输出不能直接进入最终结论。
2. 识别/解析不准时自动切换 fallback 分析路径，而不是只生成 review item。
3. fallback 仍失败时，必须显式降级为 `needs_review` 或 `blocked`，并把原因写入任务、报告与前端检查面板。
4. 所有 fallback 行为必须保留可追溯记录：触发原因、输入快照、原始输出、fallback 输出、最终采用版本。

## AgentLoop 状态机

```text
primary_analysis
  -> quality_gate
      -> passed
          -> synthesis
          -> final_report
      -> retryable_failed / low_confidence / parse_suspect / conflict
          -> fallback_analysis
              -> fallback_quality_gate
                  -> passed
                      -> synthesis
                      -> final_report
                  -> failed
                      -> needs_review / blocked
                      -> no_strong_conclusion
```

## Quality Gate 输入

Quality Gate 不直接读取 raw data，只消费以下结构化对象：

- `AgentOutput`
- `fact_review_agent.payload`
- `ReviewItem`
- `AnalysisSnapshot.status`
- parse / OCR / VLM / CME / Jin10 等上游 step summary
- `source_refs` 与 `evidence_refs`
- `confidence`
- `data_quality`
- `invalid_conditions`

## 不通过条件

### 1. 事实审查不通过

以下状态不能直接进入强结论：

- `fact_review_status = needs_review`
- `fact_review_status = conflicted`
- `fact_review_status = unavailable`
- 存在 `unsupported_claim_ids`
- 存在 `contradicted` claim
- 存在来源不可验证的核心 claim

处理：触发 fallback 分析任务。

### 2. 识别/解析不准

以下情况视为识别不准：

- CME / OCR / VLM / PDF parse 返回 `partial_success`、`failed`、`unavailable`
- 关键字段缺失，例如 `trade_date`、near-month contracts、OI、volume、strike、gamma wall
- `data_quality` 包含 `parse_suspect`、`stale_data`、`low_coverage`、`missing_required_fields`
- 输出内容出现“未从识别结果中稳定提取”，但该字段又被用于主结论

处理：优先 fallback 到更保守的分析路径，例如：

- 从视觉/LLM 识别 fallback 到规则解析或人工校验队列
- 从增强分析 fallback 到 deterministic analysis
- 从强结论 fallback 到观察性结论

### 3. 置信度不足

建议默认阈值：

```text
critical domain agent confidence < 0.60 -> fallback_analysis
coordinator confidence < 0.65 -> fallback_analysis
synthesis confidence < 0.70 -> no_strong_conclusion / needs_review
```

critical domain agents 建议包括：

- `macro_liquidity_agent`
- `cme_options_agent`
- `risk_agent`
- `coordinator_agent`

### 4. 跨 Agent 冲突

以下冲突需要进入 fallback：

- `macro_liquidity_agent` 与 `coordinator_agent` 方向相反
- `risk_agent` 明确风险升高，但 `coordinator_agent` 输出强趋势结论
- `cme_options_agent` 证据不足，但 final report 使用其结论作为关键交易依据
- bullish / bearish claim 同时存在且都被标为核心结论

## Fallback 任务类型

建议定义四类 fallback：

```text
fallback_reparse
fallback_reanalyze
fallback_cross_check
fallback_conservative_synthesis
```

### fallback_reparse

适用于：OCR / PDF / CME / Jin10 识别不准。

输出要求：

- 原始解析结果
- fallback 解析结果
- diff summary
- missing fields
- confidence delta
- 是否允许下游使用

### fallback_reanalyze

适用于：Agent 输出低置信、结论跳跃、证据不足。

输出要求：

- 原 AgentOutput
- fallback AgentOutput
- changed_fields
- accepted_output = primary | fallback | none
- reason

### fallback_cross_check

适用于：跨 Agent 结论冲突。

输出要求：

- conflicting_agents
- conflicting_claims
- source comparison
- winning evidence
- final verdict

### fallback_conservative_synthesis

适用于：fallback 后仍无法确认。

输出要求：

- 不输出强方向结论
- 报告中明确写“证据不足 / 需复核 / 仅观察”
- strategy card 降级为 observe / wait

## 建议数据结构

### AgentLoopDecision

```json
{
  "run_id": "...",
  "snapshot_id": "...",
  "gate": "agent_quality_gate",
  "decision": "passed | fallback_required | blocked | needs_review",
  "reasons": [
    {
      "code": "low_confidence",
      "agent_name": "cme_options_agent",
      "severity": "warning | error",
      "detail": "confidence 0.52 below threshold 0.60"
    }
  ],
  "fallback_tasks": [
    {
      "task_type": "fallback_reanalyze",
      "target_agent": "cme_options_agent",
      "input_snapshot_id": "...",
      "max_attempts": 1
    }
  ],
  "accepted_outputs": {
    "cme_options_agent": "primary | fallback | none"
  }
}
```

### AgentOutput payload 扩展

```json
{
  "quality_gate": {
    "decision": "passed | fallback_required | blocked | needs_review",
    "reasons": [],
    "fallback_of": null,
    "fallback_attempt": 0,
    "accepted": true
  }
}
```

## Runner 接入点

当前建议接在 C4 pipeline：

```text
Domain agents
  -> fact_review_agent
  -> agent_quality_gate
  -> optional fallback tasks
  -> coordinator_agent / synthesis_agent
  -> final_report / strategy_card
```

最小改造方案：

1. 在 `_run_c4_agent_pipeline` 中 domain agents 产出后执行 `evaluate_agent_quality_gate()`。
2. 如果 `decision = passed`，继续原链路。
3. 如果 `decision = fallback_required`，运行一次 fallback agent set。
4. fallback 通过后，用 fallback output 替换 primary output，并在 payload 标记 `fallback_of`。
5. fallback 仍失败时，不生成强方向 final report；生成降级报告与 ReviewItem。

## 前端展示要求

Agent Task / Inspection Panel 应展示：

- 当前输出是否通过 quality gate
- 是否使用 fallback output
- fallback 触发原因
- primary vs fallback 差异
- 哪些结论被降级或不允许进入主结论
- 是否需要人工复核

## 报告写作约束

当 gate 未通过时：

- 不能输出“趋势确认”“强多/强空”等确定性结论。
- 必须写明：哪些证据不足、哪些识别不准、哪些 claim 冲突。
- strategy card 默认为 `observe / wait`。
- key levels 可以保留，但必须标注“仅作观察，不构成确认”。

## 验收标准

1. 构造低置信 `cme_options_agent` 输出时，系统创建 fallback 分析任务。
2. 构造 unsupported claim 时，不能直接进入强结论 synthesis。
3. 构造 bullish / bearish 冲突时，quality gate 返回 `fallback_required` 或 `needs_review`。
4. fallback 通过后，final report 使用 fallback output，并保留 trace。
5. fallback 失败后，final report 降级，不输出强交易结论。
6. Review Center 能看到对应 `ReviewItem` 与 fallback reason。

## 实施优先级

### P0

- 新增 `agent_quality_gate` 决策模块。
- 接入 `fact_review_status`、`confidence`、`invalid_conditions`。
- 失败时阻断强结论输出。

### P1

- 增加 fallback task 类型。
- 记录 primary / fallback output diff。
- 前端展示 gate status。

### P2

- 针对 CME / Jin10 / OCR / VLM 做专项 fallback parser。
- 增加自动回归测试与历史 run replay。
