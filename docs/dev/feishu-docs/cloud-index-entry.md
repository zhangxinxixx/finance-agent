# finance-agent 云文档入口

更新时间：2026-06-12

本文是当前唯一推荐入口。旧 baseline 已降级为归档；smoke test 和重复审计导入件已删除。`系统可用性升级方案-0609` 尚未实现完，保留为进行中方案。

## 当前主入口

| 类型 | 名称 | 链接 | 用途 |
| --- | --- | --- | --- |
| Docx | finance-agent 云文档入口 | 当前页 | 唯一入口、阅读顺序、归档边界 |
| Docx | finance-agent 工程文档中台 V2 - 架构流程图 | https://my.feishu.cn/docx/NGvydwvL0omSskxocHKc6J8znoh | 架构图和流程图，使用 Mermaid 画板 |
| Bitable | finance-agent 工程台账 V2 | https://my.feishu.cn/base/XwQgbvxOvakyq5sxqnscjLPpnbf | API、页面职责、路线图、风险、数据模型台账 |
| Docx | Feishu金十工作流 | https://my.feishu.cn/docx/QFZ8dioABoj2u8xUNEMc1jsynJh | 金十 / 飞书工作流专题，保留为独立专题文档 |
| Docx | 进行中-系统可用性升级方案-0609 | https://my.feishu.cn/docx/XEFddrTn1oNzEVxOxVFctDSJneg | 仍在实现中的可用性升级方案，不删除 |

## 阅读顺序

1. 当前页：确认哪些文档是当前版本。
2. 架构流程图：看系统总览、数据流、后端主链、前端页面、报告产物和溯源链路。
3. 工程台账 V2：查 API、页面职责、路线图、风险和模块状态。
4. 进行中方案：查看尚未完成的系统可用性升级工作。
5. 专题文档：只在需要对应主题时打开，例如金十 / 飞书工作流。

## 已归档文档

这些文档保留用于追溯，不再作为当前入口：

| 文档 | 原用途 | 当前处理 |
| --- | --- | --- |
| 归档-finance-agent 架构与流程图 | 旧 baseline 大文档，超过 500 blocks | 当前以 V2 架构流程图为准 |
| 归档-finance-agent 项目现状审计 | 旧 baseline 审计文档 | 结构化台账以 Bitable 为准 |

## 已删除重复 / 测试文档

这些文档是测试或重复导入产物，已从云端删除：

| 文档 | 原因 |
| --- | --- |
| finance-agent Mermaid Smoke | Mermaid 渲染测试文档 |
| 项目现状审计.md | 与 `finance-agent 项目现状审计` 重复 |
| 归档-finance-agent 改造规划 | 旧规划导出件，已被 repo / Obsidian / Bitable 覆盖 |
| 归档-finance-agent 系统功能架构整理 | 0608 临时架构整理稿，已无持续维护价值 |
| 归档-前端结构分析0609 | 0609 临时前端分析稿，已无持续维护价值 |

## 拆分原则

- Docx 只放入口、结论、短说明和 Mermaid 画板。
- 长表格和台账放 Bitable，不再塞进 Docx。
- 大文档按主题拆为入口、架构流程图、工程台账、专题工作流。
- 新增专题文档必须从当前入口链接，不再新建孤立版本。

## 后续维护规则

- 更新单个主题时，用固定 document_id + anchor section 更新，不要全量重写。
- 需要新增文档时，先判断是否应写入 Bitable 或已有专题。
- 认证失败时修复 lark-cli 授权，不通过 `create-new` 绕过。
- 删除其他归档文档前必须再次确认，避免误删历史证据。
