// Builds image-gen-for-claude-<version>.mcpb, the Claude Desktop extension.
// dist/index.js is a single bundled file with every dependency inside, so the
// extension needs no node_modules. Run with: npm run pack:mcpb

import { execFileSync } from "node:child_process";
import { cpSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const { name, version } = JSON.parse(readFileSync(path.join(root, "manifest.json"), "utf8"));
const stage = path.join(root, "build", "mcpb");
const output = path.join(root, "build", `${name}-${version}.mcpb`);

rmSync(stage, { recursive: true, force: true });
mkdirSync(path.join(stage, "dist"), { recursive: true });
for (const file of ["manifest.json", "README.md", "LICENSE", "dist/index.js", "dist/THIRD_PARTY_LICENSES.txt"]) {
  cpSync(path.join(root, file), path.join(stage, file));
}

const mcpb = path.join(root, "node_modules", "@anthropic-ai", "mcpb", "dist", "cli", "cli.js");
execFileSync(process.execPath, [mcpb, "validate", path.join(stage, "manifest.json")], { stdio: "inherit" });
execFileSync(process.execPath, [mcpb, "pack", stage, output], { stdio: "inherit" });
console.log(`\nBuilt ${path.relative(root, output)}`);
