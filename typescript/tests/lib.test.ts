// Tests for paths and API key loading. GitHub Actions runs these on Windows, macOS and Linux.
// Run `npm run build` first: the last test starts the built server (dist/index.js).

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import path from "node:path";
import { createInterface } from "node:readline";
import { afterEach, beforeEach, describe, test } from "node:test";
import { fileURLToPath } from "node:url";
import jpeg from "jpeg-js";
import { PNG } from "pngjs";
import * as lib from "../src/lib.ts";

const isWindows = process.platform === "win32";
const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const savedEnv = { ...process.env };
let tmp: string;
let home: string;

function fakeHome() {
  home = path.join(tmp, "home");
  mkdirSync(home, { recursive: true });
  process.env.HOME = home; // macOS, Linux
  process.env.USERPROFILE = home; // Windows
  process.env.APPDATA = path.join(tmp, "appdata");
  process.env.XDG_CONFIG_HOME = path.join(tmp, "xdgconfig");
}

beforeEach(() => {
  tmp = mkdtempSync(path.join(tmpdir(), "oimcp-"));
  for (const name of ["OPENAI_API_KEY", "OPENAI_IMAGE_OUTPUT_DIR", "OPENAI_IMAGE_MODEL", "XDG_PICTURES_DIR"]) {
    delete process.env[name];
  }
});

afterEach(() => {
  for (const key of Object.keys(process.env)) if (!(key in savedEnv)) delete process.env[key];
  Object.assign(process.env, savedEnv);
});

function write(file: string, data: string | Buffer) {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, data);
}

// ---------- the OS's real folders (no fakes) ----------

describe("real OS folders", () => {
  test("key file is in the OS config folder", () => {
    delete process.env.XDG_CONFIG_HOME;
    const [first] = lib.keyFiles();
    let expected: string;
    if (isWindows) expected = path.join(process.env.APPDATA!, "openai", "api_key");
    else if (process.platform === "darwin")
      expected = path.join(homedir(), "Library", "Application Support", "openai", "api_key");
    else expected = path.join(homedir(), ".config", "openai", "api_key");
    assert.equal(first, expected);
    assert.equal(lib.keyFiles().at(-1), path.join(homedir(), ".config", "openai", "api_key"));
  });

  test("default output folder is the Pictures folder", () => {
    const pictures = lib.defaultOutputDir();
    assert.ok(path.isAbsolute(pictures), pictures);
    if (process.platform === "darwin") assert.equal(pictures, path.join(homedir(), "Pictures"));
    if (isWindows) assert.match(pictures, /Pictures|Afbeeldingen|Bilder|Images|Immagini|Imágenes/i);
  });
});

// ---------- API key ----------

describe("API key", () => {
  beforeEach(fakeHome);

  test("env var wins", () => {
    process.env.OPENAI_API_KEY = "  sk-env \n";
    write(path.join(home, ".config", "openai", "api_key"), "sk-file");
    assert.equal(lib.findApiKey(), "sk-env");
  });

  test("unfilled Claude Desktop placeholder counts as unset", () => {
    process.env.OPENAI_API_KEY = "${user_config.openai_api_key}";
    write(lib.keyFiles()[0], "sk-file");
    assert.equal(lib.findApiKey(), "sk-file");
  });

  test("from the OS config folder", () => {
    write(lib.keyFiles()[0], "sk-config\n");
    assert.equal(lib.findApiKey(), "sk-config");
  });

  test("from ~/.config on every OS", () => {
    write(path.join(home, ".config", "openai", "api_key"), "sk-dotconfig");
    assert.equal(lib.findApiKey(), "sk-dotconfig");
  });

  const encodings: [string, Buffer][] = [
    ["UTF-16 LE with BOM (Windows PowerShell 5)", Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from("sk-utf16\r\n", "utf16le")])],
    ["UTF-16 BE with BOM", Buffer.concat([Buffer.from([0xfe, 0xff]), Buffer.from("sk-utf16\r\n", "utf16le").swap16()])],
    ["UTF-8 with BOM (Notepad)", Buffer.from("﻿sk-utf16\r\n", "utf8")],
    ["Windows line ending", Buffer.from("sk-utf16\r\n")],
  ];
  for (const [name, data] of encodings) {
    test(`key file: ${name}`, () => {
      write(lib.keyFiles()[0], data);
      assert.equal(lib.findApiKey(), "sk-utf16");
    });
  }

  test("missing key lists where to put it", () => {
    assert.throws(lib.makeClient, (e: Error) => lib.keyFiles().every((p) => e.message.includes(p)));
  });
});

// ---------- output paths ----------

describe("output paths", () => {
  let out: string;
  beforeEach(() => {
    fakeHome();
    out = path.join(tmp, "out");
    process.env.OPENAI_IMAGE_OUTPUT_DIR = out;
  });

  test("no path uses the default folder", () => {
    const p = lib.outputFile(undefined, "png", "A red logo!");
    assert.equal(path.dirname(p), out);
    assert.match(path.basename(p), /^\d{8}-\d{6}-a-red-logo\.png$/);
  });

  test("absolute path", () => {
    const target = path.join(tmp, "site", "hero.webp");
    assert.equal(lib.outputFile(target, "webp", "x"), target);
  });

  test("relative path goes inside the default folder", () => {
    assert.equal(lib.outputFile("logos/logo.png", "png", "x"), path.join(out, "logos", "logo.png"));
  });

  test("~ is expanded", () => {
    assert.equal(lib.outputFile("~/Desktop/a.png", "png", "x"), path.join(home, "Desktop", "a.png"));
  });

  test("environment variables are expanded", () => {
    process.env.MY_IMAGES = path.join(home, "imgs");
    const vars = isWindows ? ["%MY_IMAGES%", "$MY_IMAGES", "${MY_IMAGES}"] : ["$MY_IMAGES", "${MY_IMAGES}"];
    for (const v of vars) assert.equal(lib.outputFile(`${v}/a.png`, "png", "x"), path.join(home, "imgs", "a.png"));
  });

  test("existing folder gets an auto name", () => {
    const folder = path.join(tmp, "existing");
    mkdirSync(folder);
    const p = lib.outputFile(folder, "png", "cat");
    assert.equal(path.dirname(p), folder);
    assert.match(p, /-cat\.png$/);
  });

  test("trailing separator means a folder", () => {
    const sep = isWindows ? "\\" : "/";
    const p = lib.outputFile(path.join(tmp, "new") + sep, "jpeg", "dog");
    assert.equal(path.dirname(p), path.join(tmp, "new"));
    assert.match(p, /-dog\.jpeg$/);
  });

  test("extension is added", () => {
    assert.equal(lib.outputFile(path.join(tmp, "hero"), "webp", "x"), path.join(tmp, "hero.webp"));
    assert.equal(lib.outputFile(path.join(tmp, "hero.v2"), "png", "x"), path.join(tmp, "hero.v2.png"));
  });

  test("OPENAI_IMAGE_OUTPUT_DIR with ~", () => {
    process.env.OPENAI_IMAGE_OUTPUT_DIR = "~/Generated";
    assert.equal(lib.defaultOutputDir(), path.join(home, "Generated"));
  });

  test("unfilled Claude Desktop placeholder falls back to Pictures", () => {
    process.env.OPENAI_IMAGE_OUTPUT_DIR = "${user_config.output_dir}";
    assert.equal(lib.defaultOutputDir(), lib.picturesDir());
  });

  test("slug matches the Python version", () => {
    assert.equal(lib.slug("  Hello, World!! "), "hello-world");
    assert.equal(lib.slug("!!!"), "image");
    assert.equal(lib.slug("a".repeat(50)), "a".repeat(40));
  });
});

// ---------- full tool call with a fake OpenAI client ----------

describe("generate_image", () => {
  beforeEach(() => {
    fakeHome();
    process.env.OPENAI_IMAGE_OUTPUT_DIR = path.join(tmp, "out");
  });

  /** A solid-color PNG. */
  const makePng = (width: number, height: number, rgba: [number, number, number, number]) => {
    const img = new PNG({ width, height });
    for (let i = 0; i < img.data.length; i += 4) img.data.set(rgba, i);
    return PNG.sync.write(img);
  };
  const decodePreview = (preview: lib.Preview | undefined) => {
    assert.ok(preview);
    assert.equal(preview.mimeType, "image/jpeg");
    return jpeg.decode(Buffer.from(preview.data, "base64"), { useTArray: true });
  };

  const png = makePng(1536, 1024, [200, 30, 30, 255]);
  const fake = (seen: Record<string, unknown>[] = [], image = png) => () => ({
    images: {
      generate: async (params: Record<string, unknown>) => {
        seen.push(params);
        return { data: [{ b64_json: image.toString("base64") }], usage: { total_tokens: 42 } };
      },
    },
  });

  test("saves the full image and returns a small JPEG preview", async () => {
    const [text, isError, preview] = await lib.generateImage({ prompt: "a test image", output_path: "sub/test" }, fake());
    const saved = path.join(tmp, "out", "sub", "test.png");
    assert.equal(isError, false);
    assert.ok(text.startsWith(`Saved: ${saved}`), text);
    assert.match(text, /tokens used: 42/);
    assert.deepEqual(readFileSync(saved), png); // full resolution on disk
    const small = decodePreview(preview);
    assert.deepEqual([small.width, small.height], [1024, 683]);
  });

  test("preview of a transparent image is white where it was transparent", () => {
    const small = decodePreview(lib.makePreview(makePng(1024, 1536, [0, 0, 0, 0]), "png"));
    assert.deepEqual([small.width, small.height], [683, 1024]);
    assert.ok(small.data[0] > 250 && small.data[1] > 250 && small.data[2] > 250);
  });

  test("a JPEG is shrunk to a JPEG preview", () => {
    const big = jpeg.encode({ data: Buffer.alloc(1536 * 1024 * 4, 128), width: 1536, height: 1024 }, 90).data;
    const small = decodePreview(lib.makePreview(Buffer.from(big), "jpeg"));
    assert.deepEqual([small.width, small.height], [1024, 683]);
  });

  test("a small WebP is sent as-is with its own mimeType", () => {
    const webp = Buffer.from("RIFF....WEBPVP8 ", "latin1");
    assert.deepEqual(lib.makePreview(webp, "webp"), { data: webp.toString("base64"), mimeType: "image/webp" });
    assert.equal(lib.makePreview(Buffer.alloc(600 * 1024), "webp"), undefined);
  });

  test("an unreadable image is still saved, just without a preview", async () => {
    const broken = Buffer.from("not an image");
    const [text, isError, preview] = await lib.generateImage({ prompt: "x", output_path: "broken" }, fake([], broken));
    assert.equal(isError, false);
    assert.equal(preview, undefined);
    assert.match(text, /No preview/);
    assert.deepEqual(readFileSync(path.join(tmp, "out", "broken.png")), broken);
  });

  test("transparent switches model and jpeg to png", async () => {
    const seen: Record<string, unknown>[] = [];
    await lib.generateImage({ prompt: "logo", background: "transparent", output_format: "jpeg" }, fake(seen));
    assert.equal(seen[0].model, lib.TRANSPARENT_MODEL);
    assert.equal(seen[0].output_format, "png");
  });

  test("OpenAI errors come back as text", async () => {
    const failing = () => ({ images: { generate: async () => { throw new Error("billing limit reached"); } } });
    const [text, isError] = await lib.generateImage({ prompt: "x" }, failing);
    assert.equal(isError, true);
    assert.match(text, /billing limit reached/);
  });
});

// ---------- FLUX with a fake Black Forest Labs API ----------

describe("FLUX", () => {
  beforeEach(() => {
    fakeHome();
    process.env.OPENAI_IMAGE_OUTPUT_DIR = path.join(tmp, "out");
    delete process.env.OPENAI_API_KEY;
    delete process.env.OPENAI_IMAGE_MODEL;
    process.env.BFL_API_KEY = "bfl-test-key";
  });

  const flat = (width: number, height: number) => {
    const img = new PNG({ width, height });
    img.data.fill(200);
    return PNG.sync.write(img);
  };

  /** A fake BFL API: answers submit, then `pending` polls, then Ready with a download URL. */
  const fakeBfl = (opts: { image?: Buffer; pending?: number; status?: string; submitStatus?: number } = {}) => {
    const calls: { url: string; headers?: Record<string, string>; body?: any }[] = [];
    let polls = 0;
    const res = (status: number, body: unknown, bytes?: Buffer) => ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
      text: async () => JSON.stringify(body),
      arrayBuffer: async () => new Uint8Array(bytes ?? Buffer.alloc(0)).buffer,
    });
    const fetch: lib.Fetch = async (url, init) => {
      calls.push({ url, headers: init?.headers, body: init?.body ? JSON.parse(init.body) : undefined });
      if (init?.method === "POST") {
        return opts.submitStatus ? res(opts.submitStatus, { detail: "nope" }) : res(200, { id: "t1", polling_url: "https://api.eu.bfl.ai/v1/get_result?id=t1", cost: 4.8 });
      }
      if (url.includes("get_result")) {
        polls++;
        if (polls <= (opts.pending ?? 1)) return res(200, { id: "t1", status: polls === 1 ? "Pending" : "Generating" });
        if (opts.status) return res(503, { id: "t1", status: opts.status });
        return res(200, { id: "t1", status: "Ready", result: { sample: "https://delivery.eu.bfl.ai/x.png" } });
      }
      return res(200, null, opts.image ?? flat(64, 64));
    };
    return { fetch, calls, pollMs: 1 };
  };

  test("uses FLUX by default when only a FLUX key is set", () => {
    assert.equal(lib.defaultModel(), "flux-3-image");
    process.env.OPENAI_API_KEY = "sk-x";
    assert.equal(lib.defaultModel(), "gpt-image-2");
  });

  test("submits, polls the given URL, downloads and saves", async () => {
    const bfl = fakeBfl({ pending: 2 });
    const [text, isError, preview] = await lib.generateImage({ prompt: "a cat", size: "1536x1024", output_path: "flux/cat" }, bfl);
    assert.equal(isError, false, text);
    const submit = bfl.calls[0];
    assert.equal(submit.url, "https://api.bfl.ai/v1/flux-3-image");
    assert.equal(submit.headers?.["x-key"], "bfl-test-key");
    assert.deepEqual(submit.body, { prompt: "a cat", width: 1536, height: 1024 }); // flux-3-image takes no output_format
    assert.equal(bfl.calls.filter((c) => c.url.includes("get_result")).length, 3);
    assert.ok(bfl.calls.every((c) => !c.url.includes("get_result") || c.url.startsWith("https://api.eu.bfl.ai")));
    assert.match(text, /FLUX cost: 4.8 credits \(\$0\.05\)/);
    assert.doesNotMatch(text, /quality/);
    assert.equal(lib.sniffFormat(readFileSync(path.join(tmp, "out", "flux", "cat.png"))), "png");
    assert.equal(preview?.mimeType, "image/jpeg");
  });

  test("converts what FLUX returns to the format asked for", async () => {
    const [text] = await lib.generateImage({ prompt: "x", model: "flux-3-image", output_format: "jpeg", output_path: "conv" }, fakeBfl());
    assert.equal(lib.sniffFormat(readFileSync(path.join(tmp, "out", "conv.jpeg"))), "jpeg", text);
  });

  test("FLUX.2 and Klein get output_format", () => {
    assert.equal(lib.fluxBody("flux-2-pro", "x", "1024x1024", "webp").output_format, "webp");
    assert.equal(lib.fluxBody("flux-3-image-klein", "x", "1024x1024", "png").output_format, "png");
    assert.equal(lib.fluxBody("flux-3-image", "x", "1024x1024", "png").output_format, undefined);
  });

  test("moderation, credits and transparency come back as clear errors", async () => {
    let [text, isError] = await lib.generateImage({ prompt: "x", model: "flux-3-image" }, fakeBfl({ status: "Content Moderated" }));
    assert.equal(isError, true);
    assert.match(text, /Content Moderated/);
    [text] = await lib.generateImage({ prompt: "x", model: "flux-3-image" }, fakeBfl({ submitStatus: 402 }));
    assert.match(text, /not enough credits/);
    [text, isError] = await lib.generateImage({ prompt: "x", model: "flux-3-image", background: "transparent" }, fakeBfl());
    assert.equal(isError, true);
    assert.match(text, /transparent/);
    [text] = await lib.generateImage({ prompt: "x", model: "flux-pro-1.1" }, fakeBfl());
    assert.match(text, /isn't supported/);
  });

  test("a missing FLUX key says where to put it", async () => {
    delete process.env.BFL_API_KEY;
    const [text, isError] = await lib.generateImage({ prompt: "x", model: "flux-3-image" }, fakeBfl());
    assert.equal(isError, true);
    assert.match(text, /BFL_API_KEY/);
    for (const file of lib.keyFiles("bfl")) assert.ok(text.includes(file));
  });
});

// ---------- versions stay in sync ----------

test("version matches package.json and manifest.json", () => {
  const pkg = JSON.parse(readFileSync(path.join(root, "package.json"), "utf8"));
  const manifest = JSON.parse(readFileSync(path.join(root, "manifest.json"), "utf8"));
  assert.equal(lib.VERSION, pkg.version);
  assert.equal(lib.VERSION, manifest.version);
});

// ---------- the built server starts and speaks MCP ----------

test("built server lists the tool over stdio", async () => {
  const proc = spawn(process.execPath, [path.join(root, "dist", "index.js")], { stdio: ["pipe", "pipe", "pipe"] });
  const lines = createInterface({ input: proc.stdout })[Symbol.asyncIterator]();
  const send = (m: object) => proc.stdin.write(JSON.stringify(m) + "\n");
  const reply = async (id: number) => {
    const timer = setTimeout(() => proc.kill(), 30_000);
    try {
      for (;;) {
        const { value, done } = await lines.next();
        if (done) throw new Error("server exited before replying");
        const message = JSON.parse(value);
        if (message.id === id) return message;
      }
    } finally {
      clearTimeout(timer);
    }
  };
  try {
    send({ jsonrpc: "2.0", id: 1, method: "initialize", params: {
      protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "0" } } });
    const init = await reply(1);
    assert.equal(init.result.serverInfo.version, lib.VERSION);
    send({ jsonrpc: "2.0", method: "notifications/initialized" });
    send({ jsonrpc: "2.0", id: 2, method: "tools/list" });
    const { result } = await reply(2);
    assert.deepEqual(result.tools.map((t: { name: string }) => t.name), ["generate_image"]);
    const props = Object.keys(result.tools[0].inputSchema.properties);
    assert.deepEqual(props, ["prompt", "quality", "size", "background", "output_format", "output_path", "model"]);

    // MCP Apps: the tool points at the image view, and the server serves it
    const uri = result.tools[0]._meta?.ui?.resourceUri;
    assert.equal(uri, "ui://openai-image/view.html");
    send({ jsonrpc: "2.0", id: 3, method: "resources/read", params: { uri } });
    const [view] = (await reply(3)).result.contents;
    assert.equal(view.mimeType, "text/html;profile=mcp-app");
    assert.match(view.text, /ui\/notifications\/tool-result/);
  } finally {
    proc.stdin.end();
    proc.kill();
  }
});
