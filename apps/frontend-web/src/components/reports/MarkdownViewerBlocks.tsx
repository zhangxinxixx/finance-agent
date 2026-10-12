import { createContext, useContext, type ReactNode } from "react";
import {
  DATA_CATEGORY_HEADINGS,
  parseInlineMarkdown,
  parseMarkdown,
  type MarkdownBlock,
  type MarkdownTableBlock,
} from "./markdownViewerModel";

type ReadingBlock = Exclude<MarkdownBlock, { type: "heading" }> | {
  type: "heading"; level: 1 | 2 | 3 | 4 | 5 | 6; content: string;
};

/** Parse original prose without the compact reading transform. Isolate figures
 * and deeper headings, which the existing compact parser does not recognize. */
export function parseFullMarkdown(content: string): ReadingBlock[] {
  const blocks: ReadingBlock[] = [];
  let pending: string[] = [];
  let fenced = false;
  const flush = () => { blocks.push(...parseMarkdown(pending.join("\n"))); pending = []; };
  for (const line of content.replace(/\r\n/g, "\n").split("\n")) {
    if (line.trim().startsWith("```")) fenced = !fenced;
    const image = !fenced && line.trim().match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
    const heading = !fenced && line.match(/^(#{4,6})\s+(.+)$/);
    if (image) {
      flush();
      blocks.push({ type: "image", alt: image[1], src: image[2].trim() });
    } else if (heading) {
      flush();
      blocks.push({ type: "heading", level: heading[1].length as 4 | 5 | 6, content: heading[2] });
    } else pending.push(line);
  }
  flush();
  return blocks;
}

function safeImageUrl(src: string, assetBaseUrl?: string, assetVersion?: string): string | undefined {
  // Disallow executable schemes and control-character URL obfuscation.
  if (/[\u0000-\u0020\u007f]/.test(src) || /^(?!https?:)[a-z][a-z\d+.-]*:/i.test(src) || src.startsWith("\\")) return undefined;
  if (!assetBaseUrl || /^(https?:|\/)/i.test(src)) return src;
  try {
    const origin = typeof window === "undefined" ? "http://localhost" : window.location.origin;
    const url = new URL(src, new URL(assetBaseUrl, origin));
    if (!/^https?:$/.test(url.protocol)) return undefined;
    if (assetVersion) url.searchParams.set("v", assetVersion);
    return url.toString();
  } catch { return undefined; }
}

const InlineAssets = createContext<{ assetBaseUrl?: string; assetVersion?: string; full?: boolean }>({});

function InlineMarkdown({ text }: { text: string }) {
  const assets = useContext(InlineAssets);
  // Inline code is literal text, even when it contains image syntax.
  const image = assets.full ? Array.from(text.matchAll(/`[^`]*`|!\[([^\]]*)\]\(([^)]+)\)/g)).find((match) => match[1] !== undefined) : undefined;
  if (image) {
    const src = safeImageUrl(image[2].trim(), assets.assetBaseUrl, assets.assetVersion);
    return <>
      <InlineMarkdown text={text.slice(0, image.index)} />
      {src ? <img src={src} alt={image[1]} loading="eager" decoding="async" /> : <span>{image[1]}</span>}
      <InlineMarkdown text={text.slice(image.index + image[0].length)} />
    </>;
  }
  return (
    <>
      {parseInlineMarkdown(text).map((token, index) => {
        const key = `${token.type}-${index}`;
        if (token.type === "bold") return <strong key={key}>{assets.full ? <InlineMarkdown text={token.text} /> : token.text}</strong>;
        if (token.type === "code") return <code key={key}>{token.text}</code>;
        if (token.type === "link") {
          return (
            <a key={key} href={token.href} target="_blank" rel="noreferrer">
              {assets.full ? <InlineMarkdown text={token.text} /> : token.text}
            </a>
          );
        }
        return <span key={key}>{token.text}</span>;
      })}
    </>
  );
}

function renderHeading(level: 1 | 2 | 3 | 4 | 5 | 6, content: string, key: string): ReactNode {
  const category = DATA_CATEGORY_HEADINGS[content];

  if (level === 1) {
    return <h1 key={key} className="fa-page-title"><InlineMarkdown text={content} /></h1>;
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

  const Heading = `h${level}` as "h3" | "h4" | "h5" | "h6";
  return <Heading key={key} className="fa-card-title"><InlineMarkdown text={content} /></Heading>;
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
  block: ReadingBlock,
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
      const src = safeImageUrl(block.src, assetBaseUrl, assetVersion);
      const figureLabel = typeof figureNumber === "number" ? `图表 ${figureNumber}` : "图表";
      const figureCaption = block.alt ? `${figureLabel} · ${block.alt}` : figureLabel;
      return (
        <figure key={key} className="space-y-2 rounded-lg border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
          {src ? <img
            src={src}
            alt={block.alt || "report image"}
            className="max-h-[640px] w-full rounded-md object-contain"
            loading="eager"
            decoding="async"
          /> : <p className="fa-muted-text">图片地址不可安全展示：{block.alt || "report image"}</p>}
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
  full = false,
}: {
  blocks: ReadingBlock[];
  assetBaseUrl?: string;
  assetVersion?: string;
  className?: string;
  full?: boolean;
}) {
  let figureCount = 0;
  return (
    <InlineAssets.Provider value={{ assetBaseUrl, assetVersion, full }}><div className={`report-prose min-h-0 min-w-0 space-y-4 pr-1 text-[length:var(--text-13)] leading-[1.85] text-[var(--fg-4)] ${className}`}>
      {blocks.map((block, blockIndex) => {
        const figureNumber = block.type === "image" ? ++figureCount : undefined;
        return renderMarkdownBlock(block, blockIndex, assetBaseUrl, assetVersion, figureNumber);
      })}
    </div></InlineAssets.Provider>
  );
}
