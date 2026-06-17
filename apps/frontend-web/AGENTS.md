# Frontend Web Instructions

## 技术栈

- Vite 5 + React 18 + TypeScript
- Tailwind CSS（无第三方 UI 库）
- 组件化页面 + hooks 数据层
- 工程目录：`apps/frontend-web/src`

## 关键目录

```
apps/frontend-web/
  src/
    adapters/       # API 数据适配层（useDashboard, useReports, useEventFlow...）
    components/     # 可复用组件（FA* 前缀 = Finance Agent 组件）
    hooks/          # 通用 hooks
    pages/          # 路由页面组件
    types/          # TypeScript 类型定义
  index.html        # 入口 HTML
  vite.config.ts    # Vite 配置
  package.json      # 依赖与脚本
```

## 页面清单与主任务

| 路由 | 主任务 | 核心组件 |
|------|--------|----------|
| `/dashboard` | 今天市场是否可交易？ | FAMetricCard, FAFilterBar |
| `/market-monitor` | 当前宏观环境是否支持黄金方向？ | 利率、美元、流动性面板 |
| `/event-flow` | 哪些事件正在改变市场预期？ | EventFlowLiveBriefsPanel |
| `/reports` | 今天的分析结论和依据？ | ReportDetailSections |
| `/strategy` | 当前策略信号和概率？ | FAConvictionBar |
| `/data-ingestion` | 数据采集状态和健康度？ | DataIngestionSourceDetailPanel |
| `/review-center` | 哪些数据/分析需要复核？ | Review 列表 |
| `/settings` | 配置管理 | Settings 面板 |
| `/knowledge-base` | 知识库检索 | KnowledgeBase 组件 |

## 前端设计原则

### 金融工作台风格（4 条铁律）

1. **低噪声、高密度、可扫描**：去除装饰元素，数字说话
2. **中文优先、数字粗体、状态色标**：交易员 3 秒扫描读结论
3. **每个卡片必须有**：标题 + 状态标识 + 更新时间 + 数据来源
4. **一页一主任务**：不堆砌，每个页面只回答一个核心问题

### 信息层级（首屏到底部）

1. 核心结论/状态（一句话判读）
2. 关键指标（利率、美元、流动性）
3. 细分数据（表格、图表）
4. 溯源信息（数据来源、更新时间）

### 不重复原则

- 同一数据不在多个页面重复展示
- 总览页只保留核心结论，细节放子页
- 市场和事件流各自独立，不互相嵌套

## 组件设计规范

所有新组件必须满足：

- **FA 前缀命名**：`FA{Name}` 格式（FAMetricCard, FASectionHeader, FAWarningBanner...）
- **单一职责**：一个组件做一件事
- **状态完整**：loading / error / empty / partial / success 五种状态
- **数据时间**：所有数据卡片显示 `updated_at`
- **溯源可见**：关键卡片附带 `FASourceTraceBadge`
- **高度一致**：卡片高度尽量统一，避免布局跳动

## 数据层规范

- **页面不直接调 API**：通过 `adapters/` 中的 hooks
- **不自己计算策略**：策略/分析结论来自后端 API，前端只做展示
- **枚举值翻译在前端**：API 返回英文枚举 → 前端翻译为中文标签
- **Dashboard indicator 映射**：`normalizeDashboardSummary()` 中的 `mappedIndicators` 做别名转换

## 修改流程（强制 5 步）

### 1. 审查

输出：
```text
页面主任务：
当前问题：
保留模块：
合并模块：
迁移模块：
删除模块：
新增模块：
```

### 2. 方案

```text
页面结构（层级树）：
组件结构：
数据依赖（API 端点）：
交互行为：
修改风险（是否影响其他页面）：
```

### 3. 确认

- 展示修改前后对比
- 标注风险点
- 等待用户确认

### 4. 执行（最小 diff）

- 先读文件，再小步改
- 不改不相关的文件和逻辑
- 不引入新依赖（除非明确需求）
- 不改 `apps/frontend/`（已废弃）

### 5. 验证（必须跑）

```bash
cd apps/frontend-web
npm run lint
npm run build
```

## 禁止事项

- 禁止向后端 API 发 write/delete 请求
- 禁止删除仍被其他页面引用的组件
- 禁止为追求 UI 效果而牺牲数据可读性
- 禁止纯装饰模块占用首屏空间
- 禁止在 page 组件里写复杂业务逻辑（放 hooks/adapters）
- 禁止引入新的 UI 框架/库（只用 Tailwind）
- 禁止修改 `apps/frontend/`（已删除的旧 Next.js 前端）

## 市场监控页专项规则

市场监控页 (`/market-monitor`) 的模块必须围绕「做单环境判断」：

- **保留**：利率面板、美元/日元面板、流动性面板、风险环境面板、市场 regime、溯源组件
- **可迁移到子页**：与首页重复的结论、与事件流重复的新闻、低价值原始指标表
- **可删除**：无引用的纯装饰模块
- **页面模块数 ≤ 8**

## 事件流页专项规则

事件流页 (`/event-flow`) 必须拆分为：

1. 当日快讯
2. 重点事件
3. 影响分析
4. 事件链路
5. 溯源

快讯 ≠ 事件流。事件流需要体现因果链、影响方向和持续时间。

## 验证清单

修改完成后必须确认：

- [ ] `npm run lint` 通过
- [ ] `npm run build` 通过
- [ ] 页面核心信息在首屏可见
- [ ] 所有数据卡片有更新时间
- [ ] 关键结论有数据来源（FASourceTraceBadge）
- [ ] 没有与其他页面重复的模块
- [ ] 总览页模块 ≤ 6 个，详情页模块 ≤ 8 个
