import { FACard } from "@/components/shared/FACard";
import type { GlobalConfigItem, SystemInfoItem } from "@/adapters/settings";
import { SettingsKVRow } from "./SettingsKVRow";

interface SettingsSystemCardProps {
  title: string;
  eyebrow: string;
  items: GlobalConfigItem[] | SystemInfoItem[];
}

export function SettingsSystemCard({ title, eyebrow, items }: SettingsSystemCardProps) {
  return (
    <FACard title={title} eyebrow={eyebrow} accent="info">
      <div className="space-y-1.5">
        {items.map((item) => (
          <SettingsKVRow key={item.label} label={item.label} value={item.value} mono={item.label.includes("Root")} />
        ))}
      </div>
    </FACard>
  );
}
