# Analysis Quality Regression Rubric

本文件定义黄金宏观分析结果的稳定回归维度。它不进入每次开发提示词；只在分析 pipeline、report、AgentOutput 或质量门发生变化时使用。

## Required Dimensions

| Dimension | Pass condition |
|---|---|
| Lineage | 重要结论能追溯到 `input_snapshot_ids`、`source_refs` 或明确 artifact |
| Epistemic status | 已观察事实、系统计算、模型推断和待验证假设可区分 |
| Freshness | 数据时间、报告时间和 stale/partial/unavailable 状态明确 |
| Missing data | 缺失数据不会被补造，不足以判断时降低 confidence 或返回 unavailable |
| Determinism | 可重复计算的指标留在 features/outputs，不由前端或 LLM 重算 |
| Domain consistency | 实际利率、美元、流动性、风险溢价及相关黄金框架定义前后一致 |
| Decision trace | 主导变量、情景路径、确认条件、失效条件和风险点互相一致 |
| Change awareness | 与上一期重复的结论说明“无变化”，变化结论给出新增证据 |
| Presentation | Markdown/JSON 非空，关键字段和引用入口对消费端可用 |

## Regression Evidence

变更至少选择一种真实证据：

- 固定 fixture 或历史 artifact 回放；
- `tests/analysis/test_coordinator_regression.py`；
- `tests/analysis/test_agent_quality_gate.py`；
- `tests/api/test_quality_gate_service.py`；
- `tests/api/test_report_lineage_write_validation.py`；
- 具体报告 Markdown/JSON 与上一版本的结构化对比。

## Scoring

- Blocker: lineage 丢失、事实/推断混淆、缺失数据被当作确认事实、核心指标定义漂移。
- Major: freshness、确认/失效条件、跨期变化说明或消费端字段不完整。
- Minor: 不影响含义和追溯的展示一致性问题。

只有所有 Blocker 为零、相关 Major 有明确处置，并保留验证证据时，分析质量回归才通过。
