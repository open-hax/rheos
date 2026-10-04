// SPDX-License-Identifier: GPL-3.0-or-later
// Exercise the caller's actual inline guards; no runtime or board implementation.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const workflow = readFileSync(new URL("../workflows/eta-mu-evidence-review.yml", import.meta.url), "utf8");
const outputBlock = workflow.split("# BEGIN COMPLETED_OUTPUTS\n")[1]?.split("# END COMPLETED_OUTPUTS")[0];
assert.ok(outputBlock, "caller must contain its completed-output guard");
const guard = outputBlock.split("\n").map(line => line.slice(8)).join("\n")
  .split("\nJS\n")[0].split("\n").slice(1).join("\n");
assert.match(guard, /readFileSync/);
test("entire upstream evidence snippet is valid Bash", () => {
  const script = workflow.split("      evidence_gates_script: |\n")[1]
    .split("\n").map(line => line.slice(8)).join("\n");
  const result = spawnSync("/bin/bash", ["--noprofile", "--norc", "-n"], { input: script, encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
});
const summary = (tests = 153, assertions = 790, failures = 0, errors = 0) =>
  `Ran ${tests} tests containing ${assertions} assertions.\n${failures} failures, ${errors} errors.\n`;
const builds = (warnings = 0) => ["server", "cli", "github-sync", "app"]
  .map(target => `[:${target}] Build completed. (42 files, 1 compiled, ${warnings} warnings, 1.0s)\n`).join("");
function execute(testLog, buildLog = builds()) {
  const dir = mkdtempSync(join(tmpdir(), "rheos-caller-fixture-"));
  try {
    writeFileSync(join(dir, "test.log"), testLog);
    writeFileSync(join(dir, "build.log"), buildLog);
    return spawnSync(process.execPath, ["--input-type=module", "-", join(dir, "test.log"), join(dir, "build.log")],
      { input: guard, encoding: "utf8" });
  } finally { rmSync(dir, { recursive: true, force: true }); }
}
test("accept actual nonempty suite and all four completed build targets", () => {
  assert.equal(execute(summary() + summary()).status, 0);
});
for (const [name, testLog, buildLog] of [
  ["zero tests", summary(0, 0)],
  ["zero assertions", summary(1, 0)],
  ["no completed tests", "Compilation succeeded\n"],
  ["standalone zero failure line", "0 failures, 0 errors.\n"],
  ["failed autorun followed by passing direct artifact", summary(153, 790, 1) + summary()],
  ["errors followed by a passing summary", summary(153, 790, 0, 1) + summary()],
  ["inconsistent duplicate suite counts", summary() + summary(1, 1)],
  ["unpaired suite summary", summary() + "Ran 2 tests containing 3 assertions.\n"],
  ["test compiler warning", summary() + "[:test] Build completed. (42 files, 1 compiled, 1 warnings, 1.0s)\n"],
  ["missing build target", summary(), builds().replace(/^\[:app\].*\n/m, "")],
  ["empty build output", summary(), ""],
  ["build compiler warning", summary(), builds(1)],
]) {
  test(`reject ${name}`, () => assert.notEqual(execute(testLog, buildLog).status, 0));
}
test("actual required-tool gate rejects missing clojure-lsp visibly", () => {
  const block = workflow.split("# BEGIN REQUIRED_TOOLS\n")[1]?.split("# END REQUIRED_TOOLS")[0];
  assert.ok(block);
  const dir = mkdtempSync(join(tmpdir(), "rheos-tools-fixture-"));
  try {
    for (const tool of ["node", "pnpm", "java", "clojure", "bb", "clj-kondo", "git", "curl", "unzip"]) {
      symlinkSync("/usr/bin/true", join(dir, tool));
    }
    const result = spawnSync("/bin/bash", ["--noprofile", "--norc", "-e", "-o", "pipefail", "-c", block],
      { env: { PATH: dir }, encoding: "utf8" });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Missing required tool: clojure-lsp/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
