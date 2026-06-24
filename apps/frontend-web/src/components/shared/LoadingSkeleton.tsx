type LoadingSkeletonVariant = "card" | "panel" | "table" | "page";

interface LoadingSkeletonProps {
  variant?: LoadingSkeletonVariant;
  rows?: number;
  className?: string;
}

function SkeletonLine({ width = "w-full" }: { width?: string }) {
  return <div className={`h-2 rounded-full bg-finance-bg-hover ${width}`} />;
}

export function LoadingSkeleton({ variant = "panel", rows = 4, className = "" }: LoadingSkeletonProps) {
  if (variant === "table") {
    return (
      <div className={`finance-panel space-y-2 p-3 ${className}`}>
        {Array.from({ length: rows }).map((_, index) => (
          <div key={index} className="grid grid-cols-4 gap-3">
            <SkeletonLine />
            <SkeletonLine />
            <SkeletonLine />
            <SkeletonLine width="w-2/3" />
          </div>
        ))}
      </div>
    );
  }

  if (variant === "page") {
    return (
      <div className={`space-y-3 ${className}`}>
        <div className="finance-panel space-y-3 p-4">
          <SkeletonLine width="w-1/4" />
          <SkeletonLine width="w-2/3" />
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <LoadingSkeleton variant="card" />
          <LoadingSkeleton variant="card" />
          <LoadingSkeleton variant="card" />
        </div>
      </div>
    );
  }

  return (
    <div className={`finance-panel space-y-3 p-3 ${className}`}>
      <SkeletonLine width={variant === "card" ? "w-1/2" : "w-1/3"} />
      {Array.from({ length: rows }).map((_, index) => (
        <SkeletonLine key={index} width={index % 3 === 0 ? "w-5/6" : "w-full"} />
      ))}
    </div>
  );
}
