import { rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const outDir = join(tmpdir(), "finance-agent-markdown-viewer-test");
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
    "--jsx",
    "react-jsx",
    "src/components/reports/markdownViewerModel.ts",
    "src/components/reports/markdownViewerModel.test.ts",
  ],
  { stdio: "inherit" },
);

if (compile.status !== 0) {
  process.exit(compile.status ?? 1);
}

const run = spawnSync(
  "node",
  [join(outDir, "components/reports/markdownViewerModel.test.js")],
  { stdio: "inherit" },
);

process.exit(run.status ?? 1);
