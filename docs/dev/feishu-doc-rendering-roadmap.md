# 飞书云文档美观化渲染路线图

更新时间：2026-06-12

本文只作为旧路径兼容入口。云文档渲染路线图已经拆分到 `docs/dev/feishu-docs/`，避免和发布手册重复维护。

## 当前维护入口

- [feishu-docs/rendering-spec.md](feishu-docs/rendering-spec.md)：通用 Feishu/Lark Docx renderer 设计规范。
- [feishu-docs/official-capabilities.md](feishu-docs/official-capabilities.md)：官方 Docx / Board 能力、块类型和限制。
- [feishu-docs/publish-cli.md](feishu-docs/publish-cli.md)：发布脚本、认证和 dry-run。
- [feishu-docs/inventory.md](feishu-docs/inventory.md)：当前远端云文档清单。

## 核心结论

- 不要把原始 Markdown 原样发布到飞书。
- Mermaid 必须用 Board / Whiteboard 渲染，不接受 Plain Text。
- 后续实现以通用 `FeishuDocModel -> layout components -> Docx block plan -> anchored section publisher` 为主线。
