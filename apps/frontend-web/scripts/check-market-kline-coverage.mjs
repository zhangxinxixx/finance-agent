import { rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const outDir = join(tmpdir(), "finance-agent-market-kline-coverage-test");
rmSync(outDir, { recursive: true, force: true });

const compile = spawnSync(
  "node",
  [
    "node_modules/typescript/bin/tsc",
    "--target",
    "ES2020",
    "--module",
    "NodeNext",
    "--moduleResolution",
    "NodeNext",
    "--rootDir",
    "src",
    "--outDir",
    outDir,
    "--noEmit",
    "false",
    "--skipLibCheck",
    "src/components/market-monitor/klineCoverageModel.ts",
    "src/components/market-monitor/klineCoverageModel.test.ts",
  ],
  { stdio: "inherit" },
);

if (compile.status !== 0) {
  process.exit(compile.status ?? 1);
}

const run = spawnSync(
  "node",
  [join(outDir, "components/market-monitor/klineCoverageModel.test.js")],
  { stdio: "inherit" },
);

process.exit(run.status ?? 1);
