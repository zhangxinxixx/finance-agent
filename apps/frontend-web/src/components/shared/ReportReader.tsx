import type { ReactNode } from "react";

interface ReportReaderProps {
  children: ReactNode;
  className?: string;
}

export function ReportReader({ children, className = "" }: ReportReaderProps) {
  return <article className={`report-reader ${className}`}>{children}</article>;
}
