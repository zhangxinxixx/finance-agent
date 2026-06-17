# FinAnalytics Pro 设计系统映射报告

> 版本：P0-09 + visual refinement pass (2026-05-28)
> 适用范围：`apps/frontend-web/` 当前 Vite + React 18 + Tailwind 3.4 前端主线
> 当前视觉 source of truth：`docs/frontend/finanalytics-pro-design-system/FinAnalytics_Preview.html`

## 1. Source Of Truth

P0-09 起，当前前端视觉迁移以 `docs/frontend/finanalytics-pro-design-system/FinAnalytics_Preview.html` 为唯一执行级视觉 source of truth。该 HTML 已包含 FinAnalytics Pro 的页面 shell、核心 CSS variables、卡片、状态、底部状态栏、右侧面板、数据密集表格和多页面示例。

`docs/frontend/finanalytics-pro-design-system/knowledge-base.html` 只作为 Knowledge Base 页面局部参考，不提升为全局主题，不反向覆盖 Dashboard、Market Monitor、CME Options、Reports、Data Ingestion、Agent Tasks 等页面。

旧 Figma Make 内容，包括 `docs/frontend/figma-make/`、`docs/frontend/figma-make-review.md` 中的 Tailwind 4、`@theme inline`、直接迁移 ui 组件等内容，只保留为历史参考，不作为当前执行入口。后续实现不得从旧 Figma Make 目录恢复第二套前端入口。

## 2. 执行约束

- 当前工程使用 Tailwind 3.4，不采用 Tailwind 4 `@theme inline` 作为执行方案。
- Token 应落到 CSS variables，再通过 Tailwind 3 utilities、arbitrary values 或少量全局类消费。
- 页面迁移必须优先抽 shared components，不在页面里大段复制 HTML inline style。
- 缺失数据继续显式展示 `unavailable` / `partial` / `error`，不得为了视觉完整补造数据。
- 视觉迁移只改变展示层，不改变 API contract、adapter、hook、业务类型或前端数据计算边界。

## 3. Token 映射表

### 3.1 Surface / Border / Foreground

| FinAnalytics Preview token | 当前值 | 语义 | 当前工程映射建议 |
|---|---:|---|---|
| `--bg-app` | `#091527` | 应用画布、主内容底色 | 替换或对齐 `--finance-bg-root` |
| `--bg-panel` | `#0d1a2e` | sidebar、header、card header、status bar | 替换或对齐 `--finance-bg-surface` |
| `--bg-card` | `#12213a` | 卡片和 panel 主面 | 替换或对齐 `--finance-bg-card` |
| `--bg-card-inner` | `#16263f` | 输入框、嵌套单元、内层容器 | 新增或对齐 `--finance-bg-hover` 的更明确语义 |
| `--bg-hover` | `rgba(255,255,255,0.07)` | hover 面 | 保持 CSS variable，不展开为固定 Tailwind 色 |
| `--bg-active` | `rgba(96,165,250,0.18)` | active tab/nav/filter | 保持 CSS variable |
| `--border` | `#263a5b` | 默认边框 | 替换或对齐 `--finance-border` |
| `--border-strong` | `#42618d` | 表格分隔、强调分隔 | 替换或对齐 `--finance-border-subtle` |
| `--border-faint` | `rgba(255,255,255,0.07)` | 弱边框、badge 内层边 | 新增 CSS variable |
| `--fg-1` | `#f1f5f9` | 关键数值、价格、hero numeric | 替换或对齐 `--finance-text-primary` 的最高层 |
| `--fg-2` | `#e2e8f0` | 标题、card title | 替换或对齐 `--finance-text-primary` |
| `--fg-3` | `#a7b6cc` | 正文、默认值 | 替换或对齐 `--finance-text-secondary` |
| `--fg-4` | `#7f94be` | 次级文本、inactive nav | 替换或对齐 `--finance-text-tertiary` |
| `--fg-5` | `#60769e` | caption、label、meta | 替换或对齐 `--finance-text-muted` |
| `--fg-6` | `#40577d` | 极弱文本、微分隔 | 新增 CSS variable |

### 3.2 Brand / Semantic / Chart

| FinAnalytics Preview token | 当前值 | 语义 | 当前工程映射建议 |
|---|---:|---|---|
| `--brand` | `#3b82f6` | 主蓝、active border、连接状态 | 对齐 `--finance-accent` |
| `--brand-hover` | `#60a5fa` | active text、hover text | 对齐 `--finance-accent-soft` |
| `--brand-dim` | `rgba(59,130,246,0.15)` | active 背景 | 新增 CSS variable |
| `--brand-cyan` | `#06b6d4` | logo gradient partner、info 辅助 | 对齐 `--finance-cyan` |
| `--brand-gradient` | `linear-gradient(135deg,#3b82f6,#06b6d4)` | logo/avatar/少量品牌标识 | 保持 CSS variable |
| `--up` | `#10b981` | 上涨、看涨、成功、live | 对齐 `--finance-bullish` |
| `--up-soft` | `rgba(16,185,129,0.12)` | 看涨/成功软底 | 新增 CSS variable |
| `--up-border` | `rgba(16,185,129,0.25)` | 看涨/成功边框 | 新增 CSS variable |
| `--down` | `#ef4444` | 下跌、看跌、错误、destructive | 对齐 `--finance-bearish` |
| `--down-soft` | `rgba(239,68,68,0.10)` | 看跌/错误软底 | 新增 CSS variable |
| `--down-border` | `rgba(239,68,68,0.25)` | 看跌/错误边框 | 新增 CSS variable |
| `--warn` | `#f59e0b` | 延迟、排队、注意、PRELIM | 对齐 `--finance-warning` |
| `--warn-soft` | `rgba(245,158,11,0.10)` | 警告软底 | 新增 CSS variable |
| `--warn-border` | `rgba(245,158,11,0.25)` | 警告边框 | 新增 CSS variable |
| `--info` | `#06b6d4` | 信息、中性指标 | 对齐 `--finance-cyan` 或新增 `--finance-info` |
| `--info-soft` | `rgba(6,182,212,0.10)` | 信息软底 | 新增 CSS variable |
| `--chart-1` 到 `--chart-6` | amber / blue / green / red / violet / cyan | 图表序列色 | 对齐 Recharts palette |

金融语义色不得简化成“好/坏”。`up` / `down` 表示市场方向或数据状态，具体含义由业务文案和状态字段决定。

## 4. Tailwind 3.4 / CSS 变量映射

Tailwind 3.4 的执行方式应是：

- 在现有全局样式中声明 FinAnalytics Pro CSS variables。
- 在 shared components 中使用 `bg-[var(--bg-card)]`、`border-[var(--border)]`、`text-[var(--fg-2)]`、`rounded-[var(--radius-md)]` 这类 Tailwind 3 arbitrary values。
- 对重复结构保留少量语义类，例如 `fa-card`、`fa-card-header`、`fa-card-body`、`fa-num`，避免每个页面复制成段 className。
- 不引入 Tailwind 4 `@theme inline`，不以旧 Figma Make `default_shadcn_theme.css` 作为当前主题入口。

| 视觉语义 | CSS variable | Tailwind 3 消费形态 |
|---|---|---|
| app canvas | `--bg-app` | `bg-[var(--bg-app)]` |
| panel/header/status bar | `--bg-panel` | `bg-[var(--bg-panel)]` |
| card | `--bg-card` | `bg-[var(--bg-card)] border border-[var(--border)]` |
| nested fill | `--bg-card-inner` | `bg-[var(--bg-card-inner)]` |
| active | `--bg-active` | `bg-[var(--bg-active)] text-[var(--brand-hover)]` |
| title | `--fg-2` | `text-[var(--fg-2)]` |
| numeric primary | `--fg-1` | `text-[var(--fg-1)] fa-num` |
| caption/meta | `--fg-5` | `text-[var(--fg-5)]` |
| status up | `--up-soft` / `--up` / `--up-border` | `bg-[var(--up-soft)] text-[var(--up)] border-[var(--up-border)]` |
| status down | `--down-soft` / `--down` / `--down-border` | `bg-[var(--down-soft)] text-[var(--down)] border-[var(--down-border)]` |
| status warn | `--warn-soft` / `--warn` / `--warn-border` | `bg-[var(--warn-soft)] text-[var(--warn)] border-[var(--warn-border)]` |
| status info | `--info-soft` / `--info` | `bg-[var(--info-soft)] text-[var(--info)]` |

## 5. 字体规则

| Token | Preview 值 | 规则 |
|---|---|---|
| `--font-sans` | `Inter`, `SF Pro Display`, system, `PingFang SC`, `Microsoft YaHei` | 全局 UI、中文正文、导航、按钮 |
| `--font-mono` | `JetBrains Mono`, `SF Mono`, `Menlo`, `Consolas` | 价格、百分比、时间戳、ticker、snapshot/run id |
| `--text-9` | `9px` | uppercase eyebrow、status pill |
| `--text-10` | `10px` | meta、caption、status bar |
| `--text-11` | `11px` | 次级 UI label、正文小字 |
| `--text-12` | `12px` | 默认 body、nav、table cell |
| `--text-13` | `13px` | 强调正文 |
| `--text-14` | `14px` | section header |
| `--text-16` | `16px` | 模块标题 |
| `--text-18` | `18px` | KPI value |
| `--text-22` | `22px` | 页面标题 |
| `--text-28` | `28px` | hero numeric，仅少量使用 |

数值必须使用 mono + tabular numerics，建议统一类为 `fa-num`。状态 pill 和 eyebrow 使用 uppercase、`tracking-[0.08em]`、`text-[9px]`。

## 6. 间距与 Density

FinAnalytics Pro 是高密度金融终端，不走宽松 SaaS spacing。

| Token | 值 | 规则 |
|---|---:|---|
| `--space-1` | `2px` | 微间距、dot 文本间距 |
| `--space-2` | `4px` | pill padding、nav gap |
| `--space-3` | `6px` | 紧凑组件 gap |
| `--space-4` | `8px` | card header 垂直 padding、按钮 padding |
| `--space-6` | `12px` | card body、right panel gap |
| `--space-8` | `16px` | 页面 section 间距 |
| `--space-12` | `24px` | 大模块连接线、少量布局间距 |

卡片主体默认 `12px` padding；小型 nested card 可用 `8px` 到 `10px`；不要默认升级到 `16px+`。

## 7. Radius / Border / Shadow

| Token | 值 | 用途 |
|---|---:|---|
| `--radius-xs` | `2px` | tiny bar、small chip |
| `--radius-sm` | `3px` | status pill、tag |
| `--radius-md` | `4px` | 默认 card、button、input |
| `--radius-lg` | `6px` | icon container、pipeline stage |
| `--radius-xl` | `8px` | 少量空态/大容器 |
| `--radius-pill` | `999px` | dot、progress bar、avatar |

默认卡片是 `1px solid var(--border)` + `var(--bg-card)` + `4px` radius。常规卡片不使用大 shadow；popover/dropdown 可使用 `--shadow-popover`；策略高亮可以使用 `--shadow-glow-up` 或 `--shadow-glow-down`，但必须克制。

## 8. 组件规则

### 8.1 Card / Panel

- 基础结构：`fa-card` + `fa-card-header` + `fa-card-body`。
- 背景：card 使用 `--bg-card`，header 使用 `--bg-panel`。
- Header：`8px 12px` padding，左侧可带 `3px × 14px` accent bar。
- Body：默认 `12px` padding。
- Accent：只用于 dashboard KPI、关键金融结构或需要 scan 的卡片，不全量滥用。

### 8.2 Table

- 表头使用 `--bg-panel`、`--fg-5`、`9px` uppercase、`tracking-[0.08em]`。
- 表格 cell 使用 `11px` 到 `12px`，数值列使用 mono 并右对齐。
- 行分隔使用 `--border`；高密表格可用 `--border-strong`。
- Hover 只改变背景到 `--bg-hover`，不要位移、放大或重 shadow。
- 状态列必须使用 `FAStatusPill` 或现有 `StatusBadge`，不可裸色块。

### 8.3 Card 内指标 / Metric

- Label：`10px` uppercase、`--fg-5`。
- Value：`18px`、bold、mono、`--fg-1`。
- Unit / hint：`9px` 到 `10px`、`--fg-5`。
- Change：`10px` semibold，按 `up/down/flat` 绑定语义色。
- KPI 顶部可有 `2px` accent bar，使用 chart palette 或 brand/semantic token。

### 8.4 Status / Badge

- Status pill 规格：`inline-flex`、gap `4px`、padding `2px 6px`、radius `3px`、`9px` semibold uppercase、tracking `0.08em`。
- Tone 映射：`up`、`down`、`warn`、`info`、`dim`、`neutral`。
- `unavailable` 不能省略，使用 dim/neutral 视觉，文案必须显式。

### 8.5 Right Panel

- 宽度固定参考：`--rightpanel-w = 300px`。
- 背景：`--bg-panel`；左边框：`1px solid var(--border)`。
- Padding/gap：`12px`。
- 内容：适合 Market Bias、Risk Controls、SourceTrace、实时监控摘要、notes/insights stack。
- 设置类页面可隐藏 right panel，但不能把 right panel 业务计算搬到前端。

### 8.6 Bottom Status Bar

- 高度参考：`30px`，固定在 app shell 底部。
- 背景：`--bg-panel`；上边框：`1px solid var(--border)`。
- 内容：数据源状态、存储摘要、last update、任务队列入口。
- 数据源 dot 使用 `6px` 圆点；同步/运行中可 pulse。
- 交互 popover 使用 `--bg-card`、`--border`、`--shadow-popover`。
- 当前 `DataStatusBar` 可作为数据状态信息来源，但视觉应向 Preview 的 `status-bar` 结构收敛。

### 8.7 Filter / Tab

- Filter bar 使用 panel surface、`6px` radius、`12px × 8px` padding。
- Tab bar 使用 panel surface、`4px` radius、内部 `p-1`。
- Active tab 使用 `--bg-active` + `--brand-hover`。
- Inactive tab 使用 `--fg-4`，hover 到 `--bg-hover` + `--fg-2`。

### 8.8 Warning / Empty / Runtime Log / Source Trace

- Warning banner 用 semantic soft fill + semantic border，不使用纯色大背景。
- Empty state 使用 dashed border、`--bg-card`、centered icon；文案短句，不写解释性长段。
- Runtime log 使用更深 terminal surface，可用 `#07111f`，字体 mono `10px`。
- Source trace 必须保留 source、status、snapshot/run/artifact 等可追溯字段；视觉可用 compact badge，但信息不可丢。

## 9. Layout 规则

| 区域 | Preview 规则 | 当前工程映射 |
|---|---|---|
| Sidebar | `200px` 宽，`--bg-panel`，active 左侧 `2px` brand border | `AppSidebar` 后续视觉对齐 |
| Header | `44px` 高，breadcrumb/search/status/user | `AppHeader` 后续视觉对齐 |
| Main content | flexible，深蓝 canvas + 克制 radial glow | 页面容器视觉对齐，不复制 mock 数据 |
| Right panel | `300px` 宽，context-aware | `ContextRightPanel` 或页面级右栏后续统一 |
| Bottom status bar | `30px` 高，数据源 + queue | 由现有 `DataStatusBar` 向 `status-bar` 收敛 |

## 10. 暂不 1:1 还原项

- 不 1:1 还原 HTML 内所有 mock 数据、内联 style 和 demo state。
- 不把 `knowledge-base.html` 的页面风格提升成全局主题。
- 不采用 Google Fonts CDN 作为生产必选方案；字体加载策略由正式前端构建和部署策略决定。
- 不恢复旧 Figma Make 的 Tailwind 4 `@theme inline`、`default_shadcn_theme.css` 或第二套入口。
- 不强制立刻实现 light mode；Preview 的 `[data-theme="light"]` 可作为后续主题扩展参考。
- 不复制 Preview 中的 React UMD / Babel / CDN lucide 方案；正式项目继续使用当前 Vite + React + TypeScript + lucide-react。
- 不用视觉迁移改变 adapter/hook/types/page 的数据职责；前端仍只消费 API 和 view model。

## 11. Phase 1 落地边界

Phase 1 的目标不是一次完成所有页面，而是先把整站拉进同一套 FinAnalytics 工作台骨架。执行边界如下：

- 必做：
  - `AppShell / AppSidebar / AppHeader / ContextRightPanel / DataStatusBar` 视觉收敛
  - `finance-page-shell`、`finance-panel`、shared card/status/metric 体系统一
  - 所有已注册路由共享同一外层布局、padding、边框、背景和状态语言
- 可延后：
  - `Knowledge Base / Event Flow / Settings` 的专用页面布局
  - light mode
  - 设计稿中的 mock 数据、复杂图表动画、交互细节
- 禁止：
  - 为了先做重点页而让其他页面留在旧视觉岛
  - 新增第二套入口、临时 shell、临时主题
  - 在 shared primitives 里混入业务计算
