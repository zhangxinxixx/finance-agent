# 金十小程序数据源清单

> 核验日期：2026-07-21。入口：`https://www.jin10.com/minipro/index.html#/`。

## 已接入

### 黄金与白银 ETF 持仓

- API：`https://mp-api.jin10.com/api/etf-reports`
- `attr_id=1`：SPDR Gold Trust 黄金 ETF。
- `attr_id=2`：iShares Silver Trust 白银 ETF。
- 核心字段：`trust`（总持仓吨数）、`change`（日变动吨数）、`value`（美元价值）、`reported_on`、`updated_at`。
- 生产路径：`news_collect -> raw -> parsed -> etf_holdings feature -> gold_macro_overview -> news claims / FactReview -> final report`。
- 数据角色：`supplemental_source` / `single_source`。不得单独升级为官方确认结论。
- Artifact：
  - `storage/raw/news/jin10_minipro_etf_reports/<date>/`
  - `storage/parsed/news/jin10_minipro_etf_reports/<date>/`
  - `storage/features/market/<date>/<run_id>/etf_holdings.json`

旧数据中心 slug `dc_etf_sliver` 是上游历史拼写，公开 latest JS 在核验时停留于 2020 年，不能用于当前白银持仓。当前链路使用小程序 `/api/etf-reports`。

## 候选能力

以下接口已从当前小程序前端路由中识别，但尚未等同于生产接入；接入前仍需逐项验证授权、字段、freshness、分页和来源角色。

| 数据族 | 候选接口 | 可能用途 |
| --- | --- | --- |
| ETF 扩展 | `/api/etf-reports/view`、`/divergence`、`/extreme` | 持仓趋势、背离与极值监控 |
| CME 报告 | `/api/cme-reports/details`、`/data` | CME 金属与成交量补充验证 |
| CFTC 报告 | `/api/cftc-reports/details`、`/data` | COT/CFTC 展示与官方源交叉验证 |
| 机构持仓 | `/api/investor-holding/categories`、`/list` | 顶级投资者及机构持仓观察 |
| 长图数据 | `/api/long-pictures/categories`、`/list`、`/details` | 图形化宏观、贵金属与市场专题发现 |
| 黄金交易 | `/api/gold-trading/data/latest`、`/list`、`/step` | 黄金交易数据观察，不直接替代主行情源 |
| 期权看板 | `/api/options-board/list`、`/details` | 期权结构候选补充源 |
| 银行订单 | `/api/bank-order`、`/data`、`/statistic` | 投行订单与价位观察 |
| 黄金储备/需求 | 小程序分类中的 `GlobalGoldReserve`、`GoldReserveRanking`、`GlobalGoldDemand` | 央行储备、全球需求候选发现 |

## 接入约束

- 小程序 API 属于金十展示层接口，字段和路径可能变化；必须保存 raw 响应并做 schema/freshness 检查。
- 新数据必须经过 parser 和 feature，不允许报告或前端直接请求并计算。
- CFTC、CME、央行储备等已有官方主源的主题，小程序数据只作补充和差异报警。
- 任何空响应、陈旧数据或 schema 变化都必须显式降级，不得沿用历史值冒充当日值。
