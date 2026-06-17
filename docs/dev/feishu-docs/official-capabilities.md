# 飞书 Docx / Board 官方能力摘要

更新时间：2026-06-12

本文基于飞书开放平台官方文档整理，作为 renderer 和 publisher 的实现约束。

## 官方文档

- 创建块：https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/create
- 批量更新块：https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/batch_update
- 删除块：https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/batch_delete
- 解析画板语法：https://open.feishu.cn/document/ukTMukTMukTM/uUDN04SN0QjL1QDN/board-v1/whiteboard-node/create_plantuml

## 可用块类型

| 能力 | 官方 Block / 字段 | 推荐用途 |
| --- | --- | --- |
| 标题层级 | Heading1~9，`block_type=3` 到 `11` | 文档层级和目录结构。 |
| 正文段落 | Text，`block_type=2` | 精炼说明。 |
| 无序 / 有序列表 | `block_type=12` / `13` | 任务、步骤、风险列表。 |
| 代码块 | `block_type=14`，`language` | 命令、JSON、SQL。 |
| 引用块 | `block_type=15` | 原则、约束、引用说明。 |
| 高亮块 / Callout | `block_type=19`，`callout.background_color`、`emoji_id` | 结论、风险、状态提示。 |
| 分割线 | `block_type=22` | 大段落视觉分隔。 |
| 文件 | `block_type=23` | 附件、PDF、原始报告引用。 |
| 分栏 | `block_type=24` / `25` | 状态卡、左右栏对照、P0/P1/P2。 |
| 图片 | `block_type=27` | 截图、架构图 PNG、市场图。 |
| 表格 | `block_type=31` | 短矩阵、任务表、API 对照。 |
| 画板 | `block_type=43` + Board PlantUML API | Mermaid / PlantUML 流程图。 |
| 链接预览 | `block_type=48` | 官方文档、飞书文档、Repo 链接。 |

## 文本样式

文本元素支持：

- `bold`
- `italic`
- `strikethrough`
- `underline`
- `inline_code`
- 文字颜色
- 背景色
- 链接
- @用户
- @文档
- 日期提醒

## Mermaid / PlantUML

官方 Board 解析接口支持把 PlantUML / Mermaid 导入画板：

- `syntax_type=2` 表示 Mermaid。
- `block_type=43` 是画板块。
- `block.token` 对应 `whiteboard_id`。

实现要求：

- Mermaid 不得作为 fenced code block 发布到飞书。
- 发布后必须检查 `board_count`。
- 如果 Feishu API 调整画板 token 返回结构，需要同步更新 `_extract_whiteboard_id()`。

## 频控与批量限制

- 创建块、删除块、更新块、批量更新块、创建嵌套块等编辑操作，单应用调用上限和单篇文档并发编辑上限约为每秒 3 次。
- 创建块接口单次 `children` 长度范围为 `1` 到 `50`。
- 批量更新块接口一次最多 200 个 update 请求。
- 同一次批量更新不能重复更新同一个 Block ID。
- 删除块接口按父块 children 的左闭右开索引区间删除。

实现要求：

- 发布器必须内置节流和 429 退避。
- 大量块创建需要分批。
- 复杂版面应使用稳定 anchor 和保守替换策略。
- 不要把无法安全局部删除的复杂嵌套结构作为频繁更新单元。
