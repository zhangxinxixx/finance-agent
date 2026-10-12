import { FAEmptyState } from '@/components/shared/FAEmptyState';
import { EvidenceRecordActions } from '@/components/shared/EvidenceRecordActions';
import { MarkdownViewer } from '@/components/reports/MarkdownViewer';
import { ResearchDetails } from '@/components/shared/ResearchDetails';
import { isMachineText, readableText, structuredResearch } from '@/lib/researchReading';
import { useState } from 'react';
import type { ReportArtifactContentView } from '@/types/reports';

const HTML_LABELS: Array<[RegExp, string]> = [
  [/\b(?:price|last price|close)\b/gi, '价格'],
  [/\b(?:date|trade date)\b/gi, '日期'],
  [/\b(?:time|timestamp)\b/gi, '时间'],
  [/\bsummary\b/gi, '摘要'],
  [/\b(?:report|research)\b/gi, '研究报告'],
  [/\b(?:risk|risks|risk points)\b/gi, '风险与限制'],
  [/\bstatus\b/gi, '状态'],
  [/\bsource(?:s)?\b/gi, '来源依据'],
  [/\bconfidence\b/gi, '判断把握程度（非胜率）'],
  [/\bdirection\b/gi, '研究方向'],
  [/\btrigger(?:s)?\b/gi, '触发条件'],
  [/\binvalidation\b/gi, '失效条件'],
  [/\bsupport\b/gi, '支撑'],
  [/\bresistance\b/gi, '阻力'],
  [/\bdelta\b/gi, '变化量或价格敏感度（含义待核对）'],
  [/\bchange\b/gi, '变化'],
  [/\bvalue\b/gi, '数值'],
  [/\bunit\b/gi, '单位'],
  [/\b(?:macro|macroeconomics)\b/gi, '宏观'],
  [/\boptions?\b/gi, '期权'],
  [/\bchart\b/gi, '图表'],
  [/\bgold\b/gi, '黄金'],
  [/\bxauusd\b/gi, '现货黄金（XAUUSD）'],
  [/\bdxy\b/gi, '美元指数（DXY）'],
  [/\bgc\b/gi, '黄金期货（GC）'],
  [/\bcme\b/gi, '芝商所（CME）'],
];
const HTML_ALLOWED_TECHNICAL = /\b(?:XAUUSD|DXY|GC|CME|ATR|GEX|OI|USD|US10Y|TIPS|FEDWATCH|RRP|TGA|SOFR|FRED|API|ISO|UTC|GMT|AM|PM|ms|bp)\b/gi;

function parseDetachedHtml(content: string): Document | null {
  if (typeof DOMParser === 'undefined') return null;
  return new DOMParser().parseFromString(content, 'text/html');
}

function htmlTextLabel(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return value;
  if (isMachineText(trimmed)) return '中文说明缺口：原始报告中的技术字段尚未整理（完整原文可复制）';

  let translated = trimmed;
  for (const [pattern, label] of HTML_LABELS) translated = translated.replace(pattern, label);
  const readable = readableText(translated, true);
  const candidate = readable || translated;
  const untranslated = candidate.replace(HTML_ALLOWED_TECHNICAL, '');
  if (readable && !/[A-Za-z]{3,}/.test(untranslated)) return readable;
  if (/\p{Script=Han}/u.test(translated) && !/[A-Za-z]{3,}/.test(translated.replace(HTML_ALLOWED_TECHNICAL, ''))) return translated;
  if (/\d/.test(translated) && !/[A-Za-z]{3,}/.test(translated.replace(HTML_ALLOWED_TECHNICAL, ''))) return translated;
  return '中文说明缺口：原始报告中的英文标签尚未整理（完整原文可复制）';
}

/** Build a detached, read-only HTML display copy; never inspect or mutate app DOM. */
export function htmlDisplayDocument(content: string): string {
  const document = parseDetachedHtml(content);
  if (!document) return '';

  document.querySelectorAll('script,noscript,meta[http-equiv="refresh"],iframe').forEach((node) => node.remove());
  document.querySelectorAll('*').forEach((element) => {
    for (const attribute of Array.from(element.attributes)) {
      if (/^on/i.test(attribute.name)) {
        element.removeAttribute(attribute.name);
      } else if (['title', 'aria-label', 'alt'].includes(attribute.name)) {
        element.setAttribute(attribute.name, htmlTextLabel(attribute.value));
      } else if (attribute.name === 'href' && /^javascript:/i.test(attribute.value)) {
        element.removeAttribute(attribute.name);
      }
    }
  });

  const transformTextNodes = (parent: Node) => {
    for (const child of Array.from(parent.childNodes)) {
      if (child.nodeType === 3) {
        const raw = child.nodeValue ?? '';
        const trimmed = raw.trim();
        if (trimmed) {
          const leading = raw.slice(0, raw.indexOf(trimmed));
          const trailing = raw.slice(raw.indexOf(trimmed) + trimmed.length);
          child.nodeValue = `${leading}${htmlTextLabel(trimmed)}${trailing}`;
        }
      } else if (child.nodeType === 1 && !/^(?:STYLE|SCRIPT|NOSCRIPT)$/i.test((child as Element).tagName)) {
        transformTextNodes(child);
      }
    }
  };
  transformTextNodes(document.body);
  return document.documentElement.outerHTML;
}

/** Parse the detached report artifact for the concise reading layer. */
export function htmlResearch(content: string): string {
  const document = parseDetachedHtml(htmlDisplayDocument(content));
  if (!document) return 'HTML 原始报告暂无法在当前环境转换；请复制原始记录核对。';
  const blocks = document.body.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li,tr');
  return Array.from(blocks).filter((node) => !node.closest('script,style,nav,footer,pre,code')).map((node) => {
    const text = node.textContent?.trim() ?? '';
    return /^H[1-6]$/.test(node.tagName) ? `${'#'.repeat(Number(node.tagName[1]))} ${text}` : text;
  }).join('\n');
}

function jsonArtifactRecord(content: string): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(content);
    if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>;
  } catch {
    // Keep the original text copyable when the detached artifact is malformed.
  }
  return { content };
}

function sourceRefCount(content: string): number | null {
  try {
    const value: unknown = JSON.parse(content);
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const refs = (value as Record<string, unknown>).source_refs;
    return Array.isArray(refs) ? refs.length : null;
  } catch {
    return null;
  }
}

function RawArtifactActions({ label, content, sourceEndpoint }: { label: string; content: string; sourceEndpoint?: string }) {
  const [feedback, setFeedback] = useState('');
  const [copying, setCopying] = useState(false);

  async function copyOriginal() {
    if (copying) return;
    setCopying(true);
    setFeedback('');
    try {
      await navigator.clipboard.writeText(content);
      setFeedback('未改原文已复制。');
    } catch {
      setFeedback('复制失败，请确认浏览器允许访问剪贴板后重试。');
    } finally {
      setCopying(false);
    }
  }

  return (
    <div className="space-y-2">
      <p className="fa-muted-text">{label}仅通过复制或原始来源链接核对，页面展示副本不会修改原文。</p>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={copying}
          onClick={copyOriginal}
          className="fa-label rounded border border-[var(--border)] px-3 py-1.5 text-[var(--fa-text-body)] hover:bg-[var(--info-soft)] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {copying ? '正在复制原文…' : '复制未改原文'}
        </button>
        {sourceEndpoint ? (
          <a className="fa-label text-[var(--brand)] underline" href={sourceEndpoint} target="_blank" rel="noreferrer">
            打开原始来源
          </a>
        ) : null}
      </div>
      <p className="fa-muted-text" role="status" aria-live="polite" aria-atomic="true">{feedback}</p>
    </div>
  );
}

export function ReportArtifactPanel({ tab }: { tab: ReportArtifactContentView | null }) {
  if (!tab?.available) return <FAEmptyState title="当前内容暂不可展示" description="本报告尚无可用研究正文。" />;
  let content = tab.content;
  const displayHtml = tab.format === 'html' ? htmlDisplayDocument(tab.content) : '';
  if (tab.format === 'json') {
    try { content = structuredResearch(JSON.parse(content)); } catch { content = ''; }
  } else if (tab.format === 'html') content = htmlResearch(tab.content);
  return <section className="min-w-0 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] p-4">
    <MarkdownViewer readingMode={tab.format === 'markdown' ? 'full' : 'concise'} content={content} assetBaseUrl={tab.asset_base_url ?? undefined} assetVersion={tab.path ?? undefined} />
    <ResearchDetails label="查看原始报告">
      {tab.format === 'html' ? (
        <div className="space-y-3">
          <p className="fa-muted-text">以下为保留图表、SVG 与表格的隔离中文展示副本；脚本和嵌套页面不会执行。完整未改 HTML 可复制或从原始来源打开。</p>
          {displayHtml ? (
            <iframe title="中文阅读副本" sandbox="" srcDoc={displayHtml} className="h-[72vh] w-full border border-[var(--border)]" />
          ) : <FAEmptyState title="原始 HTML 暂无法展示" description="请复制未改原文或打开原始来源核对。" />}
          <RawArtifactActions label="原始 HTML" content={tab.content} sourceEndpoint={tab.source_endpoint} />
        </div>
      ) : tab.format === 'json' ? (
          <div className="space-y-2">
            <p className="fa-muted-text">
              原始证据字段已保留，可复制完整记录或打开原始来源核对；页面正文使用中文业务说明。
              {sourceRefCount(tab.content) !== null ? ` 来源依据：${sourceRefCount(tab.content)} 条。` : ''}
            </p>
            <EvidenceRecordActions label="原始证据记录" record={jsonArtifactRecord(tab.content)} />
            {tab.source_endpoint ? (
              <a
                href={tab.source_endpoint}
                target="_blank"
                rel="noreferrer"
                className="inline-flex text-[length:var(--type-caption)] font-semibold text-[var(--brand)] underline"
              >
                打开原始证据来源
              </a>
            ) : null}
          </div>
        ) : <RawArtifactActions label="原始 Markdown" content={tab.content} sourceEndpoint={tab.source_endpoint} />}
    </ResearchDetails>
  </section>;
}
