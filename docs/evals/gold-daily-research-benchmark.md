# 黄金综合日报最低标准与模块适配

当前产品验收以[黄金研究质量基准与自动化验收规范 v1.0](gold-research-quality-v1.md)为准。本页保留早期基准拆解和历史工程证据；历史运行、测试数量或旧最低标准不代表已通过新的同证据对照、盲评或端到端验收。

基准：用户提供的 2026-09-05 GPT-5.6 报告；系统在此基础上增加现有 CME 分析。目标是可重复生成同等覆盖面、变化解释、冲突证据及条件场景，不能把篇幅、固定标题数或一次任务成功当作质量验收。

## 基准拆解与必要纠正

| 基准内容 | 保留的分析能力 | 校正与验收规则 | 系统归属 |
|---|---|---|---|
| 数据护照 | 最新有效值、变化、判断 | 每项保留品种/合约、单位、观察日期、采集时间、频率、同口径比较、来源；没有实时数据时不得称为最新成交 | collectors → macro/technical/positioning features → snapshot |
| 非农数量、工资、修订 | 区分就业韧性与工资通胀 | 当前 BLS vintage 可以计算新增就业，不能推断旧 vintage 修订；预期与首次发布值须独立证据；一次数据不等于彻底否定趋势 | BLS collector、employment feature |
| 2Y/10Y/30Y 与实际利率 | 短端政策重定价 vs 长端冲击 | 同日名义利率减 BE；DFII10 独立展示；异时点相减不能用于确认同步冲击，更不能单独证明黄金反弹原因 | macro feature、macro agent |
| CFTC | Long/Short/Net/OI 的变化构成 | futures-only 与 combined 分列；9/1 持仓不反映 9/4 非农后交易；减仓支持去杠杆判断，不能证明某位官员讲话是唯一原因或“首次确认” | positioning collector/features/agent |
| GLD | 份额与持金量的变化 | AUM 变化不是资金流；单一 GLD 不是全球 ETF；份额增加不证明买方身份、买入时点或特定价位承接 | official ETF collector/feature |
| 油价 | 通胀与利率传导 | EIA/FRED 现货有发布滞后，不能冒充 Brent/WTI 最新期货结算；上涨还可能经增长/避险通道影响黄金 | FRED、formal oil、risk |
| TGA、准备金、RRP、走廊 | 边际流动性与融资危机区分 | TGA 日值与周均分列；WRESBAL/WTREGEN 原始百万统一转换十亿；时间窗不一致不做机械净额归因 | FRED/Treasury → macro |
| HY OAS | 检查信用风险是否共振 | 范例 2.66% 是 9/2 值；实测 CSV 9/3 为 2.65%，始终按实际观察日期显示 | FRED → macro/risk |
| 状态机、关键位 | 前后状态与升级/失效条件 | 唯一权威为验证后的 Gold canonical chain；不复制 S5、0.85、4200 等参数；4330—4350 与 4200 的软硬条件必须有优先级 | Gold Policy、technical feature |
| 三路径 | 主路径、反向路径、触发与反证 | 没有校准依据不填写 50/30/20；条件情景不是统计预测；不从正 GEX 推断方向 | coordinator、CME、report |
| 下周事件 | CPI/PPI/FOMC 的观察顺序 | 官方日历、原时区与北京时间；无法自动采集的日历明确缺失，不硬编码本周日期为常驻事实 | official events/news |
| CME（系统增量） | Call/Put/OI/Gamma/Pin/支持阻力/到期/Block/PNT | 保留 PRELIM/FINAL、实际计算方法、原 PDF lineage；GC 执行价不等同 XAUUSD；PNT 不等于 Block，0 不等于已验证没有交易 | 既有 cme_download → parse → ingest → option_wall |

## 已核验的一手来源

- [BLS 2026-09-04 就业公告](https://www.bls.gov/news.release/archives/empsit_09042026.htm)：非农 +162k、失业率 4.1%、参与率 61.6%、工资 MoM 0.3%/YoY 3.1%，前两月合计修订 +55k。
- [CFTC combined 年度文件](https://www.cftc.gov/files/dea/history/com_disagg_txt_2026.zip)：9/1 MM 净多 140811、OI 578926；当前系统原仅期货对应 136771 / 415196，差异来自口径。
- [State Street GLD 历史份额](https://www.ssga.com/library-content/products/fund-data/etfs/us/navhist-us-en-gld.xlsx)、[SPDR 官方历史持仓](https://api.spdrgoldshares.com/api/v1/historical-archive?exchange=NYSE&lang=en&product=gld)：8/28→9/3 份额 365.3M→369.2M、持金 1042.36→1053.48 吨；但新增披露 9/4 份额 368.7M，较 9/3 减少 0.5M，9/3 持金较 9/2 减少 3.14 吨。累计增配与最近赎回可以并存，不能据前一窗口断言最新有 ETF 承接；份额与持金观察日期不同，分别分析。
- [FRED WTREGEN](https://fred.stlouisfed.org/series/WTREGEN)、[HY OAS](https://fred.stlouisfed.org/series/BAMLH0A0HYM2)：周均口径、真实观察日期。
- [BLS 九月日历](https://www.bls.gov/schedule/2026/09_sched.htm)、[Federal Reserve FOMC 日历](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)：PPI 9/10、CPI 9/11、FOMC 9/15—16。

Reuters 用户给定链接在本机工具中尚未取得完整可读取正文；4419.09、4364.99 等仅作待核对外部报价，不写入系统事实。独立 OTC 源报价差异应公开展示，不以篡改数据使其等于范例。

## 集成契约与兼容性

现有任务主链不变。新增官方数据通过 macro_collect 采集并归档，纯 feature 附加到当次宏观/分析快照；source_refs 与 input_snapshot_ids 一起纳入内容哈希。报告消费快照与已完成的 AgentOutput，不重新请求源、不手工拼入本次范例数值。

新研究报告以显式版本/输入开关启用；旧快照继续使用旧 renderer，Gold v1/v2 已落盘报告与 verifier 不变。综合报告可解释已验证模块及冲突，同时保留正式状态不可用、PRELIM、陈旧数据与发布阻断。研究信息充分与获准输出强方向是不同验收项。

BLS 达到日请求额度时，先检验本次 storage 的有效原始归档，再调用现有 FRED 官方 API 镜像；保留原始失败、真实来源、采集日期与观察月份。日历使用官方 FRED 的 CPI/PPI 日期及 Fed 的 FOMC 日期，只提供日期精度；排期事件不混入已发生事件。Treasury 官方名义/TIPS 收益率补充最新共同观察日。

Dagster 的 canonical composite 使用现有 worker 入库与报告登记逻辑；新任务必须同时拥有 AgentOutput、报告文件和产物登记。旧任务 blueprint 没有 report_render 节点时，登记到该任务现有 strategy_card 步骤。不得靠手工回填旧 run 获得验收结果。

验收包括解析边界、公式与时间对齐、不变性、受影响分析回归、真实 No-Jin10 新运行与重复运行、产物字段/来源审阅以及历史哈希保持。尚未完成的验收不得被本文件描述为完成。

## 本次本地验收证据（2026-09-06）

完整候选两次运行 `4926e733-4a7f-4735-a24e-f3f8fd6a976c`、`078317fa-4402-4be4-90be-37701d104935` 均19/19步骤成功，9个模块输出与9个产物经API回读，金十引用为0。13节Markdown与JSON可精确重放，历史产物哈希不变。分析全回归1250项通过，新宏观passport及API定向84项通过；集合不相加。

新研究宏观Agent只消费fresh且lineage verified的数据护照，LLM不能覆盖事实数值；原快照路径继续兼容。GLD自动展示周窗口与最新单日变化；IORB引用绑定到所选观测。Gold影子决策缺少前序仍blocked，不自动初始化，不复制范例S5。CME PRELIM、DXY强方向时效、consensus/vintage/FedWatch/日程时钟缺口均继续显式展示。

本地证据在相邻workbench的 `gold-daily-quality-20260906/`。本次未提交、公开发布或迁移运行目录，重复实跑不等于长期生产可用性证明。

## 继续优化：项目指标与新闻链路

上面的运行证据对应首版报告，不表示以下能力此前已经完成。用户继续要求各模块实质优化后，本轮范围为：

| 层 | 本轮产出 | 使用边界 |
|---|---|---|
| 采集/解析 | Treasury 3M、BLS 发布原文/历史版本、保留重复采集的新闻上下文 | checkpoint 只标识新增；不删除当前窗口已知新闻；失败响应归档 |
| features | 2Y−3M、10Y−2Y 两腿与共同窗口、SOFR−IORB/EFFR−IORB 历史交集、前 5/20 个完整交易日区间 | 各序列最新点与共同观察日分别保留；前期区间排除最新日，避免用突破后的极值定义突破前边界 |
| 分析 | 主导、确认、反证、结构约束分开；就业修订与行业证据、ETF 日/周分化、新闻证据范围 | 同一利率家族不重复计权；RSI 和正 GEX 不单独反转方向；没有新闻全文就不声称全文核验 |
| 综合 | 既有 coordinator 中的研究裁决、动态条件情景、同源策略卡片 | 研究裁决不是第二个 Gold 状态权威；覆盖分数不是预测概率；缺前序仍不产生正式 S 状态 |
| 报告 | 项目框架、因素裁决、相关新闻及来源覆盖，与原有就业/宏观/资金/CME/技术章节一同渲染 | section 数量不作为质量指标；fact_review 的引用检查不能代替事实逐句核验 |

2Y−3M 是项目期限价差；正负及收窄必须由两腿解释，不能直接命名为政策转向。Fed 的近端远期利差使用六个季度后的隐含 3M 利率减当前 3M，定义与该项目指标不同。[Federal Reserve](https://www.federalreserve.gov/econres/notes/feds-notes/dont-fear-the-yield-curve-20180628.html)

准备金数量与融资价格共同判断。EFFR 相对 IORB 的变化可提供准备金条件线索，单个价差点不能确认系统性融资危机。[Federal Reserve Bank of New York](https://libertystreeteconomics.newyorkfed.org/2022/10/measuring-the-ampleness-of-reserves/)

概率模块另行纠错：OI 是未平仓合约数量，OI 占比不是价格到达概率；delta 的到期价内近似也不能直接冒充触及概率。CME 期权结构可用与 FedWatch 采集可用分别报告。[CME OI 定义](https://www.cmegroup.com/trading/about-volume.html)、[CME Delta](https://www.cmegroup.com/education/courses/option-greeks/options-delta-the-greeks)

本轮最终实跑证据在完成新任务后追加；不能沿用首版 run 的通过结果证明新代码已经运行。

## 2026-09-08：模块、新闻与观察报告验收

本轮按六个数据域处理：行情技术、宏观流动性、就业工资、CFTC/ETF、CME、新闻日程。底层新增五个季调就业行业序列；FRED两个历史版本核验6—7月非农修订合计+55千人。重点新闻保留Waller与Warsh官方讲话全文，媒体标题/摘要单列，避免把Goldman误归黄金，也不因checkpoint已见过新闻就清空分析上下文。

2Y−3M、10Y−2Y、融资利差均进入特征与综合裁决；利率同家族不重复投票，跨日现货不冒充同窗口确认。CME保留Black-76模型与推导参数审计；赔率不再用OI占比或触及近似冒充到期概率。研究阶段与动态价位情景进入同源报告/策略，正式Gold缺前序仍shadow blocked。

最新真实run `075bce98-5159-4fb3-ab0d-983cd7edd029`：19/19步骤成功，9个主要分析/校验输出加3个降级输出，9个RunArtifact。来源返回485条新闻及日程记录，去重后6条官方确认事件、143条候选；重点展示8条，其中2篇官方讲话全文。该计数不是485篇独立新闻全文。16节Markdown/JSON精确重放、API/manifest哈希和9份旧产物不变性通过。

fallback的身份不再修改输入snapshot_id，严格lineage校验保留。显式daily_research.v1观察报告通过原有sink登记为`observation_report:<run>`，partial/observe/publish_allowed=false；API及页面能阅读正文，保留非权威警告，旧bare宏观/CME入口保持兼容。旧非研究blocked结果仍不进入此登记分支，不将观察结果写成accepted final。

最终分析回归1274通过，worker相关68通过，API相关84通过，最后renderer定向16通过；测试集合不相加。130个Python候选文件Ruff与diff检查通过。服务重启后浏览器确认16节正文可见、无页面错误、无错误的缺失artifact警告，`/health`正常。完整证据见相邻workbench `gold-daily-quality-20260906/acceptance-20260908.json`。

剩余外部限制：FedWatch公共API实测401、部分新闻仅摘要、非农市场预期未取得、BLS HTML/日历403导致精确发布时刻缺失、同步事件前后行情窗口缺口。SOFR/EFFR仍截至9/3，纽约联储公共接口也相同；报告保留有日期的历史利差，不放宽时效或据此确认今天融资状态。官方日程按来源的日期精度展示。

本轮交付为本地代码及真实运行/页面验收，未提交、推送、部署、启用timer或迁移运行目录。

## gold_workflow.v2：主 Skill、领域计算与最终解释

用户新增流程由 `.agents/skills/gold-market-analysis` 编排四个领域 Skill；执行入口继续为 `/api/tasks/premarket`，不新增任务调度器。数据与规则进入版本化 `gold_workflow.v2` 快照，报告版本 `2.1.0` 按数据护照、摘要、前次变化、因子表、宏观、资金、状态、关键位、三路径、执行环境、风险、综合解释、溯源的顺序输出。没有该版本标记的旧快照保留旧报告渲染。

| 处理层 | 产出与责任 |
|---|---|
| collectors/parsers | 原始 Treasury/FRED/就业/CFTC/ETF/CME、新闻、XAU 日线及可选 quote/4H/1H/15m/5m 原始响应 |
| features/research | 时间护照、官方 TIPS 优先研究口径、三段曲线、月度频率、同窗口资金分类、关键位生命周期、质量门与场景规则分数 |
| 领域 Agent | 宏观、期权、风险、技术、资金、新闻、赔率分别给事实、限制、方向证据；同一数据家族不重复投票 |
| coordinator | 先按已锁定规则汇总，再经现有 LLMGateway 解释主导因素、反证、状态限制及共振条件；不能改变 bias/confidence/正式状态/来源；失败显式 rule_fallback |
| renderer/output | Markdown/JSON 和策略卡消费同一 workflow；观察报告继续保留 publish_allowed=false 等实际质量门结果 |

研究 `REAL10Y` 优先官方 DFII10，只有同期组件可验证时才回退估算。这个新增研究选择不改既有正式 Gold Policy 的派生实际利率契约。研究 S1—SX 是候选假设，正式前序缺失时 current state 不由 Skill 初始化。

关键位来自已有价格窗口，旧窗口退出标 Stale，过期合约标 Invalidated；同一天重复采集不是第二次价格确认。CME 本身采用 Call/Put 正值暴露量相减，signed Put 负值只能相加。买入 Call 和 Put 自身 Gamma 都非负；符号是持仓假设而非已知做市商仓位。[CME Gamma 说明](https://www.cmegroup.com/education/courses/option-greeks/options-gamma-the-greeks)

场景类别基准权重为 35/25/20/15/5。数据覆盖和方向覆盖分列；有 OI/新闻但未证实方向时记 direction_unavailable，保留结构约束但不伪造中性票。仅可评分输入按类别权重乘方向覆盖归一；缺失降低覆盖置信度。融资信用在数量背景与同期融资/信用价格共同可用时纳入宏观家族；油价/BE 的机会成本传导归属实际利率，不重复加票。中性输入分配区间/上行/下行 50/25/25，方向输入为 20/60/20（或镜像），混合信号线性插值。这是版本化研究排序规则，未经统计校准；覆盖置信度也不是预测正确率。

前序对比从严格更早且成功的 DB 快照记录解析，并复用已有文件/哈希权威校验，不从文件修改时间或自由文本判断前序。同观察日数值变化标 revision；该研究比较不会更新 canonical Gold predecessor。

执行卡只有在现货报价及各周期闭合 K 线均通过时序与新鲜度检查时展示近期结构；短窗收盘方向、五根 K 线区间突破是结构代理，不等于完整 swing BOS、CH、楔形或二次入场。未实现模式显式列缺口，不自动下单。总 Agent 的证据 ID 校验和数值待核验标记不等于对全部自然语言逐句核验。

本轮新代码的真实运行验收另记于 workbench `gold-skill-workflow-20260908/`；旧 run 的成功不作为该版本已实跑的证明。

总 Agent 输出不符合 JSON 结构或证据 ID 目录时，最多一次格式修复，每次均通过现有 Gateway 审计；模型不同意规则或提出新假设不触发修复。仍不合格或请求失败则保留 rule_fallback。模型与 reasoning 由当前运行配置决定；已观察到高推理请求超过 90 秒，单次等待上限为 180 秒。

用户进一步明确最终 Agent 不应受推理方式限制。`research_synthesis.v2` 开放独立研判、模块质疑、替代假设与反证更新；只保留 JSON 结构、证据 ID、来源和系统写入边界。取消词语/数字白名单作为整段拒绝条件，新增数值标为模型待核验提及，不自动进入 facts/features/关键位/正式状态；已有数值出现也不等于句子已逐项核真。总报告摘要优先展示模型独立判断，规则基线单列供对照。


## 2026-09-08：gold_workflow.v2 与开放总 Agent 最终验收

本地主链 run `0b7007f7-f373-4fd3-a9d9-ca790b43f075` 19/19步骤成功，12个主要/校验/降级 AgentOutput、9个登记产物。采集截止 `2026-09-08T05:15:40.777931+00:00`，现货报价4428.21468、报价时刻05:14 UTC；Jin10引用为0。实际总Agent经既有Gateway调用成功，审计 `6ab95b93-8ef0-4dd7-b143-e978680ed788`，返回 research_synthesis.v2 全部9字段。模型可以不同意规则排序、质疑模块和提出替代假设；系统仅保护事实来源、格式与正式写入边界。

开放模型前一轮发现的宏观口径冲突经代码核实并修正：v2宏观评分、driver、阶段分类及policy均复用已选择的官方TIPS（本次2.43%、变化+0.01个百分点），缺失不退回旧计算；共享分类器默认参数保留legacy行为。

最终analysis全回归1298通过，宏观/项目指标定向70通过，开放综合与renderer16通过；集合有重叠，不相加。13节Markdown/JSON精确重放、manifest/registry哈希、21份历史产物不变性、报告API和浏览器正文/无页面错误检查全部通过。证据在workbench `gold-skill-workflow-20260908/acceptance.json`。

仍为Partial观察报告，正式Gold状态不可用。FedWatch/就业consensus缺失、部分新闻只有摘要、CME PRELIM和估算到期、融资与信用观测滞后仍显式保留；GDPNow、IAU/WGC及完整swing模式producer尚未实现。数值提及筛查不等于自然语言逐句核真。此次完成本地实现及实际运行验收，未commit/push/deploy、新启timer或迁移运行目录。
