/** Display labels only. Unknown values never imply a successful business state. */
const sources: Record<string, string> = {
  cme: '芝商所', 'cme daily bulletin': '芝商所每日公告', fred: '美国经济数据库',
  treasury: '美国财政部', 'us treasury': '美国财政部', fed: '美联储', federal_reserve: '美联储', 'federal reserve': '美联储',
  reuters: '路透社', reuters_public_news: '路透快讯', bloomberg: '彭博社',
  jin10: '金十数据', openbb: '宏观数据平台', 'openbb macro/market': '宏观与行情数据平台', twelvedata: '市场行情服务',
  source_api: '来源接口', macro_latest: '宏观数据快照', api: '本地数据接口',
};
export function readerSource(value: string | null | undefined, fallback = '已关联依据记录'): string {
  const text = value?.trim();
  if (!text) return '来源未提供';
  const known = sources[text.toLowerCase()];
  if (known) return known;
  if (/^(?:https?:|\/|[a-z]+_).*|storage\/|raw\/|parsed\/|[a-f\d]{8}-[a-f\d-]{27,}/i.test(text)) return fallback;
  if (/[\u3400-\u9fff]/.test(text)) return text;
  return fallback;
}
export function readerValue(value: string | null | undefined, fallback = '说明尚未提供'): string {
  const text = value?.trim();
  if (!text) return '未提供';
  if (/^(?:https?:|\/)|storage\/|raw\/|parsed\/|[a-f\d]{8}-[a-f\d-]{27,}|\b[a-z]+_[a-z_]+\b/i.test(text)) return fallback;
  if (/[\u3400-\u9fff]/.test(text) || !/[a-z]/i.test(text)) return text;
  return fallback;
}
