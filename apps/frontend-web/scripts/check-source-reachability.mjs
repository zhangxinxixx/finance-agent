import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

// This check reports candidates for review; it never deletes source files.
const root = fileURLToPath(new URL("../", import.meta.url));
const src = path.join(root, "src");
const config = ts.readConfigFile(path.join(root, "tsconfig.json"), ts.sys.readFile);
if (config.error) throw new Error(ts.flattenDiagnosticMessageText(config.error.messageText, "\n"));
const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, root);
if (parsed.errors.length) throw new Error(ts.formatDiagnosticsWithColorAndContext(parsed.errors, {
  getCanonicalFileName: (file) => file, getCurrentDirectory: () => root, getNewLine: () => "\n",
}));
const files = parsed.fileNames.filter((file) => file.startsWith(src + path.sep) && /\.tsx?$/.test(file));
const retained = JSON.parse(fs.readFileSync(new URL("source-reachability-retained.json", import.meta.url), "utf8"));
const edges = new Map();
const unresolved = [];
const dynamic = [];
const relative = (file) => path.relative(src, file).split(path.sep).join("/");
for (const file of files) {
  const imports = [];
  edges.set(relative(file), imports);
  const source = ts.createSourceFile(file, fs.readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true);
  function resolve(specifier) {
    const result = ts.resolveModuleName(specifier, file, parsed.options, ts.sys).resolvedModule;
    if (result) {
      if (result.resolvedFileName.startsWith(src + path.sep)) imports.push(relative(result.resolvedFileName));
      return;
    }
    const local = specifier.startsWith(".") || Object.keys(parsed.options.paths ?? {}).some((pattern) =>
      specifier.startsWith(pattern.split("*")[0]));
    if (!local) return;
    // TS does not resolve CSS/assets. Resolve those with the same tsconfig aliases.
    let candidates = [path.resolve(path.dirname(file), specifier)];
    for (const [pattern, targets] of Object.entries(parsed.options.paths ?? {})) {
      const [prefix, suffix = ""] = pattern.split("*");
      if (pattern.includes("*") ? specifier.startsWith(prefix) && specifier.endsWith(suffix) : specifier === pattern) {
        const match = pattern.includes("*") ? specifier.slice(prefix.length, suffix ? -suffix.length : undefined) : "";
        candidates = targets.map((target) => path.resolve(parsed.options.baseUrl ?? root, target.replace("*", match)));
        break;
      }
    }
    if (!candidates.some((candidate) => fs.existsSync(candidate) && fs.statSync(candidate).isFile())) {
      unresolved.push(`${relative(file)}: ${specifier}`);
    }
  }
  function visit(node) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteralLike(node.moduleSpecifier)) {
      resolve(node.moduleSpecifier.text);
    }
    if (ts.isCallExpression(node)) {
      if (node.expression.kind === ts.SyntaxKind.ImportKeyword || (ts.isIdentifier(node.expression) && node.expression.text === "require")) {
        if (node.arguments.length === 1 && ts.isStringLiteralLike(node.arguments[0])) resolve(node.arguments[0].text);
        else dynamic.push(`${relative(file)}: ${node.getText(source)}`);
      }
      if (ts.isPropertyAccessExpression(node.expression) && /^import\.meta\.glob/.test(node.expression.getText(source))) {
        dynamic.push(`${relative(file)}: glob requires explicit graph review`);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
}
const reachable = new Set();
function walk(file) {
  if (reachable.has(file)) return;
  reachable.add(file);
  for (const dependency of edges.get(file) ?? []) walk(dependency);
}
walk("main.tsx");
// The external chart and retained history views must be live consumers, not allowlisted dead code.
for (const file of ["components/charts/TradingViewChart.tsx", "components/market-monitor/HistoryObservationPanel.tsx", "components/market-monitor/MultiLineChartLegend.tsx"]) {
  if (!reachable.has(file)) throw new Error(`Required chart consumer is unreachable: ${file}`);
}
for (const file of ["components/charts/KLineChart.tsx", "hooks/useJin10Kline.ts", "components/market-monitor/klineCoverageModel.ts"]) {
  if (edges.has(file)) throw new Error(`Obsolete local chart source remains: ${file}`);
}
const independent = (file) => /(?:\.test\.tsx?$|\.d\.ts$)/.test(file);
const unreachable = [...edges.keys()].filter((file) => !reachable.has(file) && !independent(file));
const unexpected = unreachable.filter((file) => !retained[file]);
const invalidRetentions = Object.entries(retained).filter(([file, reason]) =>
  !edges.has(file) || reachable.has(file) || independent(file) || typeof reason !== "string" || !reason.trim()).map(([file]) => file);
console.log(`Source reachability: ${files.length} files, ${reachable.size} reachable, ${unreachable.length} unreachable, ${unreachable.filter((file) => retained[file]).length} explicitly retained; test/declaration sources preserved.`);
for (const [label, values] of Object.entries({ unresolved, dynamic, unexpected, invalidRetentions })) {
  if (values.length) console.error(`${label}:\n${values.join("\n")}`);
}
if (unresolved.length || dynamic.length || unexpected.length || invalidRetentions.length) process.exitCode = 1;
