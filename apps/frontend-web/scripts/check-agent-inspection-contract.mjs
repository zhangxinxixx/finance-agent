import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

function source(relativePath) {
  return readFileSync(join(__dirname, "..", relativePath), "utf8");
}

const types = source("src/types/agent-task.ts");
const panel = source("src/components/agent-tasks/AgentInspectionPanel.tsx");

for (const field of ["prompt_id", "checksum", "source_file"]) {
  assert.match(types, new RegExp(`${field}\\??:`), `AgentInspectionPrompt missing ${field}`);
}

for (const field of ["prompt_id", "prompt_version", "prompt_checksum", "prompt_source_file"]) {
  assert.match(types, new RegExp(`${field}\\??:`), `AgentInspection output metadata missing ${field}`);
}

assert.match(panel, /prompt_id/, "AgentInspectionPanel must render prompt_id");
assert.match(panel, /prompt_checksum/, "AgentInspectionPanel must render prompt_checksum");
assert.match(panel, /source_file/, "AgentInspectionPanel must render prompt source_file");

console.log("Agent inspection prompt metadata contract OK");
