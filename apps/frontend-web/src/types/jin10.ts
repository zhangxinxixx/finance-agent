export interface Jin10Quote {
  price: number | null;
  change: number | null;
  change_pct: number | null;
  time: string | null;
  source: string | null;
}

export interface Jin10QuotesResponse {
  status?: string;
  counts: {
    articles_headlines: number;
    calendar_events: number;
    flash_news: number;
  };
  kline_codes: string[];
  quotes: Record<string, Jin10Quote>;
  generated_at?: string;
}
