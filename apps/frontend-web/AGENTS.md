# Frontend Web Instructions

本文件只保存 `apps/frontend-web/` 的稳定不变量。单次目标、范围、权限、验收、证据和停止条件放在任务文件，不在这里重复。

## Stack And Entry

- Vite + React 18 + TypeScript，正式入口为 `apps/frontend-web/src`。
- 页面放 `src/pages`，复用组件放 `src/components`，API 适配和字段归一化放 `src/adapters` / `src/hooks`，共享类型放 `src/types`。
- 不恢复旧 `apps/frontend/` 或 FastAPI 直出页面，不新增第二套入口。
- 字体、状态色、视觉密度和 typography 使用 `docs/frontend/typography-and-visual-style-guide.md` 的 token 与语义类。

## Product Boundary

- 页面是机构研究工作台，不是通用后台管理台；一页只服务一个主要研究任务。
- Dashboard 的主判断来自综合/宏观报告，期权报告只作为结构证据。
- 前端消费后端 read model，不计算策略、因子、评分或报告结论。
- 页面不直接散落 API 调用；通过既有 adapter/hook 统一处理字段、错误和 freshness。
- 关键结论保留来源、更新时间和可进入详情/溯源的入口。

## UI Contract

- 优先复用现有 FA 组件、布局、路由、交互和 design token；不要建立平行设计系统。
- 用户状态至少覆盖任务相关的 loading、empty、partial/unavailable、error 和 success。
- 枚举翻译可在前端完成；金融计算和业务判定不可在前端复制。
- 页面层保持编排职责，复杂数据变换放 adapter/hook，通用视觉单元放组件。
- 可见中文优先，XAUUSD、CME、DXY、source_ref、snapshot_id 等技术标识保留原文。

## Change Boundary

- 普通前端修复可直接做最小修改，不强制额外设计稿、Plan 或用户确认轮次。
- 页面信息架构、公共组件 contract、路由或跨页行为变化时，先说明结构和风险；只有重大歧义才暂停确认。
- 未经任务授权，不修改后端、数据库、采集/解析、密钥、部署、全局 AppShell 或无关页面。
- 保留无关脏改动，不做全仓格式化或顺手重构。

## Evidence And Stop Condition

按任务风险选择最小有效证据：目标测试、TypeScript 检查、lint、build、API response、真实浏览器/Playwright 的 DOM、console、network 或截图。

可见页面变化至少验证任务涉及的核心流程和状态；不要求与本次改动无关的空栏目或全站截图。

满足任务 Acceptance、取得声明的证据、确认没有无关扩张后停止。最终汇报：结论、修改文件、关键决定、验证结果、未验证风险。
