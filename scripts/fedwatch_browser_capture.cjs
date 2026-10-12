// Public CME widget, isolated Chromium session. No cookies or session URLs leave
// this process. Only rendered official HTML and non-sensitive diagnostics do.
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const chrome = process.argv[2], output = process.argv[3];
if (!chrome || !output || !path.isAbsolute(chrome) || !path.isAbsolute(output)) {
  throw new Error('absolute chrome and output paths required');
}
const parent = 'https://www.cmegroup.cn/fed-watch/';
const profile = path.join(path.dirname(output), 'profile');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const pending = new Map(), frames = new Map();
let ws, seq = 0, browser, closing = false;
function send(method, params = {}, sessionId) {
  const id = ++seq;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {pending.delete(id); reject(new Error('cdp_timeout'));}, 12000);
    pending.set(id, {resolve, reject, timer});
    ws.send(JSON.stringify({id, method, params, ...(sessionId ? {sessionId} : {})}));
  });
}
function event(m) {
  if (m.id) {
    const p = pending.get(m.id);
    if (p) {clearTimeout(p.timer); pending.delete(m.id); m.error ? p.reject(new Error('cdp_error')) : p.resolve(m.result);}
  }
  if (m.method === 'Target.attachedToTarget') {
    const {sessionId, targetInfo} = m.params;
    frames.set(sessionId, targetInfo.url);
    send('Network.enable', {}, sessionId).catch(() => {});
    send('Runtime.enable', {}, sessionId).catch(() => {});
    send('Page.enable', {}, sessionId).catch(() => {});
  }
  if (m.method === 'Page.frameNavigated' && m.sessionId) frames.set(m.sessionId, m.params.frame.url);
}
async function evaluate(expression, session) {
  const r = await send('Runtime.evaluate', {expression, returnByValue: true}, session);
  if (r.exceptionDetails) throw new Error('page_evaluation_failed');
  return r.result.value;
}
async function close() {
  if (closing) return;
  closing = true;
  if (ws?.readyState === WebSocket.OPEN) await send('Browser.close').catch(() => {});
  ws?.close();
  for (const p of pending.values()) {clearTimeout(p.timer); p.reject(new Error('capture_closed'));}
  pending.clear();
  if (browser && browser.exitCode === null) browser.kill();
}
const deadline = setTimeout(async () => {await close(); process.exit(2);}, 180000);
(async () => {
  browser = spawn(chrome, ['--no-proxy-server', '--remote-debugging-port=0',
    '--user-data-dir=' + profile, '--no-first-run', '--no-default-browser-check', 'about:blank'], {stdio: 'ignore'});
  browser.on('error', () => {});
  let port;
  for (let i = 0; i < 50; i++) {
    try {port = fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split(/\r?\n/)[0]; break;} catch {}
    await sleep(200);
  }
  if (!port || !/^\d+$/.test(port)) throw new Error('browser_start_failed');
  const targets = await (await fetch('http://127.0.0.1:' + port + '/json/list', {signal: AbortSignal.timeout(5000)})).json();
  ws = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {ws.onopen = resolve; ws.onerror = () => reject(new Error('cdp_connect_failed'));});
  ws.onmessage = m => event(JSON.parse(m.data));
  await send('Network.enable'); await send('Page.enable'); await send('Runtime.enable');
  await send('Target.setAutoAttach', {autoAttach: true, waitForDebuggerOnStart: false, flatten: true});
  await send('Page.navigate', {url: parent});
  let session, tabs;
  for (let i = 0; i < 45; i++) {
    await sleep(1000);
    await evaluate(`document.querySelector('iframe.cmeIframe')?.scrollIntoView({block:'center'})`).catch(() => {});
    for (const [sid] of frames) {
      try {
        // A target may already have navigated before Page.enable: inspect its
        // current location rather than trusting the initial attachment URL.
        tabs = await evaluate(`location.hostname === 'cmegroup-tools.quikstrike.net' ? Array.from(document.querySelectorAll('a[id*="lbMeeting"]')).map(a=>({id:a.id,text:a.textContent.trim()})) : []`, sid);
        if (tabs?.length) {session = sid; break;}
      } catch {}
    }
    if (session) break;
  }
  if (!session) {
    fs.writeFileSync(output, JSON.stringify({pages: [], meeting_tabs: 0,
      reason: 'official_widget_unavailable', frame_paths: [...frames.values()].map(url => {
        try {const u = new URL(url); return u.origin + u.pathname;} catch {return 'unknown';}
      })}), {flag: 'wx'});
    throw new Error('official_widget_unavailable');
  }
  if (tabs.length > 16) throw new Error('meeting_limit_exceeded');
  const pages = [], errors = [];
  const meetingExpr = `(()=>{const t=Array.from(document.querySelectorAll('table')).find(t=>t.querySelector('th') && Array.from(t.querySelectorAll(':scope > tbody > tr,:scope > tr')).some(r=>r.textContent.includes('Meeting Date')));return t?.innerText||''})()`;
  for (let i = 0; i < tabs.length; i++) {
    try {
      const before = await evaluate(meetingExpr, session);
      await evaluate(`document.getElementById(${JSON.stringify(tabs[i].id)}).click()`, session);
      let ready = false;
      for (let j = 0; j < 30; j++) {
        await sleep(250);
        const state = await evaluate(`({meeting:(${meetingExpr}),busy:!!(window.Sys?.WebForms?.PageRequestManager?.getInstance()?.get_isInAsyncPostBack()),active:document.getElementById(${JSON.stringify(tabs[i].id)})?.className})`, session);
        if (!state.busy && state.meeting && (i === 0 || state.meeting !== before)) {ready = true; break;}
      }
      if (!ready) throw new Error('meeting_postback_timeout');
      const body = await evaluate('document.documentElement.outerHTML', session);
      if (Buffer.byteLength(body) > 4194304) throw new Error('response_too_large');
      pages.push({tab: tabs[i].text, html: body, observed_at: new Date().toISOString()});
    } catch (e) {errors.push({tab: tabs[i].text, reason: e.message}); break;}
  }
  fs.writeFileSync(output, JSON.stringify({parent_url: parent, capture_kind: 'rendered_dom',
    meeting_tabs: tabs.length, pages, errors}), {flag: 'wx'});
  console.log(JSON.stringify({meetings_captured: pages.length, tabs: tabs.length, errors}));
})().catch(e => {console.error(e.message); process.exitCode = 1;})
  .finally(async () => {clearTimeout(deadline); await close();});
