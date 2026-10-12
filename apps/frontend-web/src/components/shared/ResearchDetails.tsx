import { createContext, useContext, useState, type ReactNode } from 'react';
const RecordDetailsContext = createContext(false);
/** Mount expensive or technical content only after the reader explicitly asks for it. */
export function ResearchDetails({ children, label = '查看详细记录', className = '' }: { children: ReactNode; label?: string; className?: string }) {
  const withinDetails = useContext(RecordDetailsContext);
  const [open, setOpen] = useState(false);
  if (withinDetails) return <>{children}</>;
  return <details className={`fa-muted-text ${className}`} onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary className="cursor-pointer py-2 fa-label text-[var(--brand-hover)]">{label}</summary>
    {open ? <RecordDetailsContext.Provider value={true}><div className="mt-2">{children}</div></RecordDetailsContext.Provider> : null}
  </details>;
}
