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
  | MarkdownTableBlock
  | { type: "paragraph"; content: string };

export type MarkdownTableBlock = {
  type: "table";
  headers: string[];
  rows: string[][];
  aligns: Array<"left" | "center" | "right">;
};

export type InlineMarkdownToken =
  | { type: "text"; text: string }
  | { type: "bold"; text: string }
  | { type: "code"; text: string }
  | { type: "link"; text: string; href: string };

const IMAGE_LINE_PATTERN = /^!\[([^\]]*)\]\(([^)]+)\)$/;

const IMAGE_ALT_TRANSLATIONS: Array<[RegExp, string]> = [
  [/^Gold Price and its Recurring Support\/Resistance Zones$/i, "黄金价格与周期性支撑/阻力区间"],
  [/^Gold's Rate-Cut Period Cycle-High Indicators$/i, "黄金降息周期高点指标"],
  [/^Gold's Rate-Cut Period Cycle-High Indicators Chart - 图表 15-1$/i, "黄金降息周期高点指标图 - 图表 15-1"],
  [/^COMEX Aug 2026 Gold Options Intrinsic Value \(IV\) of All Options$/i, "COMEX 2026年8月黄金期权：全部期权内在价值（IV）"],
  [
    /^COMEX Aug 2026 Gold Options: Gold Price Premium \/ Discount to the Max-Pain Price Intrinsic Value \(IV\) relative to minimum IV$/i,
    "COMEX 2026年8月黄金期权：金价相对最大痛点/最低内在价值的溢价或折价",
  ],
  [
    /^COMEX GOLD OPTIONS: Contract's ΔIntrinsic Value \(ΔIV\) Max-Pain Price Jul 3, 2026$/i,
    "COMEX 黄金期权：合约△内在价值（△IV）最大痛点价格（2026-07-03）",
  ],
  [/^COMEX SILVER OPTIONS: Put\/Call Volume Ratio$/i, "COMEX 白银期权：看跌/看涨成交量比率"],
  [/^COMEX SILVER OPTIONS: Put-Option Volume \(30d EMA\)$/i, "COMEX 白银期权：看跌期权成交量（30日EMA）"],
  [/^COMEX SILVER OPTIONS: Call-Option Volume \(30d EMA\)$/i, "COMEX 白银期权：看涨期权成交量（30日EMA）"],
];

function localizeImageAlt(alt: string): string {
  const trimmed = alt.trim();
  if (!trimmed) return "";
  const translated = IMAGE_ALT_TRANSLATIONS.find(([pattern]) => pattern.test(trimmed));
  return translated?.[1] ?? trimmed;
}

function isTableLine(line: string): boolean {
  return splitTableRow(line).length >= 2;
}

function endsWithUnescapedPipe(line: string): boolean {
  let slashCount = 0;
  for (let index = line.length - 2; index >= 0 && line[index] === "\\"; index -= 1) {
    slashCount += 1;
  }
  return line.endsWith("|") && slashCount % 2 === 0;
}

export function splitTableRow(line: string): string[] {
  const trimmed = line.trim();
  if (!trimmed.includes("|")) return [];

  const start = trimmed.startsWith("|") ? 1 : 0;
  const end = endsWithUnescapedPipe(trimmed) ? trimmed.length - 1 : trimmed.length;
  const cells: string[] = [];
  let current = "";

  for (let index = start; index < end; index += 1) {
    const char = trimmed[index];
    const next = trimmed[index + 1];
    if (char === "\\" && next === "|") {
      current += "|";
      index += 1;
      continue;
    }
    if (char === "|") {
      cells.push(current.trim());
      current = "";
      continue;
    }
    current += char;
  }

  cells.push(current.trim());
  return cells;
}

export function isTableDivider(line: string): boolean {
  const cells = splitTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()));
}

export function parseAlign(cell: string): "left" | "center" | "right" {
  const trimmed = cell.trim();
  if (trimmed.startsWith(":") && trimmed.endsWith(":")) return "center";
  if (trimmed.endsWith(":")) return "right";
  return "left";
}

function normalizeRow(cells: string[], columnCount: number): string[] {
  return Array.from({ length: columnCount }, (_, index) => cells[index] ?? "");
}

export function parseTable(lines: string[]): MarkdownTableBlock | null {
  if (lines.length < 2 || !isTableDivider(lines[1])) return null;

  const headers = splitTableRow(lines[0]);
  if (headers.length === 0) return null;

  const dividerCells = splitTableRow(lines[1]);
  const columnCount = headers.length;
  return {
    type: "table",
    headers,
    aligns: normalizeRow(dividerCells, columnCount).map(parseAlign),
    rows: lines.slice(2).map((line) => normalizeRow(splitTableRow(line), columnCount)),
  };
}

function isSafeInlineHref(href: string): boolean {
  return /^(https?:|mailto:|\/|#)/i.test(href);
}

function pushText(tokens: InlineMarkdownToken[], text: string): void {
  if (!text) return;
  const previous = tokens[tokens.length - 1];
  if (previous?.type === "text") {
    previous.text += text;
    return;
  }
  tokens.push({ type: "text", text });
}

export function parseInlineMarkdown(text: string): InlineMarkdownToken[] {
  const tokens: InlineMarkdownToken[] = [];
  let index = 0;

  while (index < text.length) {
    if (text.startsWith("**", index)) {
      const end = text.indexOf("**", index + 2);
      if (end > index + 2) {
        tokens.push({ type: "bold", text: text.slice(index + 2, end) });
        index = end + 2;
        continue;
      }
    }

    if (text[index] === "`") {
      const end = text.indexOf("`", index + 1);
      if (end > index + 1) {
        tokens.push({ type: "code", text: text.slice(index + 1, end) });
        index = end + 1;
        continue;
      }
    }

    if (text[index] === "[") {
      const labelEnd = text.indexOf("](", index + 1);
      if (labelEnd > index + 1) {
        const hrefEnd = text.indexOf(")", labelEnd + 2);
        const href = hrefEnd > labelEnd + 2 ? text.slice(labelEnd + 2, hrefEnd).trim() : "";
        if (hrefEnd > labelEnd + 2 && isSafeInlineHref(href)) {
          tokens.push({ type: "link", text: text.slice(index + 1, labelEnd), href });
          index = hrefEnd + 1;
          continue;
        }
      }
    }

    pushText(tokens, text[index]);
    index += 1;
  }

  return tokens;
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
      blocks.push({ type: "image", alt: localizeImageAlt(imageMatch[1]), src: imageMatch[2].trim() });
      index += 1;
      continue;
    }

    if (isTableLine(line)) {
      const tableLines: string[] = [];
      while (index < lines.length && isTableLine(lines[index])) {
        tableLines.push(lines[index]);
        index += 1;
      }
      const table = parseTable(tableLines);
      blocks.push(table ?? { type: "paragraph", content: tableLines.join("\n") });
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

export function resolveAssetUrl(src: string, assetBaseUrl?: string, assetVersion?: string): string {
  if (!assetBaseUrl || /^(https?:|data:|blob:|\/)/i.test(src)) {
    return src;
  }
  const url = new URL(src, new URL(assetBaseUrl, window.location.origin));
  if (assetVersion) {
    url.searchParams.set("v", assetVersion);
  }
  return url.toString();
}
