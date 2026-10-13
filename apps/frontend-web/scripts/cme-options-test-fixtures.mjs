// Synthetic responses only. No market or trading meaning.
export function cmeFixture(complete = false, date = '2026-10-13') {
  return {
    trade_date: date, run_id: `synthetic-${date}`, snapshot_id: `synthetic-${date}`,
    has_data: true,
    data_source: { product: 'OG', status: complete ? 'FINAL' : 'PRELIM', expiries: ['OCT26', 'DEC26'], row_count: 3,
      report_date: date, input_snapshot_ids: [`synthetic-${date}`] },
    parameters: { report_p0: 4000, p0: 4000, used_real_gex: true, model: 'black-76' },
    wall_scores: [
      { strike: 4100, side: 'CALL', wall_type: 'Call Wall', ...(complete ? { oi: 120, wall_score: 2.5 } : {}), delta_oi: -12, pnt: null },
      { strike: 4050, side: 'CALL', wall_type: 'Call Wall', oi: 0, wall_score: 0, delta_oi: 0, pnt: 0 },
      { strike: 3900, side: 'PUT', wall_type: 'Put Wall', oi: 80, wall_score: 1.25, delta_oi: 15, pnt: 1.5 },
    ],
    support_resistance: { resistance: [{ strike: 4100, wall_score: complete ? 2.5 : null, distance_pct: complete ? 2.5 : null }],
      support: [{ strike: 3900, wall_score: 0, distance_pct: -2.5 }] },
    gex: { netgex_aggregate: { net_gex: -150, net_gex_direction: 'negative', gamma_zero: { price: 4000, method: 'synthetic' } },
      by_expiry: {
        OCT26: { gex_top: [
          { strike: 4100, call_gex: complete ? 150 : null, put_gex: -20, net_gex: complete ? 130 : null, total_gex: complete ? 170 : null },
          { strike: 4050, call_gex: 0, put_gex: 0, net_gex: 0, total_gex: 0 },
          { strike: 3900, call_gex: 40, put_gex: -80, net_gex: -40, total_gex: 120 },
        ], summary: { call_gex: complete ? 190 : null, put_gex: -100, net_gex: -150, total_gex: complete ? 290 : null }, iv_skew: {} },
        DEC26: { gex_top: [{ strike: 4200, call_gex: 500, put_gex: -200, net_gex: 300, total_gex: 700 }],
          summary: { call_gex: 500, put_gex: -200, net_gex: 300, total_gex: 700 }, iv_skew: {} },
      } },
    data_quality: { warnings: ['隔离合成响应：不代表真实市场；部分字段未提供。'], categories: { invalid: 1 } },
    source_trace: [{ name: '隔离合成响应', trade_date: date, snapshot_id: `synthetic-${date}`, source_ref: 'synthetic-only', status: 'warn' }],
  };
}
