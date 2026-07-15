import type { CSSProperties, ReactNode } from "react";

interface CMEOptionsSurfaceProps {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  bodyStyle?: CSSProperties;
}

export function CMEOptionsSurface({ title, action, children, className = "", bodyClassName = "", bodyStyle }: CMEOptionsSurfaceProps) {
  return (
    <div className={`cme-options-surface ${className}`.trim()}>
      {(title || action) && (
        <div className="cme-options-surface-header">
          {title ? <span className="cme-options-surface-title">{title}</span> : null}
          {action}
        </div>
      )}
      <div className={`cme-options-surface-body ${bodyClassName}`.trim()} style={bodyStyle}>{children}</div>
    </div>
  );
}
