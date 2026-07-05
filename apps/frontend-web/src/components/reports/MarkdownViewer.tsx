import { MarkdownBlockList, MarkdownFallbackPre } from "./MarkdownViewerBlocks";
import { parseMarkdown } from "./markdownViewerModel";

export function MarkdownViewer({
  content,
  assetBaseUrl,
  assetVersion,
  blockListClassName,
  fallbackClassName,
}: {
  content: string;
  assetBaseUrl?: string;
  assetVersion?: string;
  blockListClassName?: string;
  fallbackClassName?: string;
}) {
  const blocks = parseMarkdown(content);

  if (blocks.length === 0) {
    return <MarkdownFallbackPre content={content} className={fallbackClassName} />;
  }

  return <MarkdownBlockList blocks={blocks} assetBaseUrl={assetBaseUrl} assetVersion={assetVersion} className={blockListClassName} />;
}

export default MarkdownViewer;
