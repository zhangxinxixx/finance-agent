# FinAnalytics Pro → 当前前端组件映射表

> 版本：P0-09 + visual refinement pass (2026-05-28)
> 视觉 source of truth：`docs/frontend/finanalytics-pro-design-system/FinAnalytics_Preview.html`
> 目标前端：`apps/frontend-web/`，Tailwind 3.4 + React 18

## 1. 映射原则

P0-09 起，新增视觉迁移以 `FinAnalytics_Preview.html` 的 class/style 和交互密度为准，但不得大段复制 HTML 或 mock 数据。正式项目应将重复结构沉淀到 `apps/frontend-web/src/components/shared/` 的 FinAnalytics shared components，再由页面消费 API/view model 数据。

旧 Figma Make 内容仍为历史参考，不作为当前执行入口。旧文档中关于直接迁移 Figma Make ui 组件、Tailwind 4 `@theme inline`、MUI/shadcn 批量迁移等说明不覆盖当前 P0-09 执行口径。

## 2. HTML Class / Style 到 Shared Components 映射

| Preview class/style/primitive | 当前或目标 shared component | 映射规则 | 状态 |
|---|---|---|---|
| `.card` | `FACard` | `--bg-card` + `1px solid var(--border)` + `4px radius`；作为所有 panel/card 基础容器 | 已有，作为主映射 |
| `.card-header` | `FACard` header / `FASectionHeader` | header 背景 `--bg-panel`，padding `8px 12px`，可带 accent bar 和 action | 已有，需按页面收敛 |
| `.card-body` | `FACard` body | 默认 `12px` padding；高密内容可传 `bodyClassName` 调整 | 已有 |
| `.card-accent-bar` / top `2px` accent | `FACard` / `FAMetricCard` | section header 左侧 `3px × 14px` 或 KPI 顶部 `2px` accent，颜色来自 brand/semantic/chart token | 已有，KPI 顶部 accent 可后续补齐 |
| `.status-pill` / `StatusPill({kind})` | `FAStatusPill` | tone 映射 `up/down/warn/info/dim/neutral`；`9px` uppercase、soft fill、semantic border | 已有，优先替代裸 `StatusBadge` 新用法 |
| `KpiCard(...)` | `FAMetricCard` | label/value/unit/delta/hint/trend/status；数值 mono `18px`；用于 dashboard/market/CME KPI | 已有，作为新视觉主 KPI |
| `.eyebrow` | `FASectionHeader` / `FACard` eyebrow | `9px` uppercase、tracking `0.08em`、`--fg-5` | 已有 |
| timeframe button group / filter row | `FAFilterBar` | panel surface、紧凑 gap、左右区；具体 button 仍由页面传入 | 已有 |
| tab buttons in DailyComposite | `FATabBar` | active `--bg-active` + `--brand-hover`；inactive `--fg-4`，hover `--bg-hover` | 已有 |
| Conviction numeric / progress | `FAConvictionBar` | 0-100 clamp，label uppercase，bar 使用 semantic tone | 已有 |
| `EmptyState()` | `FAEmptyState` | dashed border、center icon、短标题和说明；不复制 mock 文案 | 已有 |
| alert strip / risk warning inline block | `FAWarningBanner` | semantic soft fill + border；适合 PRELIM、风险、错误提示 | 已有 |
| `Pipeline` / `PipelineStage` | `FAPipelineStepper` | stage status 映射 `done/running/queued/error/unavailable`；保留 compact stage 卡片和连接线 | 已有 |
| queue popover task rows / runtime rows | `FARuntimeLog` | mono terminal surface、time/level/source/message 四类信息；适合 task log 和运行流水 | 已有 |
| source popover compact source item | `FASourceTraceBadge` | source + status + snapshotId，作为 compact trace badge；详情仍用 `SourceTrace` | 已有 |
| `.status-bar` / `.statusbar-*` | `DataStatusBar` + 后续 status bar shared shell | 保留现有数据状态来源，视觉向 Preview 底部 30px status bar 收敛 | 现有组件需后续视觉迁移 |
| `.right-panel` | 页面右栏 / 后续 `ContextRightPanel` | 300px、`--bg-panel`、left border、12px padding/gap；内容由页面 API 数据驱动 | 需后续统一 |
| `.num` | `fa-num` utility | mono、tabular numerics、tight tracking；价格/百分比/id/time 全部使用 | 需全局统一 |

## 3. Shared Components 逐项说明

| 组件 | P0-09 定位 | 迁移注意事项 |
|---|---|---|
| `FACard` | FinAnalytics Pro 基础容器，对应 Preview `Card`、`.card`、`.card-header`、`.card-body` | 页面不得重复写完整 card 样式；特殊布局通过 `className/headerClassName/bodyClassName` 扩展 |
| `FAStatusPill` | 新视觉状态 pill，对应 `.status-pill` | 新增视觉迁移优先使用；数据状态语义仍来自后端/status normalize |
| `FAMetricCard` | 新视觉 KPI 卡，对应 Preview `KpiCard` | 比旧 `MetricCard` 更贴近 Preview；适合逐页替换 dashboard/market KPI |
| `FASectionHeader` | 页面/section 标题结构 | 用于替代页面中重复的标题、eyebrow、description、action 组合 |
| `FAFilterBar` | 筛选、时间周期、工具按钮容器 | 只管布局和 surface，不承载业务筛选逻辑 |
| `FATabBar` | 视图切换和报告详情 tab | 只处理受控 tab UI，不在组件内绑定路由或请求 |
| `FAConvictionBar` | conviction / confidence / progress 类横向强度条 | 输入必须是已有字段或 view model 字段，不在组件内计算策略结论 |
| `FAEmptyState` | 空态展示 | 缺失数据文案应明确 `unavailable` / `暂无数据`，不伪造占位值 |
| `FAWarningBanner` | PRELIM、风险、错误、延迟提示 | tone 对应 warn/down/info，不能用红黄绿表达笼统好坏 |
| `FAPipelineStepper` | pipeline stage 可视化 | 对应 task_runs/task_steps、collector/parser/feature/report 阶段，只展示已有状态 |
| `FARuntimeLog` | 运行日志和任务队列列表 | 适合 Agent Tasks、Data Ingestion、status bar popover |
| `FASourceTraceBadge` | compact source trace chip | 适合 card header、summary row；完整溯源仍用 `SourceTrace` |

## 4. 现有组件兼容映射

| 现有组件 | 当前角色 | P0-09 映射策略 |
|---|---|---|
| `MetricCard` | 旧 dashboard KPI 组件，使用 `finance-*` token | 保留兼容；新页面迁移优先使用 `FAMetricCard`，后续可逐步替换 |
| `StatusBadge` | 旧通用数据状态 badge，绑定 `available/partial/error/unavailable/info/neutral` | 保留数据状态语义；新视觉或 uppercase pill 使用 `FAStatusPill` |
| `SourceTrace` | 完整数据溯源展示 | 不替代；与 `FASourceTraceBadge` 分工，详情区域继续用 `SourceTrace` |
| `DataStatusBar` | 当前全局数据状态条，消费 `useDataStatus()` | 数据来源保留；视觉后续向 Preview `.status-bar` / `.statusbar-*` 收敛 |
| `PipelineStepper` | 旧 pipeline stepper | 保留兼容；FinAnalytics Pro 新视觉统一走 `FAPipelineStepper` |
| `EmptyState` / `ErrorState` | 旧空态/错误态 | 保留兼容；FinAnalytics Pro 新视觉统一走 `FAEmptyState` / `FAWarningBanner` |

## 5. Page / Shell 映射

| Preview 区域 | 当前前端目标 | 映射要求 |
|---|---|---|
| `Sidebar` / `.sidebar` / `.nav-item` | `AppSidebar` | 200px、active left border、brand dim active bg；不得恢复旧入口 |
| `Header` / `.header` / `.search` | `AppHeader` | 44px、breadcrumb/search/status/user；搜索可先保留静态或既有能力 |
| `.app-content` | 页面根容器 | 深蓝 canvas，可保留克制 radial glow；不得影响 API 数据流 |
| `.right-panel` | 后续统一右侧上下文面板 | 300px，context-aware；页面无右栏时可隐藏 |
| `.status-bar` | `DataStatusBar` 后续视觉目标 | 30px 底部条，数据源、存储、last update、任务队列 |
| Dashboard `KpiCard` row | `FAMetricCard` grid | 使用 API/view model 指标，不复制 Preview mock 数据 |
| DailyComposite tabs / report summary | `FATabBar` + `FACard` + `FAConvictionBar` | 只复用结构，不把 demo 报告写死到前端 |
| Data Ingestion source table | `FACard` + `FAStatusPill` + `FASourceTraceBadge` + `FAPipelineStepper` | 状态来自 task/data source API，缺失保持显式 |
| Agent Tasks queue/log | `FACard` + `FARuntimeLog` + `FAStatusPill` | 任务状态来自 `/api/runs` 等后端接口 |

## 6. Status 语义映射

| 后端/现有状态 | 新视觉 tone | 说明 |
|---|---|---|
| `available` / `ok` / `success` / `done` / `LIVE` | `up` | 可用、成功、完成、在线 |
| `partial` / `PRELIM` / `warn` / `queued` / `PARTIAL` | `warn` | 部分可用、预备、排队、延迟 |
| `error` / `failed` / `down` | `down` | 错误、失败、不可达 |
| `running` / `syncing` / `info` / `connected` | `info` | 运行中、同步中、连接信息 |
| `unavailable` / `unknown` / empty | `dim` 或 `neutral` | 不可用或未知，必须显式展示 |

## 7. 不迁移 / 暂缓项

- 不迁移 `FinAnalytics_Preview.html` 的 mock 数据、React UMD、Babel、CDN lucide 运行方式。
- 不复制 `knowledge-base.html` 为全局主题；它只服务 Knowledge Base 页面参考。
- 不按旧 Figma Make 的 Tailwind 4 `@theme inline` 写法改造当前工程。
- 不新增第二套 frontend entrypoint，不恢复 `apps/frontend/` 或早期 `dashboard.html`。
- 不在 shared component 内实现业务 adapter、hook、策略计算或数据补造。

## 8. Phase 1 页面一致性要求

即使页面内部模块仍在分批迁移，Phase 1 也要求所有现有路由先满足以下一致性：

- 统一通过 `AppShell` 进入同一工作台外壳
- 页面根容器统一使用 `finance-page-shell`
- 通用 panel 统一落到 `FACard` / `finance-panel` / FinAnalytics shared primitives
- 顶部标题区、右栏、底部状态条不允许继续维持旧占位风格
- `PlaceholderPage` 也必须属于同一产品视觉，而不是默认空白页
