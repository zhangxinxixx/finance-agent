import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const nodeModules = process.env.NODE_PATH || join(root, "node_modules");
const require = createRequire(join(nodeModules, "package.json"));
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const source = readFileSync(join(root, "src/components/shared/ChartReadingGuide.tsx"), "utf8");
const compiled = ts.transpileModule(source, {
  fileName: "ChartReadingGuide.tsx",
  reportDiagnostics: true,
  compilerOptions: {
    jsx: ts.JsxEmit.ReactJSX,
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
  },
});
assert.deepEqual(compiled.diagnostics, [], "component must transpile without diagnostics");

const module = { exports: {} };
vm.runInNewContext(compiled.outputText, { exports: module.exports, module, require }, {
  filename: "ChartReadingGuide.js",
});
const { ChartReadingGuide } = module.exports;
assert.equal(typeof ChartReadingGuide, "function", "named component export must exist");

const render = (props) => renderToStaticMarkup(React.createElement(ChartReadingGuide, props));
const labels = ["看什么", "相对什么", "如何理解", "限制"];
const missing = render({ question: "价格变化", limits: ["限制一", "限制二", "限制三", "第四条限制"] });
assert.match(missing, /<section\b[^>]*aria-label="图表阅读说明"/);
assert.equal((missing.match(/<dl\b/g) ?? []).length, 1);
assert.equal((missing.match(/<dt\b/g) ?? []).length, 4, "all four terms must remain visible");
assert.equal((missing.match(/<dd\b/g) ?? []).length, 4, "all four descriptions must remain visible");
for (const label of labels) assert.ok(missing.includes(`>${label}</dt>`), `${label} must be visible`);
assert.ok(missing.includes("比较基准未提供"));
assert.ok(missing.includes("后端未提供影响解释，本图仅展示观测。"));
assert.equal((missing.match(/<li\b/g) ?? []).length, 4, "every limit must render as a list item");
assert.ok(missing.includes("<li>第四条限制</li>"), "fourth limit must be visible without interaction");
assert.doesNotMatch(missing, /<details\b|\shidden\b|>0<|>0\.0</);

const complete = render({
  question: "观测问题 A",
  reference: "对照基准 B",
  interpretation: "后端解释 C",
  limits: ["边界 D", "边界 E"],
  className: "custom-guide",
});
for (const value of ["观测问题 A", "对照基准 B", "后端解释 C", "边界 D", "边界 E", "custom-guide"]) {
  assert.ok(complete.includes(value), `${value} must be preserved`);
}
assert.equal((complete.match(/<li\b/g) ?? []).length, 2);
assert.ok(!complete.includes("比较基准未提供"));
assert.ok(!complete.includes("后端未提供影响解释"));

const nullish = render({ question: "观测问题", reference: null, interpretation: null, limits: [] });
assert.ok(nullish.includes("比较基准未提供"));
assert.ok(nullish.includes("后端未提供影响解释，本图仅展示观测。"));
assert.ok(nullish.includes("限制未提供"));
assert.doesNotMatch(nullish, />0<|>0\.0</);

console.log("ChartReadingGuide rendered component checks OK");
