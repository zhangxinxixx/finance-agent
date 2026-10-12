---
name: cme-gold-options-analysis
description: 解析 CME 黄金期权 Daily Bulletin 的 OI、结算、IV、Black-76 Greeks、GEX、墙和到期生命周期；严格区分真实字段、结算隐含 IV 与 proxy。
---

# CME 黄金期权领域分析

本领域只消费已归档的 CME Daily Bulletin/结算数据和其解析结果。没有完整行级输入时输出不可用/部分可用，并明确不参与强方向结论；不能从成交量单独命名 Call Wall/Put Wall。

## 输入与价格类型

先区分 COMEX 合约、XAUUSD spot、连续期货和具体到期合约。行级结果应在存在时包含 strike、option_type、settlement、OI、OI delta、volume、block/PNT、expiry、IV 及 IV 来源、F、r、T。合约乘数默认 100 oz，但以项目字段/合约定义为准。到期日必须是实际合约日期或明确标为 estimated，估算到期不能生成伪造的概率或精确期限判断。

## IV、Black-76 与 GEX

优先使用 vendor IV；项目当前可有由期货结算反推的 settlement-implied IV，它可以进入 B76 模型，但必须这样命名，不能写成 vendor IV 或市场公布 IV。没有 IV 时可使用明确标注的 gamma proxy；proxy 不是真实 GEX。

Black-76 应记录 F、K、T、IV、r、delta、gamma 的来源，并用项目约定的 GEX 单位/缩放计算 1% price move 暴露。若 put GEX 是带负号的 signed value，净值应对 call 和 put signed contributions 求和；只有当 put 先取成正的绝对量时，才做 `call magnitude - put magnitude`。禁止把同一 put 负号再减一次。

GEX、gamma flip、Call Wall、Put Wall、pin zone 都是模型估计，表示基于公开 OI/输入的暴露集中区，不是已知 dealer 实际持仓或做市商意图。要用 OI/结构支持墙；volume 只能作为辅助，不可代替 OI。

## 生命周期和输出

对每个墙、pin、max pain 写 `instrument`、expiry、source_date、role、confidence、activation、invalidation、valid_until、status。到期后 `Invalidated`；旧期权水平不能继续作为当前目标。Max Pain 只在临近到期、OI 完整、连续稳定且没有重大冲击并得到 GEX/价格结构支持时作为 soft anchor。

输出 `snapshot_id`、`input_snapshot_ids`、`source_refs`、数据覆盖率、IV provenance、公式版本、Net GEX、flip、walls、pin、max pain、局部 bias 和 limitations。输入不完整时明确“本次 CME 结构不参与强结论”，不要编造精确 wall 或 GEX。
