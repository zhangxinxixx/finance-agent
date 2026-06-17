# 飞书云文档发布说明

更新时间：2026-06-12

本文只作为旧路径兼容入口。云文档发布、渲染和 V2 中台说明已经拆分到 `docs/dev/feishu-docs/`，避免同一内容在多个文件里重复维护。

## 当前唯一维护入口

- [feishu-docs/README.md](feishu-docs/README.md)：云文档维护总入口。
- [feishu-docs/inventory.md](feishu-docs/inventory.md)：当前远端 Docx / Bitable 清单与多版本边界。
- [feishu-docs/publish-cli.md](feishu-docs/publish-cli.md)：发布脚本、认证、dry-run、定向 section 发布。
- [feishu-docs/rendering-spec.md](feishu-docs/rendering-spec.md)：通用 Docx 渲染规范。
- [feishu-docs/official-capabilities.md](feishu-docs/official-capabilities.md)：官方 Docx / Board 能力和限制。
- [feishu-docs/workspace-v2.md](feishu-docs/workspace-v2.md)：V2 Docx + Bitable 工程文档中台。

## 快速命令

定向 section dry-run：

```bash
rtk uv run python scripts/publish_feishu_section.py \
  --document-id <docx_document_id> \
  --anchor <stable_anchor> \
  --doc-file <repo_doc.md> \
  --diagram <diagram.mmd> \
  --dry-run
```

真实发布优先使用本地 OAuth：

```bash
rtk uv run python scripts/publish_feishu_section.py \
  --document-id <docx_document_id> \
  --anchor <stable_anchor> \
  --doc-file <repo_doc.md> \
  --auth-mode lark-cli
```

完整说明见 [feishu-docs/publish-cli.md](feishu-docs/publish-cli.md)。
