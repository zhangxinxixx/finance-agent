import type { ReactNode } from "react";
import { DATA_CATEGORY_HEADINGS, resolveAssetUrl, type MarkdownBlock } from "./markdownViewerModel";

function renderHeading(level: 1 | 2 | 3, content: string, key: string): ReactNode {
  const category = DATA_CATEGORY_HEADINGS[content];

  if (level === 1) {
    return <h1 key={key} className="text-[20px] font-semibold text-[var(--fg-1)]">{content}</h1>;
  }

  if (level === 2) {
    const borderClass = category ? category.accent : "border-l-[var(--brand)]";
    return (
      <h2 key={key} className={`border-l-2 ${borderClass} pl-3 text-[16px] font-semibold text-[var(--fg-1)]`}>
        {content}
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

function renderMarkdownBlock(block: MarkdownBlock, blockIndex: number, assetBaseUrl?: string): ReactNode {
  const key = `${block.type}-${blockIndex}`;

  switch (block.type) {
    case "heading":
      return renderHeading(block.level, block.content, key);
    case "list":
      return (
        <ul key={key} className="space-y-1 pl-5 text-[var(--fg-4)]">
          {block.items.map((item, itemIndex) => (
            <li key={`${key}-${itemIndex}`} className="list-disc marker:text-[var(--brand)]">
              {item}
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
    case "image":
      return (
        <figure key={key} className="space-y-2 rounded-lg border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
          <img
            src={resolveAssetUrl(block.src, assetBaseUrl)}
            alt={block.alt || "report image"}
            className="max-h-[640px] w-full rounded-md object-contain"
            loading="lazy"
          />
          {block.alt ? <figcaption className="text-[11px] text-[var(--fg-5)]">{block.alt}</figcaption> : null}
        </figure>
      );
    case "table":
      return (
        <div key={key} className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--bg-card-inner)]">
          <pre className="min-w-full p-4 font-mono text-[12px] leading-6 text-[var(--fg-2)]">
            {block.content}
          </pre>
        </div>
      );
    case "paragraph":
      return (
        <p key={key} className="whitespace-pre-wrap text-[var(--fg-4)]">
          {block.content}
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
      className={`max-h-[calc(100vh-260px)] min-h-0 overflow-y-auto overflow-x-auto whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--bg-card-inner)] p-4 font-mono text-[12px] leading-6 text-[var(--fg-4)] ${className}`}
    >
      {content}
    </pre>
  );
}

export function MarkdownBlockList({
  blocks,
  assetBaseUrl,
  className = "",
}: {
  blocks: MarkdownBlock[];
  assetBaseUrl?: string;
  className?: string;
}) {
  return (
    <div className={`max-h-[calc(100vh-260px)] min-h-0 space-y-4 overflow-y-auto overflow-x-hidden pr-1 text-[13px] leading-7 text-[var(--fg-4)] ${className}`}>
      {blocks.map((block, blockIndex) => renderMarkdownBlock(block, blockIndex, assetBaseUrl))}
    </div>
  );
}
