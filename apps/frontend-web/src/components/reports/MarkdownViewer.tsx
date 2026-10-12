import { MarkdownBlockList, parseFullMarkdown } from './MarkdownViewerBlocks';
import { parseMarkdown } from './markdownViewerModel';
import { researchReading } from '../../lib/researchReading';
import { ResearchDetails } from '../shared/ResearchDetails';

export function MarkdownViewer({ content, assetBaseUrl, assetVersion, blockListClassName, readingMode = "concise" }: {
  readingMode?: "concise" | "full"; content: string; assetBaseUrl?: string; assetVersion?: string; blockListClassName?: string; fallbackClassName?: string;
}) {
  if (readingMode === "full") return <article className="fa-body-text min-w-0 report-reading-full">
    {content.trim()
      ? <MarkdownBlockList full blocks={parseFullMarkdown(content)} assetBaseUrl={assetBaseUrl} assetVersion={assetVersion} className={blockListClassName} />
      : <p className="fa-muted-text">本报告正文为空，暂不可阅读。</p>}
  </article>;
  const reading = researchReading(content);
  const visibleRisks = reading.risks.filter((risk) => !reading.highlights.includes(risk));
  const prose = (lines: string[]) => lines.map((line, index) => `${index && line.startsWith("|") && lines[index - 1].startsWith("|") ? "\n" : index ? "\n\n" : ""}${line}`).join("");
  return <article className="fa-body-text space-y-3">
    {reading.highlights.length ? <MarkdownBlockList blocks={parseMarkdown(prose(reading.highlights))} assetBaseUrl={assetBaseUrl} assetVersion={assetVersion} className={blockListClassName} />
      : <p className="fa-muted-text">暂无可提取的研究重点，请核对报告是否完整。</p>}
    {visibleRisks.length ? <section aria-label="风险与限制" className="border-l-2 border-[var(--warn)] bg-[var(--warn-soft)] p-3">
      <h3 className="fa-card-title">风险与限制</h3>
      <ul className="mt-1 space-y-1">{visibleRisks.slice(0, 12).map((risk) => <li key={risk}>{risk.length > 900 ? <><p>存在较长的风险说明，需展开核实；暂不能据此确认参考条件。</p><ResearchDetails label="查看完整风险说明">{risk}</ResearchDetails></> : risk}</li>)}</ul>
      {visibleRisks.length > 12 ? <><p>另有 {visibleRisks.length - 12} 项限制尚需核实。</p><ResearchDetails label="查看其余风险"><ul>{visibleRisks.slice(12).map((risk) => <li key={risk}>{risk.length > 900 ? <><p>存在较长的风险说明，需展开核实；暂不能据此确认参考条件。</p><ResearchDetails label="查看完整风险说明">{risk}</ResearchDetails></> : risk}</li>)}</ul></ResearchDetails></> : null}
    </section> : null}
    {reading.remaining.length ? <ResearchDetails label="展开其余研究正文"><MarkdownBlockList blocks={parseMarkdown(prose(reading.remaining))} assetBaseUrl={assetBaseUrl} assetVersion={assetVersion} /></ResearchDetails> : null}
  </article>;
}
export default MarkdownViewer;
