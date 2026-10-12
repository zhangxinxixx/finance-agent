---
name: gold-market-analysis
description: 运行可追溯的 XAUUSD 宏观、利率、流动性、资金和 CME 结构综合分析；用于黄金日报、周报及非农、CPI、PPI、FOMC 后更新。
metadata:
  version: "2.7"
  language: zh-CN
---

# 黄金市场综合分析

## 当前日内PA范围

日内执行先分析4H、1H、15m，不分析5m。`price_action.v1`用左右各2根完整K线确认摆动，保留pivot_time/confirmed_at；按已确认摆动推进HH/HL/LH/LL与BOS/CHoCH，不把前5根区间突破代理混称摆动BOS。Zone break/reclaim/retest只对上一核验报告中已经知道的区间，从该快照时点后评估；当前新算zone不能回填历史信号。影线拒绝只作辅助，FVG/OB/VP、量能与仓位管理不在本版范围。

最终综合需要结合PA与CME，说明支持/冲突/无法确认，不强迫同向。CME纽约分析日相对报告日的交易日年龄：0—1日系数1.0、2日0.5、3日及以上0.2且仅背景；PRELIM可直接用于研究、不等待FINAL且不额外降权；版本未知另乘0.5，无来源/未来/日历未知为0。自然日年龄同时展示；系数是未校准研究证据权重，不是概率。GC Proxy坐标不直接映射XAU，缺少基差不能据墙位宣称精确共振。PA不直接写Accepted或下单。

本 Skill 是黄金分析的编排规范。它把采集、校验、确定性计算、领域判断和最终综合分开；最终由现有主链中的 `coordinator_agent` 形成总判断。不要在 Skill 中另造任务调度器、第二套数据链或前端计算逻辑。

## 生产边界

遵守项目主链：

`api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output`

领域模块只消费带 `snapshot_id`、`input_snapshot_ids` 和 `source_refs` 的快照或领域输出。原始响应/PDF 归档在 raw，解析结果在 parsed，指标在 features，观点和报告在 analysis/output。历史报告不可覆盖。缺失数据写明缺失原因，不能用旧值、搜索摘要或模型常识补齐。

当前运行入口是：

- `GET /api/tasks/premarket/preflight`：检查运行中的任务和源可用性；
- `POST /api/tasks/premarket`：触发一次完整盘前主链；
- `GET /api/tasks/{task_id}`、`GET /api/tasks/{task_id}/logs`：轮询任务与步骤；
- `GET /api/runs/{run_id}/artifacts`、`GET /api/agent-analysis?date=YYYY-MM-DD&run_id=...`：读取产物和 Agent 输出。

触发后必须以实际任务/GraphQL 状态和报告文件为准，不能把 HTTP 接受请求当成分析完成。Jin10 不属于本 Skill 的数据源；保持明确禁用，不把主动排除标成采集失败。

## 分析顺序

按需要读取四个领域入口。Skill 规定方法，数值由对应程序计算；它们不启动新的生产调度器。

| 领域 Skill | 负责内容 | 已有代码入口 |
|---|---|---|
| [macro-rates-analysis](../macro-rates-analysis/SKILL.md) | 官方实际利率、美元、曲线、Fed/通胀/增长 | `apps/features/research/daily.py`、`apps/analysis/agents/macro_liquidity.py` |
| [liquidity-analysis](../liquidity-analysis/SKILL.md) | 数量、融资价格与信用共振 | `apps/features/research/workflow.py`、`apps/analysis/agents/risk.py` |
| [gold-flow-analysis](../gold-flow-analysis/SKILL.md) | 同窗口 CFTC 变化、ETF 申赎 | `apps/features/research/flows.py`、`apps/analysis/agents/positioning.py` |
| [cme-gold-options-analysis](../cme-gold-options-analysis/SKILL.md) | 期权结构、定价输入质量和期限 | `apps/analysis/agents/cme_options.py`、`apps/features/research/levels.py` |

总 Agent 使用 `apps/analysis/agents/coordinator.py` 汇总领域输出，再由 `research_synthesis.py` 经现有 LLMGateway 开展独立综合研判。允许质疑模块判断、重评规则场景、提出遗漏传导和替代假设；规则结论是参考输入，不是要求模型同意的答案。实际模型、调用审计和 `success/rule_fallback` 状态从当次 AgentOutput 读取；不要把确定性降级说成已完成模型分析。

1. 建立 Data Passport：`analysis_time`、现货报价时间、报价类型、时区/延迟、各官方序列观测日、CFTC 截止日、ETF 日期、CME 文件和到期日。
2. 校验每个值的来源、抓取时间、观测时间、单位、频率和跨源时间一致性。现货与 COMEX 期货必须分别标记；日线收盘不能冒充盘中报价。
3. 按领域 Skill 由底层程序计算宏观利率、流动性、资金、期权、关键位生命周期、研究状态候选和规则场景，并运行前置质量门，锁定 `gold_workflow.v2` 快照。
4. 由领域模块先给出事实、计算、缺口和局部判断，再交给现有 `coordinator_agent`。总 Agent 可以解释冲突、提出独立方向/状态候选/关键位假设并形成报告；新增观点标为 MODEL、给出依据与反证，不自动改写已归档数值、日期、公式结果、系统关键位或缺失状态。
5. 运行输出 Quality Gate，核对事实引用与来源、是否明确区分系统结果和模型假设；允许模型提出不同的状态、关键位或路径判断，最后写带 lineage 的 Markdown/JSON 报告。

## 来源与证据标签

官方/原始来源优先：U.S. Treasury、Federal Reserve、New York Fed、FRED、BLS、BEA、ISM、Atlanta Fed、CFTC、CME、State Street、iShares、WGC。Reuters/AP/Bloomberg 只用于新闻事件和即时反应核验。TradingView、预测市场和评论只能标为辅助或未确认。

报告中区分：

- `[FACT]`：原始数据或可复核的观测事实；
- `[NEWS]`：已标明来源和时间的新闻事实；
- `[CHART]`：独立价格序列或图表结构；
- `[MODEL]`：公式、状态机、情景或关键位推断；
- `[UNCONFIRMED]`：二级来源、摘要或尚未交叉确认的信息。

新闻标题不能自动变成宏观事实，模型推断不能写成官方结论。

## TradingView 盘中研究补充

原 merge TaskStep 调用 `apps/worker/cross_asset_research.py`，采集并冻结 `tradingview_cross_asset`；raw、parsed、features 与原分析快照一并溯源。WTI固定为 `NYMEX:CL1!`，Brent为 `ICEEUR:BRN1!`；另取 `OANDA:XAUUSD` 和 `TVC:DXY/US03MY/US02Y/US10Y/US30Y`。不得用经纪商USOIL、期货与现货互相替代。

模型研究循环和最终综合同时消费TV观测及 `cross_asset_freshness`。TV的日线 `time` 是bar起点，不是当前成交时间；`retrieved_at` 是采集时间。`delayed_streaming_600`必须显示600秒延迟，缺少分钟bar/报价时钟时标为 `DELAYED_CLOCK_UNVERIFIED`，能源能力保持 `DEGRADED` 并报告 `ENERGY_INTRADAY`。分钟bar超过15分钟、未来时间、未知延迟均不能参与盘中确认；曲线两腿还须相差不超过2分钟。

读者报告分列官方日终与TV盘中表，保留两者不同的单位、时间和权威性。不用TV名义10Y减异步FRED通胀预期生成所谓官方实际利率。单次快照不能支持事件前后收益率或已确认实物供应冲击。GLD比较必须显示份额和吨数各自的起止日期、两端值及变化。

## 四个因子与时间口径

### 实际利率

研究层优先使用官方 `DFII10`；如果它在当前窗口不可用，再使用同期名义 10Y 减 `T10YIE` 的估算，并明确 `estimated_same_date`。异步估算只能标为背景，不能作为该实际利率输入参与方向确认。5Y/30Y TIPS、T5YIE、T5YIFR 等只有在快照实际存在且通过 lineage 校验时才可使用。当前经验分区 `2.35% / 2.40% / 2.45%` 是可配置的 regime 阈值，不是永久规律。

正式 Gold Policy 的既有版本和状态文件保持原契约；改变其实际利率权威口径必须通过新的版本化契约，不能在日报 Skill 中偷偷改历史语义。

### 美元与收益率曲线

Broad Dollar Index 是正式宏观美元指标；DXY 可作为盘中辅助，二者日期和含义不得混用。若没有明确残差化计算，不要把 `Residual Dollar Shock` 写成已计算事实。

计算并展示 `2Y-3M`、`10Y-2Y`，以及数据存在时的 `30Y-10Y`。2Y-3M 用于政策周期和经济周期背景，不能单独作为黄金方向信号；2Y 观察 Fed 定价，10Y 观察实际利率和中长期通胀/增长，30Y 观察财政、期限溢价和长期债务压力。

Fed 讲话、市场利率反应和美元反应分开记录。只有“讲话 -> 2Y/DXY/实际利率 -> 黄金”的链条在数据上得到支持时，才可说某种政策影响；“已 price-in”属于 `[MODEL]` 推断。

### 流动性、通胀和信用

SOFR、EFFR、IORB、准备金、TGA、RRP、WALCL、HY OAS 和油价按观测日记录。`TGA 上升 + 准备金下降` 只是抽水迹象；只有融资利差异常、准备金压力和信用利差快速走阔共同出现，才允许候选 `SX Liquidity Selloff`。RRP 接近零本身不等于危机。

战争/供应冲击必须拆成安全避险通道和油价-通胀-Fed 通道，依据当期利率、美元和风险价格判断谁占主导，不能写“战争升级所以黄金必涨”。HY OAS 若同时被流动性和信用模块使用，只计为同一个共享信用证据，防止重复投票。

## 资金和期权规则

CFTC 判断必须使用同一窗口的价格变化以及 long、short、spreading、Other Reportables、Total OI 和各自 delta，区分新多、空头回补、多头平仓和新空。净多绝对值大不等于正在加仓。

ETF 优先使用 GLD/IAU shares outstanding 或 gold holdings。AUM 会随金价变化，不能单独当成资金流入。CME 期权只有拿到行权价、类型、结算、OI、到期、IV/IV 来源等字段时才形成墙和 pin；没有完整输入就写“本次不参与强结论”。

Black-76 的 GEX 是模型暴露估计，不是已知 dealer 实际仓位。若 put GEX 以负号记录，直接对 call/put signed contributions 求和；若先取 put 的正值绝对量，才用 `call magnitude - put magnitude`。两种符号约定不可混用。

把 vendor IV、由期货结算反推的 settlement-implied IV、以及无 IV 时的 gamma proxy 分开命名。结算隐含 IV 可以用于模型计算，但不能冒充 vendor IV；proxy 不能称真实 GEX。到期后的墙和 max pain 标为 `Invalidated`，max pain 仅是接近到期且有其他结构支持时的 soft anchor。

## 状态、关键位和证据门控

研究层可使用 `S1 Rates Pressure`、`S2 Support Defense`、`S3 Bottom Confirmation`、`S4 Range Accumulation`、`S5 Active Repair`、`S6 Trend Continuation`、`SX Liquidity Selloff`。它是研究状态机，不自动等同于正式 Gold Policy 状态。没有合法同资产、严格更早的 predecessor 时，不得伪造 Previous State 或强行 bootstrap；应输出 current unavailable/observation，并说明原因。

状态升级至少需要两类独立证据（例如价格结构 + 实际利率，或资金 + 宏观），而且必须通过时间和数据质量门控。一天的涨跌、单条新闻、净多绝对值、单一指标或旧期权墙都不能单独升级/降级。总 Agent 需要同时回答：当前状态、主导因子、价格是否得到宏观和资金确认、触发下一状态的“价格 + 宏观”联合条件。

每个关键位带 `price`、`instrument`、`role`、`source_type`、`source_date`、`confidence`、`status`、`activation`、`invalidation`、`valid_until`、`previous_role`。支持/阻力翻转要显式记录；过期水平不能留作 Active。spot 和 futures 的关键位不混用。

## 情景与执行环境

研究特征层还提供三个可复用的纯函数：

- `build_session_quality(snapshot, calendar=None)` 生成版本化 `research_session.v1`。它分别记录 `session_class`（`NORMAL`、`HOLIDAY`、`EARLY_CLOSE`、`PARTIAL`、`LOW_LIQUIDITY`）、`otc_daily_close`、`cme_settlement`、`liquidity_class`、`calendar_version`、`source_refs` 和 `confidence_multiplier`。CME 不发布 settlement 不等于 OTC 没有报价；假日的关键位置信度乘 `0.7` 是规则系数，不是概率。未提供或无覆盖的日历进入 `PARTIAL`，早收和未知不会被补成正常交易日。
- `build_execution_zones(snapshot, levels=None, session_quality=None)` 生成 `execution_zones.v1`。`raw_levels` 原样保留，spot 执行区使用实际可得的 ATR、spread、intraday range 和 source dispersion，并在 `inputs`、`input_methods`、`missing_inputs`、`zone_method`、`width_policy_version` 和 `confidence` 中说明口径；缺少的 spread/dispersion 不填常数。每个 zone 同时保留 `raw_lower/raw_upper` 与向外取整的 `display_lower/display_upper/display_label`，CME futures 坐标不转换成 spot 目标。
- `build_scenario_display(scenarios, mode="5pct")` 保留 `raw_scenarios` 和原始规则权重；`5pct` 显示按 5% 档位并归一到 100，`level` 显示 High/Medium/Low。输出固定标明 `uncalibrated`、`is_probability=false`、无 Brier 校准，不把规则权重改写成统计概率。

这些特征只作为 `coordinator_agent` 的可追溯输入，不能另起调度器或由前端重复计算。会话日期必须对应实际观察日；报告日与假日收盘日不同的时候，关键位置信度调整只作用于假日日期产生的水平。

宏观、价格、期权、资金、事件的 `35/25/20/15/5` 是可解释的类别权重，不是统计概率，也不是三个情景的自动概率。缺失期权时只能对可用类别重新归一化并降低总体置信度，不能把缺口当中性票。已采集的期权和新闻若尚未证明方向，标 `direction_unavailable`，仍展示结构/事件约束，但不伪造中性权重。Main、Bull、Bear 每条都要有 `Weight`、`Trigger`、`Macro Confirmation`、`Price Path`、`Invalidation`，且明确权重是规则权重或情景评分。

执行卡只描述交易环境和条件：4H/1H用于背景和过滤，15m为主要观察周期，当前不分析5m。重大数据公布后等待首轮流动性扫单、回踩和结构确认，不追第一根15m K线。没有合格的盘中数据时写“无法验证执行触发”，不从日线臆造日内信号；不自动下单。

## 自主研究与读者报告

基础数据用于发现问题，不决定每天的分析主题。官方通胀、就业、Treasury、基础行情、核心资金和正式状态前序是确定性安全底座，Agent不能为了某个叙事取消这些采集。现有快照合并步骤调用 `apps/worker/adaptive_research.py` 的多轮研究循环：模型先指出当天最需要解释的市场矛盾、主假设、竞争假设和反证，再从版本化能力目录中自选补采；证据返回后再次评估，自主继续、换方向或结束。

补充请求采用`research_plan.v2`，每项必须写明provider/key、要验证的claim、对状态/情景/置信度的decision impact、freshness need和priority。当前可执行能力以apps/worker/research_capabilities.py为准：FRED、TradingView、Reuters元数据、公开正文、新闻发现、web_search及归档资料/CME按需展开；程序在采集前验证能力和预算，模型不能发明工具或标的。TradingView白银现货代理使用`TVC:SILVER`，不把它写成某家经纪商XAGUSD。每轮FRED和TradingView各最多四项、Reuters最多两项；默认最多三轮补采，累计八个FRED、六个TradingView和四个新闻请求。600秒为阶段间检查的软时间预算，单次外部调用仍受自己的超时约束。这些是能力和资源边界，不是每日清单，也不要求用满。

每次决策先保存不可变decision.json，采集后保存evidence.json及前序引用和哈希；最终`adaptive_research.v3`记录初始plan、完整rounds、final_assessment、每项选择理由、能力外数据缺口、stop_reason与消耗。两轮没有新增证据时只允许最终评估，不继续抓相同provider+key。重复请求、预算、模型失败与证据充分分别记录；外部失败不是支持原假设的证据。决定性能力外缺口使研究状态保持partial，并传给总Agent限制结论。v1/v2历史调查仍可读取，历史快照不覆盖。

主流新闻正文是必须检查的底座。程序通过公开发布方feed和正文读取提供24小时内新闻，至少包含一篇明确Reuters署名及两篇新鲜主流媒体正文。CNA转载的Reuters稿件按Reuters原始机构计源，不重复计票；图片REUTERS版权不能冒充文章来源。新鲜度以正文发布时间为准，不能用抓取时间或旧稿更新时间刷新。缺日期、过期、仅搜索标题不关闭新闻正文缺口；研究Agent须换源或保留决定性缺口，程序不得判定evidence_sufficient。正文和CME都可按需展开，只有有决策价值才追加读取。

总 Agent 可以根据新增证据推翻初始假设、质疑模块结论和规则排序。主导因子、论证顺序、篇幅和章节由模型判断，不能为了覆盖所有模块而逐项复述；不强制每天分析能源、增长或任何固定专题。需要当前能力之外的数据时，明确提出研究缺口及其可能影响，不能声称已经采集。

`reader_narrative` 保存连贯中文正文。先给最有解释力的判断，再围绕关键证据、反证、替代解释和判断改变条件展开。结论所依赖的时间、来源和不确定性必须可追溯；保持独立观点不等于解除事实约束。规则状态是参考和正式权限边界，不能代替市场解释。

### 日报输入与完整交付

日报先读取最近有效日报和最新有效周报，再联网核验当期行情与宏观材料，逐项重验旧假设。现有主链用 `report_continuity.py` 校验注册身份、资产、实际截止、质量、路径、正文哈希和 lineage，将两份完整正文同时交给自主研究和最终综合。同日较早的报告可以接续；生成时间不代替分析截止。历史正文只是旧观点，不能成为当前事实或 Accepted 权威。任一报告缺失、被拒绝或超限时如实说明，不能声称已读，也不能用另一份或样本替代。

新日报采用 `gold_reader.v4` / `gold_reader.research.v1`，写作方法见 [gold_macro_daily.md](../../../apps/analysis/prompts/gold_macro_daily.md)。以“一句话结论”交代阶段、主导矛盾和相对前序的变化，并给真实北京时间截止及参考现货报价时间。围绕当天重新定价、政策三段、利率与跨资产传导、黄金承接、关键位、未来1—3日情景、下一事件与改判开关自然展开。判断先行，事实和推论说清楚，来源就近附；合并重复，不机械压缩内容或套固定章节。4H/1H过滤、15m确认，合理结构止损超过20美元/盎司就等待或跳过，不编造已触发信号。

用户请求日报时，聊天直接呈现报告的完整正文，文件保存同一正文；不能只交摘要或文件链接。读取实际产物后再展示，不从模板或归档回放冒充最新研究。内部20主题推理、完整来源链和确定性明细保留在审计附件。报告未通过生成或质量门时只如实交代阻断与缺口，不能把诊断包装成完整日报。每次价格、数据、主线、方向和关键位依据当期证据更新，不沿用样稿数字；不使用金十。

历史 `gold_reader.v2` / 报告2.4.0的`final_report.md`提供核心判断、精简行情快照、自主研究正文和来源，并固定附上五张简明决策卡：Delta、Accepted/Candidate、完整三路径、空仓/多单/空单执行环境、数据健康。固定卡片不限制模型正文的主题和结构，数据不足也应显示缺口，不能静默省略。`audit_report.md`单独保存完整数据护照、模块结果和溯源，两者绑定同一冻结快照。历史v1报告不重写，重放不重新调用模型。

Delta对比上一份核验研究报告，不能冒称上一Accepted报告；同源现货报价、ETF份额/吨数、同CFTC口径水平分别比较，周变化不是报告间变化。无前序或来源/日期不可比时差值为空。Accepted为空就写初始化待确认，规则neutral不等于正式中性；候选数据校验通过不等于迁移触发已确认。Main由当前评分决定，可以是Bull或Bear；必须同时展示区间、多头、空头三种路径及触发、宏观确认、失效。未校准分数不叫概率，未实现的BOS/CH/失败突破不伪装成已识别形态。

## Quality Gate

提交综合报告前逐项检查：Spot/Futures 是否区分；数据日期和时区是否齐全；实际利率是否同期且标明估算；OI 是否与 volume 分开；ETF AUM 是否误作流量；新闻和模型是否分开；旧期权是否失效；关键位生命周期是否更新；方向是否有至少两类独立证据；核心缺口是否降低 `Data Quality` 和置信度。任何关键数据缺失时写“本项不参与方向确认”，不得输出无依据的“强烈看多/看空/趋势确认”。

总 Agent 输出不符合 JSON 格式或证据 ID 白名单时，最多一次格式修复，每次均通过现有 Gateway 审计且复用相同证据白名单；仍不合格或请求失败则保留 rule_fallback。模型与 reasoning 由当前运行配置决定；完整正文单次等待上限为 360 秒，超时不冒充真实模型分析完成。

最终研判采用 `research_synthesis.v2`：不设置分析词语黑名单，也不因模型观点不同于规则或提出新数值假设而整段降级。新增数值仅作待核验模型提及，不自动写入事实。报告区分独立判断、模块质疑、替代假设、改变判断的条件和规则基线；正式状态写入权限仍按已有 Gold 主链处理。
