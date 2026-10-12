import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

function source(relativePath) {
  return readFileSync(join(__dirname, "..", relativePath), "utf8");
}

const panels = source("src/components/agent-tasks/AgentTaskPanels.tsx");
const adapter = source("src/adapters/agentTasks.ts");
const removedPanelPath = join(__dirname, "..", "src/components/agent-tasks/AgentInspectionPanel.tsx");

assert.equal(existsSync(removedPanelPath), false, "raw agent inspection panel must not remain reachable");
assert.doesNotMatch(panels, /AgentTaskIOPanels|TracePanel|LogPanel|EventTimelinePanel/, "task detail must stay on ADS summaries and reviews");
assert.doesNotMatch(adapter, /\/artifacts`|\/logs`|\/events`|\/steps`/, "task adapter must not request lower-layer detail endpoints");
assert.match(adapter, /\?view=ads/, "task detail requests must explicitly select the ADS view");

console.log("Agent task ADS summary boundary contract OK");
