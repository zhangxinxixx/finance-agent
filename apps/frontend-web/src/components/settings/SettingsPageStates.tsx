import { ErrorState } from "@/components/shared/ErrorState";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";

export function SettingsPageLoadingState() {
  return (
    <div className="finance-page-shell">
      <div className="space-y-3">
        <LoadingSkeleton variant="page" />
        <div className="grid gap-3 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <LoadingSkeleton key={index} variant="card" rows={4} />
          ))}
        </div>
      </div>
    </div>
  );
}

export function SettingsPageErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="finance-page-shell">
      <ErrorState title="设置页不可用" message={message} onRetry={onRetry} retryLabel="重试" />
    </div>
  );
}
