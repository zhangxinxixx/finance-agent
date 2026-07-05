import type { ReactNode } from "react";
import {
  DATA_CATEGORY_HEADINGS,
  parseInlineMarkdown,
  resolveAssetUrl,
  type MarkdownBlock,
  type MarkdownTableBlock,
} from "./markdownViewerModel";

function InlineMarkdown({ text }: { text: string }) {
  return (
    <>
      {parseInlineMarkdown(text).map((token, index) => {
        const key = `${token.type}-${index}`;
        if (token.type === "bold") return <strong key={key}>{token.text}</strong>;
        if (token.type === "code") return <code key={key}>{token.text}</code>;
        if (token.type === "link") {
          return (
            <a key={key} href={token.href} target="_blank" rel="noreferrer">
              {token.text}
            </a>
          );
        }
        return <span key={key}>{token.text}</span>;
      })}
    </>
  );
}

function renderHeading(level: 1 | 2 | 3, content: string, key: string): ReactNode {
  const category = DATA_CATEGORY_HEADINGS[content];

  if (level === 1) {
    return <h1 key={key} className="text-[20px] font-semibold text-[var(--fg-1)]">{content}</h1>;
  }

  if (level === 2) {
    const borderClass = category ? category.accent : "border-l-[var(--brand)]";
    return (
      <h2 key={key} className={`border-l-2 ${borderClass} pl-3 text-[16px] font-semibold text-[var(--fg-1)]`}>
        <InlineMarkdown text={content} />
        {category ? (
          <span className={`ml-2 inline-block rounded border px-1.5 py-0.5 font-mono text-[9px] font-medium tracking-wider ${category.tone}`}>
            {category.label}
          </span>
        ) : null}
      </h2>
    );
  }

  return <h3 key={key} className="text-[14px] font-semibold text-[color-mix(in_srgb,var(--fg-1)_95%,transparent)]">{content}</h3>;
}

function renderTable(block: MarkdownTableBlock, key: string): ReactNode {
  return (
    <div key={key} className="report-table-scroll">
      <table>
        <thead>
          <tr>
            {block.headers.map((header, cellIndex) => (
              <th key={`${key}-head-${cellIndex}`} style={{ textAlign: block.aligns[cellIndex] ?? "left" }}>
                <InlineMarkdown text={header} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, rowIndex) => (
            <tr key={`${key}-row-${rowIndex}`}>
              {row.map((cell, cellIndex) => (
                <td key={`${key}-cell-${rowIndex}-${cellIndex}`} style={{ textAlign: block.aligns[cellIndex] ?? "left" }}>
                  <InlineMarkdown text={cell} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function renderMarkdownBlock(
  block: MarkdownBlock,
  blockIndex: number,
  assetBaseUrl?: string,
  assetVersion?: string,
  figureNumber?: number,
): ReactNode {
  const key = `${block.type}-${blockIndex}`;

  switch (block.type) {
    case "heading":
      return renderHeading(block.level, block.content, key);
    case "list":
      return (
        <ul key={key} className="space-y-1 pl-5 text-[var(--fg-4)]">
          {block.items.map((item, itemIndex) => (
            <li key={`${key}-${itemIndex}`} className="list-disc marker:text-[var(--brand)]">
              <InlineMarkdown text={item} />
            </li>
          ))}
        </ul>
      );
    case "code":
      return (
        <div key={key} className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--bg-terminal)]">
          {block.language ? <div className="border-b border-[var(--border)] px-3 py-2 font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--fg-5)]">{block.language}</div> : null}
          <pre className="overflow-x-auto p-4 font-mono text-[12px] leading-6 text-[var(--fg-2)]">
            <code>{block.content}</code>
          </pre>
        </div>
      );
    case "image": {
      const figureLabel = typeof figureNumber === "number" ? `图表 ${figureNumber}` : "图表";
      const figureCaption = block.alt ? `${figureLabel} · ${block.alt}` : figureLabel;
      return (
        <figure key={key} className="space-y-2 rounded-lg border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
          <img
            src={resolveAssetUrl(block.src, assetBaseUrl, assetVersion)}
            alt={block.alt || "report image"}
            className="max-h-[640px] w-full rounded-md object-contain"
            loading="eager"
            decoding="async"
          />
          <figcaption className="text-[11px] text-[var(--fg-5)]">{figureCaption}</figcaption>
        </figure>
      );
    }
    case "table":
      return renderTable(block, key);
    case "paragraph":
      return (
        <p key={key} className="whitespace-pre-wrap text-[length:var(--text-13)] leading-[1.85] text-[var(--fg-4)]">
          <InlineMarkdown text={block.content} />
        </p>
      );
    default:
      return null;
  }
}

export function MarkdownFallbackPre({
  content,
  className = "",
}: {
  content: string;
  className?: string;
}) {
  return (
    <pre
      className={`min-h-0 overflow-x-auto whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--bg-card-inner)] p-4 font-mono text-[12px] leading-6 text-[var(--fg-4)] ${className}`}
    >
      {content}
    </pre>
  );
}

export function MarkdownBlockList({
  blocks,
  assetBaseUrl,
  assetVersion,
  className = "",
}: {
  blocks: MarkdownBlock[];
  assetBaseUrl?: string;
  assetVersion?: string;
  className?: string;
}) {
  let figureCount = 0;
  return (
    <div className={`report-prose min-h-0 space-y-4 pr-1 text-[length:var(--text-13)] leading-[1.85] text-[var(--fg-4)] ${className}`}>
      {blocks.map((block, blockIndex) => {
        const figureNumber = block.type === "image" ? ++figureCount : undefined;
        return renderMarkdownBlock(block, blockIndex, assetBaseUrl, assetVersion, figureNumber);
      })}
    </div>
  );
}
