import { FACard } from "@/components/shared/FACard";
import type { GlobalConfigItem, SystemInfoItem } from "@/adapters/settings";
import { SettingsKVRow } from "./SettingsKVRow";

interface SettingsSystemCardProps {
  title: string;
  eyebrow: string;
  items: GlobalConfigItem[] | SystemInfoItem[];
}

export function SettingsSystemCard({ title, eyebrow, items }: SettingsSystemCardProps) {
  const isEnvironment = title === "环境路径";
  const rows = (
    <div className="space-y-1.5">
      {items.map((item) => (
        <SettingsKVRow key={item.label} label={item.label} value={item.value} mono={item.label.includes("Root")} />
      ))}
    </div>
  );
  return (
    <FACard title={title} eyebrow={eyebrow} accent="info">
      {isEnvironment ? (
        <details>
          <summary className="cursor-pointer text-[11px] font-semibold text-[var(--fg-3)]">查看环境路径与运行目录</summary>
          <div className="mt-2">{rows}</div>
        </details>
      ) : rows}
    </FACard>
  );
}
