export interface HistoryObservation {
  date: string;
}

/** Keep dates attached to their values; never interpolate missing observations. */
export function historyObservationSegments(rows: HistoryObservation[], key: string) {
  const observations = rows
    .filter((row) => row && typeof row.date === "string" && Number.isFinite(Date.parse(row.date)))
    .map((row) => ({ date: row.date, time: Date.parse(row.date), value: (row as unknown as Record<string, unknown>)[key] }))
    .sort((a, b) => a.time - b.time);
  const segments: Array<Array<{ date: string; time: number; value: number }>> = [];
  let current: (typeof segments)[number] = [];
  for (const row of observations) {
    if (typeof row.value !== "number" || !Number.isFinite(row.value)) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      current.push({ ...row, value: row.value });
    }
  }
  if (current.length) segments.push(current);
  return segments;
}
