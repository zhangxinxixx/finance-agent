export type PageDataLayer = "dws" | "output" | "ads" | "blocked";

export interface PageRequestClassification {
  allowed: boolean;
  layer: PageDataLayer;
  reason: string;
}

export function classifyPageRequest(input: string): PageRequestClassification;
export function assertPageRequestAllowed(input: string): PageRequestClassification;
export function summarizeEvidenceRecord(record: unknown, depth?: number): unknown | null;
