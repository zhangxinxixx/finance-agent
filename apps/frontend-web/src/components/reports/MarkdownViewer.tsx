import { MarkdownBlockList, MarkdownFallbackPre } from "./MarkdownViewerBlocks";
import { parseMarkdown } from "./markdownViewerModel";

export function MarkdownViewer({ content, assetBaseUrl }: { content: string; assetBaseUrl?: string }) {
  const blocks = parseMarkdown(content);

  if (blocks.length === 0) {
    return <MarkdownFallbackPre content={content} />;
  }

  return <MarkdownBlockList blocks={blocks} assetBaseUrl={assetBaseUrl} />;
}

export default MarkdownViewer;
