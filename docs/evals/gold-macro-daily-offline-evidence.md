# 黄金宏观日报：离线证据接线边界

本批基于 PR #139 的研究质量门，只修复已有输入与可读交付。宏观研究不要求 CME 可用；正式发布和交易资格继续由原有门禁决定。没有真实模型对照时，研究质量仍为 `not_evaluated`。

## 事件、预期与响应

`macro.data.release_events` 的每条记录包含稳定的 `event_id`，以及 `actual`、可选 `consensus`。

每份观察需要：`status=available`、`indicator`、`reference_period`、`measure`（例如季调月率与非季调年率必须分开）、`unit`、有限数值 `value`、`observation_date`、`published_at`、`retrieved_at` 和 `source_refs`。`evidence_kind` 分别为 `official_release_value`、`pre_release_consensus`；实际发布的来源须标注 `source_type=official`。引用绑定原始路径、来源 URL、接收时刻和归档哈希。输入校验器在独立 storage_root 核对原始文件。

只有同指标、参考期、口径、单位，且预期的发布时间和接收时间都严格早于实际发布，程序才计算 actual − consensus。百分率之差以百分点表示。缺少或迟到的预期只取消预期差，不删除有效发布事实。相同事件身份的多份未裁决版本隔离，不任择一份。

现有 `official_event_snapshot.v1` 继续提供合法事件及其严格配对的价格响应；标题不是数值来源。`macro_causal.engines.releases` 将这些信息送到原研究输入链。日频指数变化、FedWatch 分布和金美元窗口各自保留资格，不自动成为事件因果证明。

当前真实冻结样本缺少合格 PPI/零售发布原件和事前共识，因此仍为 unavailable。本批没有新增这些源的采集，也未把事后审阅数字填入原输入。接线及合成边界回归不代表真实事件链已完成验收。

## FedWatch 与 PA

worker 与离线归档复用纯 `build_fedwatch_view`。过期分布保留会议、来源时刻和历史对比，当前重定价字段及资格关闭。已缓存的 fresh view 在新截止时点重新检查时效。实际模型输入仍受200000字符上限保护。

`gold_macro_daily` 使用 `macro_daily_native_bars.v1` 投影：完整原生OHLC保留在冻结快照；有效周期向模型提供最近32根，以及已投影PA的枢轴、事件、确认时刻前后各2根。不改变任何选中行的时钟、价格或缺失值；不合格周期不因投影变为合格。`bar_projection` 记录原数量、提供/未提供的零基闭区间、完整行列表SHA-256、快照路径和未匹配的PA时刻。`bar_count`、连续性和确定性PA仍描述原完整序列，不能从选中片段重新推断完整路径或声称模型读过未提供的历史。

`decision_tables.v3` 复用现有共享表格：事件由 `events_table` 表达，共有的 actual/consensus/response 状态只存一次，每个事件身份、发布时间、独立来源和例外值保留。已有列游程编码在确有节省时使用，不随总输入大小反复开关。来源目录保留提供的归档哈希及适配/解析/交易时段规则版本；完整路径与其他归档字段继续在冻结输入及来源manifest中解析。研究输入目标170000字符，为新事件和合格前序正文预留空间；超限明确拒绝，不提高硬上限或静默截断。

PA 的模型投影补充枢轴身份、规则确认时刻、归档接收所支持的可得时刻，并将事件严格匹配到同周期、方向、价位、枢轴时刻和确认时刻。早于可得时刻的距离只能作 `post_hoc_geometry`；没有接收记录不授予当时可用资格。原PA事件算法与历史快照不回写。

## 前序正文与交付

注册表读取同时核对正文哈希、生成时刻、报告/附件当前版本的创建与更新时间。截止后导入或修订的正文不证明截止前可知；没有历史版本记录时保守留缺。新 v4 日报消费前序时要求 `available_at` 和 `availability_basis=report_and_artifact_registry_revision`。旧格式仍可读取，不能借旧格式绕过新日报的时点资格。

不可用前序新增 `failure_category`：`database_unavailable`（注册查询或绑定快照查询失败）、`no_eligible_prior`（查询成功且没有匹配候选）、`body_unavailable`（正文不可读/不存在等）、`cutoff_or_version_rejected`（时点、版本、身份或质量不合格）。保留原 `reason_code`、细分拒绝计数与多类失败的 `failure_category_counts`，一并进入实际消息；数据库失败不解释为历史上没有报告。已有冻结失败对象在新投影中可补分类，不重连生产库，不回写旧对象。绑定快照查询失败时不悄悄选较旧正文。

原生审计附录可处理 CFTC unavailable 形状；正文范围说明区分“完整就业发布与审计材料缺失”和“部分历史FRED序列可用”。离线重渲染必须绑定原输入和原模型输出，修复后的新输入另存，不把新事实嫁接到旧模型正文。

## 验收限制

本批只允许本地隔离回放、合成失败边界、注册表/报告API的隔离回归。未新增采集、付费模型、生产数据库写入、调度或部署。新的完整模型报告、同类基准研究质量、生产网页贯通、工作日12:00运行和失败恢复，仍须分别取得后续授权与实际证据。
