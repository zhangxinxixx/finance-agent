export function formatSettingsTime(value: string | null | undefined): string {
  if (!value) return "unknown";
  return value.replace("T", " ").replace("Z", "");
}
