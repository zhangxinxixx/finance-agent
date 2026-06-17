export const DATA_CATEGORY_HEADINGS: Record<string, { label: string; tone: string; accent: string }> = {
  "已确认数据": { label: "CONFIRMED", tone: "border-[var(--up-border)] bg-[var(--up-soft)] text-[var(--up)]", accent: "border-l-[var(--up)]" },
  "外部观点": { label: "EXTERNAL OPINION", tone: "border-[var(--warn-border)] bg-[var(--warn-soft)] text-[var(--warn)]", accent: "border-l-[var(--warn)]" },
  "系统推论": { label: "SYSTEM INFERENCE", tone: "border-[var(--info-border)] bg-[var(--info-soft)] text-[var(--info)]", accent: "border-l-[var(--info)]" },
};

export type MarkdownBlock =
  | { type: "heading"; level: 1 | 2 | 3; content: string }
  | { type: "list"; items: string[] }
  | { type: "image"; alt: string; src: string }
  | { type: "code"; language: string; content: string }
  | { type: "table"; content: string }
  | { type: "paragraph"; content: string };

const IMAGE_LINE_PATTERN = /^!\[([^\]]*)\]\(([^)]+)\)$/;

function isTableLine(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed) return false;
  if (trimmed.startsWith("|") || trimmed.endsWith("|")) return true;
  return trimmed.includes("|") && trimmed.split("|").length >= 3;
}

export function parseMarkdown(content: string): MarkdownBlock[] {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: MarkdownBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const language = trimmed.slice(3).trim();
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      blocks.push({ type: "code", language, content: codeLines.join("\n") });
      continue;
    }

    if (trimmed.startsWith("### ")) {
      blocks.push({ type: "heading", level: 3, content: trimmed.slice(4).trim() });
      index += 1;
      continue;
    }

    if (trimmed.startsWith("## ")) {
      blocks.push({ type: "heading", level: 2, content: trimmed.slice(3).trim() });
      index += 1;
      continue;
    }

    if (trimmed.startsWith("# ")) {
      blocks.push({ type: "heading", level: 1, content: trimmed.slice(2).trim() });
      index += 1;
      continue;
    }

    if (trimmed.startsWith("- ")) {
      const items: string[] = [];
      while (index < lines.length) {
        const candidate = lines[index].trim();
        if (!candidate.startsWith("- ")) break;
        items.push(candidate.slice(2).trim());
        index += 1;
      }
      blocks.push({ type: "list", items });
      continue;
    }

    const imageMatch = trimmed.match(IMAGE_LINE_PATTERN);
    if (imageMatch) {
      blocks.push({ type: "image", alt: imageMatch[1].trim(), src: imageMatch[2].trim() });
      index += 1;
      continue;
    }

    if (isTableLine(line)) {
      const tableLines: string[] = [];
      while (index < lines.length && isTableLine(lines[index])) {
        tableLines.push(lines[index]);
        index += 1;
      }
      blocks.push({ type: "table", content: tableLines.join("\n") });
      continue;
    }

    const paragraphLines: string[] = [];
    while (index < lines.length) {
      const candidate = lines[index];
      const candidateTrimmed = candidate.trim();
      if (!candidateTrimmed) break;
      if (
        candidateTrimmed.startsWith("# ") ||
        candidateTrimmed.startsWith("## ") ||
        candidateTrimmed.startsWith("### ") ||
        candidateTrimmed.startsWith("- ") ||
        candidateTrimmed.startsWith("```") ||
        isTableLine(candidate)
      ) {
        break;
      }
      paragraphLines.push(candidateTrimmed);
      index += 1;
    }

    if (paragraphLines.length > 0) {
      blocks.push({ type: "paragraph", content: paragraphLines.join("\n") });
      continue;
    }

    index += 1;
  }

  return blocks;
}

export function resolveAssetUrl(src: string, assetBaseUrl?: string): string {
  if (!assetBaseUrl || /^(https?:|data:|blob:|\/)/i.test(src)) {
    return src;
  }
  return new URL(src, new URL(assetBaseUrl, window.location.origin)).toString()
}
