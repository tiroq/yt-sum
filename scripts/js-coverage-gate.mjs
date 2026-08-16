import { spawnSync } from "node:child_process";

const result = spawnSync(
  process.execPath,
  ["--test", "--experimental-test-coverage", "tests/*.test.mjs"],
  { encoding: "utf8", shell: true },
);

const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;
process.stdout.write(output);

if (result.status !== 0) {
  process.exit(result.status ?? 1);
}

const rows = [...output.matchAll(/^# ([^|\n]+)\|\s+([\d.]+)\s+\|\s+([\d.]+)\s+\|\s+([\d.]+)\s+\|/gm)]
  .map((match) => ({
    file: match[1].trim(),
    line: Number(match[2]),
    branch: Number(match[3]),
    funcs: Number(match[4]),
  }))
  .filter(({ file }) => (
    !file.startsWith("tests/")
    && !file.startsWith("dist/")
    && !file.includes("/dist/")
    && !file.startsWith("node_modules/")
    && file !== "all files"
  ));

if (!rows.length) {
  console.error("Could not find any source coverage rows in the Node test coverage output.");
  process.exit(1);
}

const failures = rows.filter(({ line, branch, funcs }) => line !== 100 || branch !== 100 || funcs !== 100);
if (failures.length) {
  console.error("Expected 100% JS source coverage. Failing files:");
  for (const { file, line, branch, funcs } of failures) {
    console.error(`- ${file}: line=${line}, branch=${branch}, funcs=${funcs}`);
  }
  process.exit(1);
}
