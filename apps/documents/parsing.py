"""Parse report markdown into structured blocks."""

from __future__ import annotations

from apps.documents.schemas import ParsedBlock, ParsedDocument, SourceDocument


def build_parsed_document(source_document: SourceDocument) -> ParsedDocument:
    lines = [line.rstrip() for line in source_document.report_text.splitlines()]
    blocks: list[ParsedBlock] = []
    buffer: list[str] = []
    block_index = 0

    def flush_paragraph() -> None:
        nonlocal block_index
        text = "\n".join(item for item in buffer if item.strip()).strip()
        buffer.clear()
        if not text:
            return
        block_index += 1
        blocks.append(
            ParsedBlock(
                block_id=f"{source_document.document_id}:paragraph:{block_index}",
                block_type="paragraph",
                text=text,
                page=None,
            )
        )

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            continue
        if stripped.startswith("![") and "](" in stripped:
            flush_paragraph()
            block_index += 1
            blocks.append(
                ParsedBlock(
                    block_id=f"{source_document.document_id}:image:{block_index}",
                    block_type="image",
                    text=stripped,
                    page=len([b for b in blocks if b.block_type == "image"]) + 1,
                )
            )
            continue
        buffer.append(stripped)

    flush_paragraph()

    return ParsedDocument(
        document_id=source_document.document_id,
        trade_date=source_document.trade_date,
        title=source_document.title,
        source_url=source_document.source_url,
        article_id=source_document.article_id,
        category=source_document.category,
        category_code=source_document.category_code,
        blocks=blocks,
        source_refs=source_document.source_refs,
    )
