---
name: macro-rates-analysis
description: 计算和解释黄金分析所需的利率、实际利率、美元、收益率曲线、Fed 定价与宏观通胀传导；只输出带时间和来源的领域结果。
---

# 宏观利率领域分析

本领域是 `gold-market-analysis` 的确定性宏观输入，不负责调度任务，也不直接写最终报告。先读取同一 `daily_research.v1` 快照和其 source refs，再计算；不能从新闻或旧报告补数。

## 数据优先级和现有口径

优先读取 U.S. Treasury/FRED/Fed/New York Fed 的 3M、2Y、5Y、10Y、30Y 名义利率，DFII5/10/30（若快照存在），T5YIE、T10YIE、T5YIFR（若存在），Broad Dollar Index 和 DXY。当前项目日报护照已明确记录 `US03M`、`US02Y`、`US10Y`、`US30Y`、`BREAKEVEN_10Y`、`REAL10Y`（官方 TIPS）与 `REAL_10Y`（估算），以及 `YIELD_SPREAD_2Y_3M`、`YIELD_SPREAD_10Y_2Y`；新增字段必须先确认代码和快照中实际存在。

研究层优先 `DFII10`。仅在它缺失或不可用时计算 `10Y - T10YIE`，并把异步估算写为 estimated；不要把估算改名成官方实际利率。正式 Gold Policy 的旧版权威口径保持不变，口径变化需要版本化。

## 计算和判读

输出值、观测日、上一观测值、日/周变化、组成项和 source refs：

- `2Y-3M`：政策周期/经济周期背景；
- `10Y-2Y`：曲线中段；
- `30Y-10Y`：只有两端同日存在时计算，用于期限溢价/财政背景；
- 实际利率 regime：`<2.35`、`2.35–2.40`、`2.40–2.45`、`>2.45`，作为当前可校准阈值，不是永久结论；
- 名义利率、Breakeven、实际利率分别报告，避免把同一冲击重复算成三票；
- Broad Dollar 是正式美元方向，DXY 只作为盘中/辅助；没有残差化公式就不要宣称 residual dollar 已计算。

把 Fed 讲话、FedWatch/市场赔率（若实际可用）和 2Y 实际反应分成事实与推论。可以写“2Y 上行与讲话同步”，不能仅凭讲话标题写“Fed 已转鹰”。

## 宏观输出契约

领域输出至少包含 `snapshot_id`、`input_snapshot_ids`、`source_refs`、各值的 `observation_date`、`as_of`、`status`（fresh/stale/unavailable）、计算公式或 components、局部 `bias` 和 `limitations`。没有数据的变量保留 unavailable；不能用搜索结果、旧收盘或用户提供报告中的数字伪装当前值。

宏观方向只描述本领域证据：实际利率上升通常压制黄金，实际利率下降通常支持黄金；美元与实际利率同向时可增强解释，冲突时报告冲突并交给总 Agent。总方向必须由至少另一独立证据族确认。
