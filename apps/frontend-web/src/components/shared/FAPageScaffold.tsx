import type { ReactNode } from "react";

interface FAPageScaffoldProps {
  hero?: ReactNode;
  intro?: ReactNode;
  status?: ReactNode;
  actions?: ReactNode;
  toolbar?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  headerClassName?: string;
}

export function FAPageScaffold({
  hero,
  intro,
  status,
  actions,
  toolbar,
  children,
  className = "",
  bodyClassName = "",
  headerClassName = "",
}: FAPageScaffoldProps) {
  const hasHeader = hero || intro || status || actions;
  const hasStatusArea = status || actions;

  return (
    <div className={`finance-page-shell fa-page-stack ${className}`}>
      {hasHeader ? (
        <div className={`fa-page-shell-header ${headerClassName}`}>
          <div className="min-w-0 flex-1">
            {hero ?? intro}
          </div>
          {hasStatusArea ? (
            <div className="fa-page-shell-status">
              {status}
              {actions}
            </div>
          ) : null}
        </div>
      ) : null}
      {toolbar}
      <div className={`fa-layout-fill ${bodyClassName}`}>{children}</div>
    </div>
  );
}
