# 飞书云文档清单

更新时间：2026-06-12

本文只记录 `finance-agent` 当前推荐维护的远端云文档和旧版本边界，避免后续重复创建多套同名文档。

## 当前推荐：工程文档中台 V2

V2 是当前推荐的远端展示结构：Docx 只放入口、短说明和流程图，长表格放 Bitable。

清单来自 `docs/feishu_publish_manifest.v2.json`：

| 类型 | 名称 | ID / Token | URL |
| --- | --- | --- | --- |
| Docx | finance-agent 云文档入口 | `ATJQd801Ho9jPNxK8qTcxxgsnfg` | https://my.feishu.cn/docx/ATJQd801Ho9jPNxK8qTcxxgsnfg |
| Docx | finance-agent 工程文档中台 V2 - 架构流程图 | `NGvydwvL0omSskxocHKc6J8znoh` | https://my.feishu.cn/docx/NGvydwvL0omSskxocHKc6J8znoh |
| Bitable | finance-agent 工程台账 V2 | `XwQgbvxOvakyq5sxqnscjLPpnbf` | https://my.feishu.cn/base/XwQgbvxOvakyq5sxqnscjLPpnbf |
| Docx | 进行中-系统可用性升级方案-0609 | `XEFddrTn1oNzEVxOxVFctDSJneg` | https://my.feishu.cn/docx/XEFddrTn1oNzEVxOxVFctDSJneg |

当前 Bitable 表：

| 表名 | 当前记录数 | 用途 |
| --- | ---: | --- |
| `API_MAP` | 101 | API 与页面 / 用途映射。 |
| `PAGE_MATRIX` | 12 | 页面职责矩阵。 |
| `ROADMAP` | 21 | 后端 / 前端改造规划。 |
| `RISKS_TODO` | 10 | 风险与待办。 |
| `DATA_MODEL_STORAGE` | 88 | 数据模型与 storage 分层。 |
| `MODULE_STATUS` | 43 | 审计中的模块 / API / 页面 / 模型状态。 |

## 旧 baseline 三件套

旧 baseline 由 `scripts/publish_feishu_docs.py --preset project-docs-baseline` 维护。它仍可用于兼容和历史查看，但不应作为新内容扩展的默认入口。

| 文档 | document_id | 当前建议 |
| --- | --- | --- |
| 归档-finance-agent 项目现状审计 | `S3JMdA5uPoSpdkxRwDUchbUkn3d` | 历史审计入口，当前结构化状态以 Bitable 为准。 |
| 归档-finance-agent 架构与流程图 | `Qijfd0pJsoQtjjxwJSycMthyn0b` | 历史大文档，当前以 V2 架构流程图为准。 |

## 已删除重复 / 测试文档

| 文档 | token | 删除原因 |
| --- | --- | --- |
| 删除候选-finance-agent Mermaid Smoke | `Axm3dikDNop1E3x9FEIcahOjnfj` | Mermaid 渲染测试文档，能力已由 V2 架构流程图覆盖。 |
| 删除候选-项目现状审计.md | `UKQPdrkYxodSZIxP5WrcszSknvg` | 与归档审计文档和 Bitable 台账重复。 |
| 归档-finance-agent 改造规划 | `FI1UdfFVQoWa6Pxv8suc7cdbnFg` | 旧规划导出件，已被 repo / Obsidian / Bitable 覆盖。 |

## 防止多版本规则

- 更新现有 V2 时使用 `scripts/publish_feishu_workspace_v2.py --update-existing`。
- 更新单个主题时使用 `scripts/publish_feishu_section.py --document-id <existing_docx_id> --anchor <stable_anchor>`。
- 只有用户明确要求创建新版远端文档时才使用 `--create-new`。
- 认证失败时先修复 `lark-cli auth` 或 env token，不通过新建文档绕过。
- 新增远端文档或 Bitable 后，必须同步更新 `docs/feishu_publish_manifest.v2.json` 或本文。

## 与其他飞书能力的边界

- `lark-channel-bridge` 远程入口见 `docs/dev/workbench-maintenance.md`。
- 飞书 webhook 消息发送见 `apps/output/feishu.py` 和 `scripts/send_feishu_message.py`。
- Jin10 / Feishu 群消息采集属于新闻链数据源，不属于云文档发布。
