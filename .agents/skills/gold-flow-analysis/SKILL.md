---
name: gold-flow-analysis
description: 解析黄金 CFTC、ETF 和价格/OI 配合关系，区分趋势建仓、空头回补、多头平仓和新空，并把资金证据交给黄金总 Agent。
---

# 黄金资金领域分析

本领域只分析带日期的 CFTC、ETF 和价格/OI 数据，输出事实、公式、局部判断和限制；不根据净多绝对值直接给出黄金总方向。

## CFTC

使用 CFTC 官方报告，并明确 futures-only、futures+options combined 以及报告截止日。能读取时保留 Managed Money Long/Short/Spreading、Other Reportables Long/Short、Total Open Interest 及上一报告期。计算 `Managed_Net = Long - Short`、各仓位 delta 和 `Delta_OI`，同时绑定同一窗口的金价变化。

用联合条件判读：

- 价格上升 + Long 上升 + OI 上升：新多候选；
- 价格上升 + Short 下降 + OI 下降/持平：空头回补候选；
- 价格下降 + Long 下降 + OI 下降：多头平仓/去杠杆候选；
- 价格下降 + Short 上升 + OI 上升：新空候选。

若价格窗口、CFTC 截止日和 ETF 日期不同，说明异步性，不把它们假设成同一时点。报告中的“趋势资金撤退”必须由仓位 delta/OI 和价格共同支持。

## ETF

优先 State Street GLD、iShares IAU 和 WGC 的 shares outstanding 或 gold holdings；保留申赎日期、单位和 source refs。AUM 同时受金价和份额影响，不能单独当作资金流入。只有 shares 或 holdings 的方向变化可以支持申购/赎回叙述；数据缺失时写“不参与强结论”。

## 输出契约

输出必须有 `snapshot_id`、`input_snapshot_ids`、`source_refs`、报告日期、最新/前值/delta、同窗价格、`status`、局部 flow regime、`limitations`。`source_refs` 只引用真正读取的 CFTC/ETF 原始文件或页面。资金与宏观同向只能作为两类证据之一；若 CFTC 去杠杆而 ETF 增持，应保留“快钱撤退、配置资金承接”的冲突，不替总 Agent 抹平。
