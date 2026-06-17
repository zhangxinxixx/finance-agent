# 飞书云文档维护入口

更新时间：2026-06-12

本目录是 `finance-agent` 仓库内飞书 / Lark 云文档发布与渲染说明的唯一维护入口。旧入口 `docs/dev/feishu-doc-publish.md` 和 `docs/dev/feishu-doc-rendering-roadmap.md` 只保留兼容跳转，不再承载重复长内容。

## 适用范围

这里记录的是云文档协作展示层：

- Docx 文档发布。
- Mermaid / PlantUML 画板渲染。
- Bitable 工程台账。
- 发布脚本、认证方式、读回验收。
- 后续 Docx block renderer 设计规范。

这里不记录：

- 飞书聊天 webhook 发送。
- Jin10 / Feishu 群消息采集。
- `lark-channel-bridge` 远程 Codex 入口。
- 业务数据源采集和分析链路。

## 当前推荐入口

| 文档 | 用途 |
| --- | --- |
| [inventory.md](inventory.md) | 当前远端云文档 / Bitable 清单、推荐入口和旧版本边界。 |
| [publish-cli.md](publish-cli.md) | 发布脚本、认证、dry-run、全量发布、定向 section 发布。 |
| [rendering-spec.md](rendering-spec.md) | 通用 Docx 渲染规范、版面原则、后续实现顺序。 |
| [official-capabilities.md](official-capabilities.md) | 官方 Docx / Board 能力、块类型、限制、频控。 |
| [workspace-v2.md](workspace-v2.md) | V2 Docx + Bitable 工程文档中台说明。 |

## 当前结论

- 常规更新优先使用 `scripts/publish_feishu_section.py`，按 anchor 更新目标 Docx 的局部 section。
- 不要为了避开 token 过期或内容冲突而反复 `--create-new`，否则远端会出现多版本文档。
- 旧 `scripts/publish_feishu_docs.py --confirm-overwrite` 是固定 baseline 全量重写工具，只在明确需要重写旧三件套时使用。
- 新的通用方向是 `FeishuDocModel -> layout components -> Docx block plan -> anchored section publisher -> read-back validation`。
- Mermaid 必须通过 Board / Whiteboard 小组件渲染，不接受 fenced code block 在飞书里变成 Plain Text。

## 推荐工作流

```text
确认目标远端文档
-> dry-run
-> 检查 action / block_count / table_count / board_count
-> 使用 lark-cli 或 env token 发布
-> 读回检查 anchor marker、标题和 board_count
-> 更新 inventory / manifest / 版本记录
```

## 本地与远端事实边界

- Repo docs 和 Obsidian 是长期事实源。
- 飞书云文档是协作展示层，不作为系统事实源。
- `docs/feishu_publish_manifest.v2.json` 只记录 V2 云文档和 Bitable 的当前远端 ID，不保存 token 或 secret。
