import type { AgentPromptRegistry } from "@/types/agent-registry";

export function promptTemplateText(prompt: AgentPromptRegistry | undefined): string {
  const template = prompt?.template;
  if (template == null) return "";
  if (typeof template === "string") return template.trim();
  // Compound templates, for example VLM multi-prompt payloads, stay readable in governance UI.
  try {
    return JSON.stringify(template, null, 2);
  } catch {
    return String(template);
  }
}

export function promptTemplatePayload(prompt: AgentPromptRegistry | undefined): Record<string, unknown> {
  const template = prompt?.template;
  if (template && typeof template === "object" && !Array.isArray(template)) {
    return template;
  }
  const text = typeof template === "string" ? template.trim() : "";
  return text ? { template: text } : {};
}

export function formatPromptVersionTime(value: string | null | undefined): string {
  if (!value) return "unknown";
  return value.replace("T", " ").replace("Z", "");
}
