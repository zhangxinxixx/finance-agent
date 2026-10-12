import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import ts from "typescript";

const root = path.resolve(new URL("../src", import.meta.url).pathname);
const sourcePath = path.join(root, "components/cme-options/cmeOptionsFormat.ts");
const source = fs.readFileSync(sourcePath, "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText;
const module = { exports: {} };
vm.runInNewContext(output, {
  module,
  exports: module.exports,
  require(specifier) {
    if (specifier === "@/lib/researchReading") return { readableWarning: (value) => value };
    throw new Error(`Unexpected import: ${specifier}`);
  },
}, { filename: sourcePath });

const { formatCMEExpiryLabel } = module.exports;
assert.equal(formatCMEExpiryLabel("NOV26"), "2026年11月合约（NOV26）");
assert.equal(formatCMEExpiryLabel("DEC26"), "2026年12月合约（DEC26）");
assert.equal(formatCMEExpiryLabel(null), "到期月未提供");
assert.match(formatCMEExpiryLabel("contract_expiry"), /^到期范围待确认（contract_expiry）$/);

const page = fs.readFileSync(path.join(root, "../src/pages/CMEOptionsPage.tsx"), "utf8");
assert.match(page, /formatCMEExpiryLabel\(ex\)/);
assert.match(page, /EvidenceRecordActions/);
assert.match(page, /来源已匹配/);
assert.match(page, /后端未单独提供判断主快照身份/);
assert.match(page, /当前仅核对来源记录，不能证明完整版本一致/);
assert.doesNotMatch(page, /结构快照 ID：\{snapshot\?\.snapshot_id/);
assert.doesNotMatch(page, /决策快照 ID：\{decisionRevisionIdentity/);

console.log("CME human-readable expiry and snapshot identity contract OK");
