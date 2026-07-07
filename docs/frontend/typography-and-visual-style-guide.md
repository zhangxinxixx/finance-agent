# 前端字体与视觉风格开发规范

版本：2026-07-04  
适用范围：`apps/frontend-web/src` 当前 Vite + React 前端主线

本规范用于后续页面开发、组件改造和视觉修正。所有字体、字号、文字颜色、状态色和信息密度默认遵守这里，不再在页面里临时发明一套样式。

## 1. Source Of Truth

执行入口固定为：

| 文件 | 用途 |
|---|---|
| `apps/frontend-web/src/styles/finanalytics-tokens.css` | 全局颜色、字体、字号、间距、圆角 token |
| `apps/frontend-web/src/styles/finanalytics-typography.css` | 字体语义类和文字层级 |
| `apps/frontend-web/src/index.css` | 全局 shell、公共 layout、Tailwind arbitrary 兜底 |
| `apps/frontend-web/tailwind.config.js` | Tailwind 字体和 finance 色彩映射 |

规则：

- 页面和组件优先使用 token、`fa-*` 类和已有共享组件。
- 不直接写新的字体栈、原始 hex 颜色、随意字号。
- 若确实需要新增 token，先放到 `finanalytics-tokens.css`，再在组件里消费。
- 旧 Figma Make 或历史设计文档只作为参考，不覆盖当前 token。

## 2. 设计方向

系统定位是金融投研操作台，不是营销页或后台模板。

默认视觉方向：

- 信息密度高，但不拥挤。
- 先保证扫描效率，再做装饰。
- 文字层级克制，标题不放大，标签不压小。
- 颜色以中性色为主体，品牌色和状态色只用于动作、状态和重点。
- 数字和价位要稳定、可比较，不随内容变化挤压布局。

禁止：

- 页面里出现新的字体库或局部字体栈。
- 继续写 `text-[7px]`、`text-[8px]`、`text-[9px]` 作为业务信息字号。
- 用 `text-[24px]`、`text-[28px]` 做普通面板标题或数字。
- 用 `text-[#...]`、`color: #...` 写正文或状态色。
- 负字距，例如 `tracking-[-0.02em]`。
- 大面积紫色、渐变、玻璃态、卡片套卡片、营销式 hero。

## 3. 字体库

当前统一字体：

| Token | 字体栈 | 用途 |
|---|---|---|
| `--font-ui` | `"Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", sans-serif` | 全局中文 UI、正文、标题 |
| `--font-sans` | `var(--font-ui)` | Tailwind `font-sans` |
| `--font-display` | `var(--font-ui)` | 标题、标签、模块名 |
| `--font-market` | `var(--font-ui)` | 行情价格、KPI 数字 |
| `--font-mono` | `"JetBrains Mono", Consolas, monospace` | run id、hash、代码、需要等宽比较的机器字段 |

使用规则：

- 中文标题、中文标签、中文正文不要使用 `font-mono`。
- 价格、点位、百分比默认使用 `--font-market` + `tabular-nums`，不要随意换 DIN/Inter。
- `font-mono` 只用于机器字段、代码、日志、短 ID、hash、精确时间戳。
- 图表 tooltip、K 线标签若需要等宽，用 `var(--font-mono)`，不要写 `monospace`。

## 4. 字号层级

当前字号阶梯：

| Token | 值 | 用途 |
|---|---:|---|
| `--type-page-title` | `16px` | 页面标题、全局主标题 |
| `--type-section-title` | `15px` | 页面 section 标题、模块标题 |
| `--type-card-title` | `14px` | 卡片标题、价位组标题、小模块标题 |
| `--type-subtitle` | `13px` | 强调正文、二级标题 |
| `--type-body` / `--text-body` | `13px` | 普通正文、报告摘要、列表正文 |
| `--type-body-sm` | `12.5px` | 次级正文、密集列表说明 |
| `--type-label` | `12px` | 标签、表头、meta label、按钮文字 |
| `--type-caption` | `11px` | caption、弱提示、机器字段摘要 |
| `--type-kpi` | `18px` | KPI 数字、关键小指标 |
| `--type-kpi-lg` | `20px` | 重要价格、主 KPI |
| `--text-28` | `22px` | 极少量大数字，不用于普通面板 |

原则：

- 正文默认 `13px`，不要压到 `10px` 以下。
- 标签最小 `11px`，业务标签推荐 `12px`。
- 页面里普通标题不超过 `16px`，卡片标题常用 `14px`。
- KPI 大数字常用 `18px` 到 `20px`，不要默认 `24px+`。
- 如果必须使用 Tailwind arbitrary size，写 token：`text-[length:var(--type-label)]`，不要写裸 `text-[10px]`。
- 现有 `text-[7px]`、`text-[8px]`、`text-[9px]`、`text-[10px]` 已有运行态兜底，但新代码不要继续增加。

推荐类：

| 类名 | 用途 |
|---|---|
| `.fa-page-title` | 页面标题 |
| `.fa-section-title` | 区块标题 |
| `.fa-card-title` | 卡片标题 |
| `.fa-body-text` | 正文 |
| `.fa-muted-text` | 次级正文 |
| `.fa-faint-text` | 弱提示 |
| `.fa-label` | 标签 / 表头 |
| `.fa-compact-label` | 极紧凑标签 |
| `.fa-price-num` | 主价格 / 主点位 |
| `.fa-num` | 等宽机器数值 |

## 5. 文字颜色层级

文字色只分 5 个语义层级：

| 语义 | Token | 用途 |
|---|---|---|
| primary | `--fa-text-primary` / `--fg-1` | 标题、关键数值、主要判断 |
| body | `--fa-text-body` / `--fg-2` | 正文、普通可读内容 |
| muted | `--fa-text-muted` / `--fg-3` | 辅助说明、表格次级列 |
| label | `--fa-text-label` / `--fg-4` | 标签、表头、meta label |
| faint | `--fa-text-faint` / `--fg-5` | 时间、空态、弱提示、非关键 meta |

浅色主题当前色阶：

| Token | 值 |
|---|---|
| `--fg-1` | `#0f172a` |
| `--fg-2` | `#1f2a3a` |
| `--fg-3` | `#344256` |
| `--fg-4` | `#516176` |
| `--fg-5` | `#66758a` |
| `--fg-6` | `#7b8798` |

规则：

- 标题和关键数字用 `primary`，正文用 `body`，说明用 `muted`，标签用 `label`。
- 不要为了“显高级”把正文写得太浅。
- `fg-6` 只用于极弱信息，不能用于按钮、状态、表头、关键数据。
- 新代码优先用语义类或 `var(--fa-text-*)`，少写 `text-[var(--fg-*)]`。
- 禁止直接写 `text-[#64748b]`、`text-slate-*` 这类绕过 token 的颜色。

## 6. 状态色和功能色

状态色不可和正文灰阶混用。

| Token | 用途 |
|---|---|
| `--brand` / `--brand-hover` | active、主操作、链接、选中状态 |
| `--up` / `--up-soft` / `--up-border` | 上涨、偏多、成功、可用 |
| `--down` / `--down-soft` / `--down-border` | 下跌、偏空、错误、阻断 |
| `--warn` / `--warn-soft` / `--warn-border` | 风险、预警、partial、待确认 |
| `--info` / `--info-soft` / `--info-border` | 信息提示、周末模式、普通通知 |
| `--important` / `--important-soft` / `--important-border` | 当前页面主重点、需要用户先读的判断 |

规则：

- 状态必须同时有颜色和文字，不能只靠红绿表达。
- `up/down` 是市场方向或运行状态，不要写成“好/坏”的视觉含义。
- 重点内容用 `important`，不要到处用纯红。
- 信息提示用 `info` token，不写硬编码蓝色。
- 状态 pill 必须有 soft 背景和 border，不要只改文字颜色。

## 7. 数字、价位和金融指标

价位和数字是金融页面的核心，应稳定且可比较。

规则：

- 价位行推荐结构：`label + value`，不要用 `space-between` 把两端拉开造成大空白。
- 数字使用 `font-variant-numeric: tabular-nums` 和 `"tnum", "zero"`。
- 点位、价格、百分比使用 `--font-market`；机器 ID 和代码用 `--font-mono`。
- 卡片内大 KPI 用 `--type-kpi` 或 `--type-kpi-lg`。
- 多个价位组右侧排版时，优先固定右栏宽度或单列堆叠，不让内容横向撑开。

示例：

```tsx
<div className="dashboard-level-row">
  <span>上方确认区</span>
  <strong>4,165</strong>
</div>
```

对应 CSS 应使用 token：

```css
.dashboard-level-row {
  color: var(--dashboard-text-label);
  font-size: var(--type-label);
}

.dashboard-level-row strong {
  color: var(--dashboard-text-primary);
  font-family: var(--font-market);
  font-size: var(--type-card-title);
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum", "zero";
}
```

## 8. Tailwind 使用规则

允许：

```tsx
<div className="text-[length:var(--type-body)] text-[var(--fa-text-body)]" />
<span className="fa-num text-[var(--fg-2)]" />
<button className="border border-[var(--border)] text-[var(--fg-3)]" />
```

不允许：

```tsx
<div className="text-[9px] text-[#64748b]" />
<div className="text-2xl tracking-[-0.02em]" />
<div style={{ fontFamily: "Inter", color: "#334155" }} />
```

优先级：

1. 共享组件和 `fa-*` 类。
2. CSS token + Tailwind arbitrary value。
3. 局部 CSS class。
4. inline style 只用于图表库或第三方库无法避免的属性。

## 9. 组件级规范

### 页面标题

- 使用 `FAWorkspaceHeader`、`FAPageScaffold` 或现有 header 体系。
- 页面标题 `16px` 左右，不做大 hero。
- 面包屑、日期、来源等 meta 使用 `label/faint`，不要抢标题层级。

### 模块标题

- 使用 `.fa-section-title` 或 `.fa-card-title`。
- 中文标题使用 display 字体 token，不用 mono。
- 英文缩写只在业务必要时保留，例如 `XAUUSD`、`CME`、`Gamma Zero`。

### 正文

- 使用 `.fa-body-text` 或 `--type-body`。
- 行高用 `--lh-body` 或 `--lh-body-sm`。
- 报告和分析摘要不能压缩到 11px 以下。

### 标签和表头

- 使用 `--type-label`，颜色用 `--fa-text-label`。
- 只有极紧凑机器字段可用 `--type-caption`。
- 表头不得使用 `fg-6` 或过低对比度。

### 卡片和面板

- 卡片 radius 默认不超过 `8px`。
- 不做卡片套卡片，除非是重复 item 或明确 framed tool。
- 卡片 padding 默认 `10-14px`；密集区可以 `8-10px`。
- 单个模块内部不留大块空白，内容少时用横向信息条或薄 meta row。

### 状态 Pill

- 文字 `11-12px`，不要 8px。
- 状态必须使用语义色：`up/down/warn/info/important`。
- 状态文案必须明确，例如 `偏多`、`待确认`、`数据完整`。

## 10. 开发前检查

新写或改视觉时先检查：

- 是否用了 `--font-ui` / `--font-sans` / `--font-market` / `--font-mono`，没有新字体栈。
- 是否用了 `--type-*`，没有裸写新的字号。
- 是否用了 `--fa-text-*` 或 `fg-*`，没有硬编码正文颜色。
- 状态色是否来自 `up/down/warn/info/important`。
- 是否存在 `space-between` 导致标签和数值被拉开。
- 是否有 `text-[7px]`、`text-[8px]`、`text-[9px]`、`text-[24px]`、`text-[28px]` 新增。
- 是否有 `tracking-[-...]`。
- 是否有卡片套卡片或空白过大的右侧栏。

## 11. 验收要求

视觉相关改动完成前至少执行：

```bash
rtk npm run typecheck --prefix apps/frontend-web
rtk npm run build --prefix apps/frontend-web
```

若当前工作树已有无关类型错误，应在交付说明中明确指出阻断文件和错误行，不把它归因到本次视觉改动。

用户可见页面调整还应保留浏览器证据：

- Dashboard / 首页改动：截图 `/dashboard`
- 市场监控改动：截图 `/market-monitor`
- 黄金主线改动：截图 `/gold-mainlines`
- 事件流改动：截图 `/event-flow`

截图用于确认排版、溢出、裁剪、空白和状态色，不替代代码规则。

## 12. 快速执行清单

开发时按下面顺序做：

1. 先找现有组件和 token。
2. 用 `fa-*` 或 CSS 变量写样式。
3. 字号按 `--type-*` 选，不手写裸 px。
4. 颜色按 `--fa-text-*` 和状态 token 选。
5. 中文不用 mono，机器字段才用 mono。
6. 数字用 tabular numeric。
7. 页面保持高密度，去掉无意义空白。
8. 跑 `typecheck` 和 `build`，必要时截图验收。
