// Bundles src/index.ts and every dependency into one file, dist/index.js, so `npx`
// starts fast (nothing to install) and the .mcpb needs no node_modules.
// Also writes dist/THIRD_PARTY_LICENSES.txt for the bundled packages, as their licenses require.

import { build } from "esbuild";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

const result = await build({
  entryPoints: [path.join(root, "src", "index.ts")],
  outfile: path.join(root, "dist", "index.js"),
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node20",
  minifySyntax: true,
  minifyWhitespace: true,
  legalComments: "none", // the full license texts go in THIRD_PARTY_LICENSES.txt
  metafile: true,
  loader: { ".html": "text" }, // the MCP Apps view, shared with the Python version
  banner: {
    js: "#!/usr/bin/env node\nimport { createRequire } from 'node:module'; const require = createRequire(import.meta.url);",
  },
});

// Every package that ended up in the bundle, from the paths esbuild read
const packages = new Map();
for (const input of Object.keys(result.metafile.inputs)) {
  const match = input.match(/node_modules\/((?:@[^/]+\/)?[^/]+)\//g);
  if (!match) continue;
  const dir = path.join(root, input.slice(0, input.lastIndexOf(match.at(-1)) + match.at(-1).length));
  if (!packages.has(dir)) packages.set(dir, JSON.parse(readFileSync(path.join(dir, "package.json"), "utf8")));
}

const sections = [...packages]
  .sort(([, a], [, b]) => a.name.localeCompare(b.name))
  .map(([dir, pkg]) => {
    const file = readdirSync(dir).find((f) => /^(licen[cs]e|copying)(\.|$)/i.test(f));
    const text = file && existsSync(path.join(dir, file)) ? readFileSync(path.join(dir, file), "utf8").trim() : `License: ${pkg.license}`;
    return `${pkg.name}@${pkg.version} (${pkg.license})\n${"-".repeat(60)}\n${text}`;
  });

writeFileSync(
  path.join(root, "dist", "THIRD_PARTY_LICENSES.txt"),
  "dist/index.js includes the following open-source packages.\n\n" + sections.join("\n\n\n") + "\n"
);
console.log(`dist/index.js: ${(result.metafile.outputs["dist/index.js"]?.bytes ?? 0) / 1000 | 0} kB, ${packages.size} bundled packages`);
for (const [, pkg] of packages) console.log(`  ${pkg.name}@${pkg.version} ${pkg.license}`);
