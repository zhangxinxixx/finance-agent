---
name: liquidity-analysis
description: 评估美元流动性、融资压力、财政抽水、准备金、回购和信用利差对黄金的影响，并明确何时可以候选 SX 流动性抛售。
---

# 流动性与信用领域分析

本领域消费同一研究快照，负责确定性差分、时间对齐和条件判断；不创建第二任务主脑，不让 LLM 猜测缺失值。

## 观察变量

优先使用真实存在且有 source refs 的 SOFR、EFFR、IORB、WRESBAL/银行准备金、TGA 或 WTREGEN、RRPONTSYD、WALCL、HY OAS、VIX。当前日报护照已记录 `SOFR`、`EFFR`、`IORB`、`SOFR_MINUS_IORB`、`EFFR_MINUS_IORB`、`RESERVES`、`TGA_WEEKLY_AVERAGE`、`ON_RRP_USAGE`、`HY_OAS` 和 `VIX`；不能因此宣称所有序列都已实时发布或完全同步。

每行保留观测日、发布/抓取时间、频率和 freshness：日频、周均和行政利率不能无标签拼接。对 NY Fed 利率，按实际营业日发布时间处理；周均准备金/TGA 要同时保留周变化和数据日期。

## 计算与门控

计算：

- `SOFR - IORB`、`EFFR - IORB`；
- `Reserve_change = WRESBAL(t) - WRESBAL(t-1)`；
- `TGA_change = TGA(t) - TGA(t-1)`；
- RRP 变化和 HY OAS 变化（如果同窗口存在）。

`TGA 上升 + 准备金下降`只能标为财政抽水迹象；RRP 很低只能标为缓冲变薄。只有融资利差异常、准备金压力、信用利差快速走阔和美元现金需求等独立迹象共同出现，才把 `SX Liquidity Selloff` 作为候选。缺其中任一关键条件时不把普通黄金下跌解释为流动性危机。

油价属于通胀/事件共享证据，流动性模块可引用但不能重复投票。HY OAS 既可描述信用风险也可描述流动性压力，必须在最终综合中去重。

## 输出契约

输出 `snapshot_id`、`input_snapshot_ids`、`source_refs`、每个指标的最新/前值/变化/日期/状态、公式、是否同窗、局部 `bias`、`sx_candidate`、触发条件和限制。若融资市场正常但财政抽水边际增强，应明确写成“流动性边际收紧、尚未构成 SX”，不能用 RRP 单项下危机结论。
