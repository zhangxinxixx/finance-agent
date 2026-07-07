# Figma Make 代码审查报告

> 历史审查说明：本文是 2026-05-17 针对早期 Figma Make 导出的审查记录。2026-05-27 之后，当前视觉迁移以 `docs/frontend/finanalytics-pro-design-system/FinAnalytics_Preview.html` 和 Task P0-09 为准；本文中的 Tailwind 4、直接迁移 ui 组件、Figma Make 截图验收等表述仅保留为历史背景，不可覆盖当前 `apps/frontend-web` 的 Tailwind 3.4 与 P0-09 设计系统映射口径。

> 审查目标：`docs/frontend/figma-make/`
> 审查日期：2026-05-17
> 审查人：前端架构 Agent

---

## 1. 代码结构总览

```
figma-make/
├── src/app/
│   ├── App.tsx                    # 主壳 (useState 视图切换 + 三栏布局)
│   ├── components/
│   │   ├── Sidebar.tsx            # 左侧导航 (9 项菜单 + Logo + 底部状态)
│   │   ├── Header.tsx             # 顶部 Header (面包屑 + 搜索 + 状态 + 用户)
│   │   ├── RightPanel.tsx         # 右侧面板 (风险控制 + Market Bias + SourceTrace)
│   │   ├── dashboard/
│   │   │   ├── DashboardView.tsx  # 总览 (SummaryCards + Macro + CME + Strategy)
│   │   │   ├── SummaryCards.tsx   # 顶部摘要卡片行
│   │   │   ├── MacroLiquidity.tsx # 宏观流动性面板
│   │   │   └── CMEOptionsPanel.tsx# CME 期权面板
│   │   ├── DataIngestionView.tsx  # 数据接入页
│   │   ├── EventFlowView.tsx      # 事件流页
│   │   ├── MarketMonitorView.tsx  # 市场监控页
│   │   ├── CMEOptionsView.tsx     # CME 期权结构页
│   │   ├── ReportsView.tsx        # 报告中心页
│   │   ├── KnowledgeBaseView.tsx  # 知识库页
│   │   ├── AgentTasksView.tsx     # Agent 任务页
│   │   ├── SettingsView.tsx       # 设置页
│   │   └── ui/                    # 48 个 shadcn/ui 组件（完整）
│   └── styles/                    # theme.css, globals.css, tailwind.css, fonts.css
├── ui_mockups/                    # 9 张页面原型图
├── previews/                      # 4 张预览截图
└── package.json                   # Vite + React 18 + Tailwind 4 + shadcn + Recharts + MUI
```

**总文件数**：66 个 TSX 文件
**代码总量**：~3,000 行 TypeScript (含 shadcn/ui boilerplate)
**页面组件**：9 个完整页面视图
**UI 组件**：48 个 shadcn/ui 基础组件（Radix + CVA + Tailwind 4）

---

## 2. 可保留内容

### 2.1 Shell 布局结构 ✅

| 组件 | 保留原因 | 保留方式 |
|------|----------|----------|
| `App.tsx` 三栏布局 | 暗色金融风格正确，flex 布局合理 | 抽取为 `AppShell`，替换 useState 为 React Router |
| `Sidebar.tsx` | 导航项完整，激活态样式好 | 重命名为 `AppSidebar`，硬编码颜色改为 CSS Token |
| `Header.tsx` | 面包屑 + 搜索 + 状态指示器模式正确 | 重命名为 `AppHeader`，抽取状态指示器为 `StatusIndicator` |
| `RightPanel.tsx` | Risk Controls + Market Bias + SourceTrace 三段式合理 | 重命名为 `ContextRightPanel`，硬编码数据改为 props |

### 2.2 Dashboard 子组件 ✅

| 组件 | 保留原因 |
|------|----------|
| `DashboardView.tsx` 布局 | 4 段垂直布局清晰 (SummaryCards → Macro → CME → Strategy) |
| `StrategyCard` 内联组件 | trigger/invalid/risk_points 四栏结构完全符合需求 |
| `SummaryCards.tsx` | 顶部 KPI 卡片行，这是 Dashboard 的标准模式 |

### 2.3 shadcn/ui 组件库 ✅

| 组件 | 说明 |
|------|------|
| `ui/` 目录 48 个组件 | 可直接整体迁移到正式项目 |
| Radix UI 依赖 | 已配置完整的 `@radix-ui/*` 依赖树 |
| CVA + clsx + tailwind-merge | 标准 shadcn 工具链 |

### 2.4 样式系统 ✅

- `theme.css`：完整的 shadcn 主题变量（light/dark），当时面向 Tailwind 4 项目；当前 Tailwind 3.4 不直接采用
- `tailwind.css`：Tailwind 4 的 `@import "tailwindcss"` 入口，当前仅作历史参考
- 暗色主题：组件中使用的 `#080d1a`, `#0b0f1e`, `#1a2040` 等颜色是合理的金融深色方案

### 2.5 设计原型参考 ✅

- `ui_mockups/` 9 张页面原型图，可直接作为 Playwright 视觉对比基准
- `Guidelines.md` 模板可用于填写正式设计规范

---

## 3. 必须重构内容

### 3.1 硬编码业务数据 ❌ — 最严重问题

**问题文件**：所有页面组件

```
❌ RightPanel.tsx:33-39    → const riskPoints = [...]  硬编码风险数据
❌ RightPanel.tsx:41-46    → const sourceLogs = [...]  硬编码数据源日志
❌ DataIngestionView.tsx:3  → const sources = [...]    硬编码数据源列表
❌ DashboardView.tsx        → 硬编码策略卡 trigger/invalid/risk
❌ SummaryCards.tsx         → 硬编码指标数值
❌ MarketMonitorView.tsx    → 硬编码实时报价
```

**修复方案**：
1. 所有数据移到 `src/mocks/*.json`
2. 所有组件通过 props 接收数据
3. 创建 `src/adapters/api.ts` 统一 fetch 层
4. Dashboard 加载流程：`API adapter → mock fallback → skeleton`

### 3.2 无路由系统 ❌

```tsx
// ❌ 当前：useState 切换
const [activeView, setActiveView] = useState<ViewId>("dashboard");

// ✅ 目标：React Router
<Route path="/dashboard" element={<DashboardPage />} />
<Route path="/data-ingestion" element={<DataIngestionPage />} />
```

### 3.3 颜色硬编码 ❌

几乎所有组件使用 inline style 而非 CSS Token：

```tsx
// ❌ 当前
style={{ background: "#0b0f1e", borderRight: "1px solid #1a2040" }}

// ✅ 目标
className="bg-sidebar border-r border-sidebar-border"
```

### 3.4 缺失 SourceTrace 组件 ❌

当前只有 `RightPanel.tsx` 内有 sourceLogs 硬编码列表。需要抽取为独立复用组件：
- 每个分析页面底部必须显示数据来源
- 包含：source name / date / file / model version / snapshot_id

### 3.5 缺失状态处理 ❌

| 缺失状态 | 影响页面 |
|----------|----------|
| Loading skeleton | 所有动态加载页 |
| Empty state | Data Ingestion, Market Monitor |
| Error state | 所有 API 请求页 |
| Unavailable 标记 | Options, Macro |
| Stale data badge | 所有数据展示 |

### 3.6 内联样式过多 ❌

图 Make 生成代码使用 100% inline `style={{}}` 而非 Tailwind 类名。正式项目必须全部迁移到 Tailwind。

---

## 4. 不适合直接进主项目的原因

| # | 原因 | 影响 |
|---|------|------|
| 1 | **硬编码 Mock 数据混入组件** | 违反"前端不得补造业务结论"的 AGENTS.md 规则 |
| 2 | **无数据分层** | raw → parsed → features → outputs 链路完全缺失 |
| 3 | **无 API adapter 层** | 组件直接消费硬编码数据，无法对接后端 API |
| 4 | **无状态管理** | 没有 TanStack Query 缓存、revalidation、stale 策略 |
| 5 | **无路由** | useState 切换在 SPA 中是反模式 |
| 6 | **无 SourceTrace** | 违反"缺失数据必须 unavailable"的溯源原则 |
| 7 | **无测试** | 没有 Playwright 截图、组件测试、API mock |
| 8 | **技术栈不完全匹配** | 当前项目后端是 Python/FastAPI，前端需独立工程化 |

---

## 5. 迁移策略

```
Phase 0: 环境搭建
  → Vite + React + TypeScript + Tailwind + shadcn 项目脚手架
  → 迁移 ui/ 组件库（48 个 shadcn 组件）

Phase 1: Shell 重构 (AppShell)
  → AppSidebar + AppHeader + ContextRightPanel + React Router
  → 迁移主题 Token（theme.css → Tailwind 4 变量，当前仅作历史参考）
  → 创建 mock JSON 数据文件

Phase 2: P0 页面 (见 component-map.md + page-specs/*)
  → Dashboard + Data Ingestion + Market Monitor + CME Options

Phase 3: API 对接 + 质量
  → TanStack Query adapter 层
  → Playwright 视觉验收
  → 状态处理 (loading/empty/error/stale)

Phase 4: P1 页面 (占位)
  → Event Flow / Reports / Knowledge Base / Agent Tasks / Settings
```

---

## 6. 图 Make 组件 vs 正式项目组件对照

| Figma Make | 正式项目 | 状态 |
|------------|----------|------|
| `Sidebar.tsx` | `AppSidebar.tsx` | 重构 |
| `Header.tsx` | `AppHeader.tsx` | 重构 |
| `RightPanel.tsx` | `ContextRightPanel.tsx` | 重构 |
| `DashboardView.tsx` | `DashboardPage.tsx` | 重构 |
| `SummaryCards.tsx` | `MetricCardRow.tsx` | 重构 |
| `MacroLiquidity.tsx` | `MacroLiquidityPanel.tsx` | 重构 |
| `CMEOptionsPanel.tsx` | `CMEOptionsPanel.tsx` | 重构 |
| `StrategyCard` (内联) | `StrategyCard.tsx` (独立) | 抽取 |
| `DataIngestionView.tsx` | `DataIngestionPage.tsx` | 重构 |
| `MarketMonitorView.tsx` | `MarketMonitorPage.tsx` | 重构 |
| `CMEOptionsView.tsx` | `CMEOptionsPage.tsx` | 重构 |
| — | `SourceTrace.tsx` | **新增** |
| — | `StatusBadge.tsx` | **新增** |
| — | `RiskPanel.tsx` | **新增** |
| `EventFlowView.tsx` | — | P1 占位 |
| `ReportsView.tsx` | — | P1 占位 |
| `KnowledgeBaseView.tsx` | — | P1 占位 |
| `AgentTasksView.tsx` | — | P1 占位 |
| `SettingsView.tsx` | — | P1 占位 |
| `ui/*` (48 files) | `ui/*` (直接迁移) | 保留 |
| `styles/theme.css` | `styles/theme.css` (修改) | 修改 |
