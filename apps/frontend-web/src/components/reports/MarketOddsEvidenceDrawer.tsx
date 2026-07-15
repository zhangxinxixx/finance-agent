import { useEffect } from "react";
import { X } from "lucide-react";
import type { MarketOddsEvidenceItemView } from "@/types/reports";

export function MarketOddsEvidenceDrawer({ item, parserVersion, schemaVersion, onClose }: { item: MarketOddsEvidenceItemView | null; parserVersion: string; schemaVersion: string; onClose: () => void }) {
  useEffect(() => {
    if (!item) return undefined;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [item, onClose]);

  if (!item) return null;
  const sourceUrl = item.source_refs
    .map((ref) => ref.url ?? ref.source_url)
    .find((value): value is string => typeof value === "string" && /^https?:\/\//.test(value));
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-[var(--bg-overlay)]" role="dialog" aria-modal="true" aria-label="赔率证据">
      <button type="button" className="min-w-0 flex-1" aria-label="关闭赔率证据" onClick={onClose} />
      <aside className="h-full w-full max-w-lg overflow-y-auto border-l border-[var(--border)] bg-[var(--bg-card)] p-4 shadow-xl">
        <div className="flex items-center justify-between gap-3">
          <h2 className="fa-section-title">赔率证据</h2>
          <button type="button" onClick={onClose} className="fa-icon-button" aria-label="关闭赔率证据" title="关闭">
            <X size={15} />
          </button>
        </div>
        <dl className="mt-4 grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-[length:var(--type-body-sm)]">
          <dt className="text-[var(--fg-5)]">事件</dt><dd className="text-[var(--fg-2)]">{item.outcome_label}</dd>
          <dt className="text-[var(--fg-5)]">锚点</dt><dd className="fa-num text-[var(--fg-2)]">page {item.page_no ?? "-"} · {item.figure_id ?? "-"}</dd>
          <dt className="text-[var(--fg-5)]">bbox</dt><dd className="fa-num break-all text-[var(--fg-2)]">{item.bbox?.join(", ") ?? "未提供"}</dd>
          <dt className="text-[var(--fg-5)]">OCR</dt><dd className="break-words text-[var(--fg-2)]">{item.ocr_text}</dd>
          <dt className="text-[var(--fg-5)]">语义</dt><dd className="fa-num text-[var(--fg-2)]">{item.probability_semantics}</dd>
          <dt className="text-[var(--fg-5)]">版本</dt><dd className="fa-num text-[var(--fg-2)]">{parserVersion} · schema {schemaVersion}</dd>
          <dt className="text-[var(--fg-5)]">来源</dt><dd>{sourceUrl ? <a className="font-semibold text-[var(--brand-hover)]" href={sourceUrl} target="_blank" rel="noreferrer">打开原始来源</a> : <span className="text-[var(--fg-4)]">来源引用已记录</span>}</dd>
        </dl>
        {item.image_url ? (
          <figure className="mt-4 overflow-hidden rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)]">
            <img src={item.image_url} alt={`${item.outcome_label} 证据裁剪图`} className="max-h-[38rem] w-full object-contain" />
            <figcaption className="border-t border-[var(--border-faint)] px-2 py-1 text-[length:var(--type-caption)] text-[var(--fg-5)]">
              {item.image_kind === "figure_crop" ? "VLM figure 裁剪图" : "原始页面图"}
            </figcaption>
          </figure>
        ) : null}
      </aside>
    </div>
  );
}
