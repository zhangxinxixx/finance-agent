import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

// Uses installed dependencies only. In an isolated worktree, supply NODE_PATH.
const require = createRequire(import.meta.url);
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = resolve(frontend, "src/components/shared/EvidenceRecordActions.tsx");
const options = {
  target: ts.ScriptTarget.ES2020,
  module: ts.ModuleKind.CommonJS,
  moduleResolution: ts.ModuleResolutionKind.Node10,
  jsx: ts.JsxEmit.ReactJSX,
  strict: true,
  skipLibCheck: true,
  noEmitOnError: true,
  typeRoots: [dirname(dirname(require.resolve("@types/react/package.json")))],
};
const program = ts.createProgram([source], options);
let compiled;
const emitted = program.emit(undefined, (filename, text) => {
  if (filename.endsWith("EvidenceRecordActions.js")) compiled = text;
});
const diagnostics = [...ts.getPreEmitDiagnostics(program), ...emitted.diagnostics];
assert.equal(diagnostics.length, 0, ts.formatDiagnosticsWithColorAndContext(diagnostics, {
  getCanonicalFileName: (name) => name,
  getCurrentDirectory: () => frontend,
  getNewLine: () => "\n",
}));
assert.ok(compiled, "组件必须通过 TypeScript 检查并实际编译");
const module = { exports: {} };
runInNewContext(compiled, { require, module, exports: module.exports, URL }, { filename: source });
const { EvidenceRecordActions } = module.exports;
assert.equal(typeof EvidenceRecordActions, "function");
const render = (props) => renderToStaticMarkup(React.createElement(EvidenceRecordActions, props));
const record = {
  source_ref: "/private/raw/gold.json",
  snapshot_id: "a18e3ca2-573a-45d5-bd8c-2d5a842ec09d",
  decision: "SUSPENDED_DATA",
  source_url: "https://example.org/internal/raw",
  nested: { untouched: [0, false, "original_evidence"] },
};
const html = render({ record });
assert.match(html, /复制依据记录/);
assert.match(html, /依据记录可复制完整内容以核对依据。/);
assert.match(html, /role="status"/);
assert.doesNotMatch(html, /disabled=""/);
for (const raw of [...Object.keys(record), record.source_ref, record.snapshot_id, record.decision, record.source_url, "original_evidence"]) {
  assert.ok(!html.includes(raw), `原始机器信息不应进入 HTML: ${raw}`);
}
assert.equal(JSON.stringify(record), JSON.stringify({
  source_ref: "/private/raw/gold.json",
  snapshot_id: "a18e3ca2-573a-45d5-bd8c-2d5a842ec09d",
  decision: "SUSPENDED_DATA",
  source_url: "https://example.org/internal/raw",
  nested: { untouched: [0, false, "original_evidence"] },
}));
for (const missing of [null, undefined]) {
  const empty = render({ record: missing });
  assert.match(empty, /依据记录未提供。/);
  assert.match(empty, /<button[^>]*disabled=""[^>]*>复制依据记录<\/button>/);
}
for (const present of [false, 0, "", []]) {
  assert.doesNotMatch(render({ record: present }), /disabled=""/);
}
assert.match(render({ record, label: "宏观依据" }), /宏观依据可复制完整内容/);
for (const url of ["https://example.org/source", "http://example.org/source"]) {
  const linked = render({ record, url });
  assert.ok(linked.includes(`href="${url}"`));
  assert.match(linked, /target="_blank" rel="noreferrer"/);
  assert.match(linked, />查看原始来源<\/a>/);
  assert.ok(!linked.replace(/<[^>]*>/g, "").includes(url), "URL 不应成为可读文本");
}
for (const url of [null, "", "javascript:alert(1)", "data:text/html,test", "file:///private/raw", "/source", "//example.org/source", "invalid", "https://user:password@example.org", "https://user@example.org", "https://:password@example.org"]) {
  const rejected = render({ record, url });
  assert.doesNotMatch(rejected, /href=|<a\b|查看原始来源/);
}
// Serialization belongs to the click handler, never the render path.
const circular = {};
circular.self = circular;
for (const value of [circular, 1n, { toJSON() { throw new Error("不得在呈现时序列化"); } }]) {
  assert.match(render({ record: value }), /复制依据记录/);
}

// Exercise the actual click handler with controlled hooks and clipboard;
// this supplements SSR and does not claim browser interaction coverage.
function clickHarness(value, clipboard) {
  const states = [];
  const runtime = { exports: {} };
  const react = { ...React, useState(initial) {
    const index = states.length;
    states.push(initial);
    return [initial, (next) => { states[index] = next; }];
  } };
  runInNewContext(compiled, {
    require: (name) => name === "react" ? react : require(name),
    module: runtime,
    exports: runtime.exports,
    URL,
    navigator: { clipboard },
  }, { filename: source });
  const tree = runtime.exports.EvidenceRecordActions({ record: value });
  const button = tree.props.children[1].props.children[0];
  return { states, button };
}
const copied = [];
const success = clickHarness(record, { async writeText(value) { copied.push(value); } });
assert.equal(copied.length, 0, "呈现时不得复制");
await success.button.props.onClick();
assert.equal(copied[0], JSON.stringify(record, null, 2), "复制必须保留全部原始字段");
assert.equal(success.states[0], "依据记录已复制。");
assert.equal(success.states[1], false);
for (const [value, clipboard] of [
  [circular, { async writeText() { assert.fail("序列化失败不得访问剪贴板"); } }],
  [1n, { async writeText() { assert.fail("序列化失败不得访问剪贴板"); } }],
  [record, { async writeText() { throw new Error("permission denied"); } }],
  [record, undefined],
]) {
  const failure = clickHarness(value, clipboard);
  await failure.button.props.onClick();
  assert.match(failure.states[0], /^复制失败/);
  assert.doesNotMatch(failure.states[0], /permission denied/);
  assert.equal(failure.states[1], false);
}
const emptyClick = clickHarness(null, { async writeText() { assert.fail("空记录不得复制"); } });
await emptyClick.button.props.onClick();
assert.equal(emptyClick.states[0], "");
console.log("PASS: TypeScript 编译、真实 React SSR 与受控点击；中文按钮/空态、原始信息隔离、来源 URL 限制、完整复制及中文失败反馈。");
