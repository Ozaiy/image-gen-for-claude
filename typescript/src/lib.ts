/**
 * Paths, API key loading and the generate_image tool. Same behavior as the Python
 * version in ../src/openai_image_mcp/server.py. Works on Windows, macOS and Linux.
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import OpenAI from "openai";

export const VERSION = "0.2.0";
export const TRANSPARENT_MODEL = "gpt-image-1.5"; // gpt-image-2 can't do transparent backgrounds
const IMAGE_SUFFIXES = new Set([".png", ".jpg", ".jpeg", ".webp"]);
const isWindows = process.platform === "win32";

export type Quality = "low" | "medium" | "high";
export type Size = "1024x1024" | "1536x1024" | "1024x1536";
export type Background = "auto" | "opaque" | "transparent";
export type Format = "png" | "jpeg" | "webp";

/**
 * Read a setting from the environment. Empty counts as unset, and so does an
 * unfilled Claude Desktop placeholder like "${user_config.output_dir}".
 */
export function setting(name: string): string | undefined {
  const value = process.env[name]?.trim();
  if (!value || /^\$\{user_config\.[^}]*\}$/.test(value)) return undefined;
  return value;
}

/** Expand ~ and environment variables ($HOME, ${HOME}, and %USERPROFILE% on Windows). */
export function expand(p: string): string {
  const env = (name: string, original: string) => process.env[name] ?? original;
  let out = p.trim().replace(/\$\{(\w+)\}|\$(\w+)/g, (m, a, b) => env(a ?? b, m));
  if (isWindows) out = out.replace(/%(\w+)%/g, (m, name) => env(name, m));
  if (out === "~" || out.startsWith("~/") || out.startsWith("~\\")) out = homedir() + out.slice(1);
  return path.normalize(out);
}

// ---------- folders ----------

/** The OS's usual folder for app settings. */
export function configDir(): string {
  if (isWindows) return process.env.APPDATA || path.join(homedir(), "AppData", "Roaming");
  if (process.platform === "darwin") return path.join(homedir(), "Library", "Application Support");
  const xdg = process.env.XDG_CONFIG_HOME;
  return xdg && path.isAbsolute(xdg) ? xdg : path.join(homedir(), ".config");
}

/** Files the API key is read from, in order. The first is in the OS's usual config folder. */
export function keyFiles(): string[] {
  const paths = [
    path.join(configDir(), "openai", "api_key"),
    // Also checked everywhere, because many macOS and Windows users keep CLI config here
    path.join(homedir(), ".config", "openai", "api_key"),
  ];
  return [...new Set(paths)];
}

/** Windows: the Pictures folder from the registry, so a OneDrive-moved folder is found. */
function windowsPictures(): string | undefined {
  const keys = [
    "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\User Shell Folders",
    "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Shell Folders",
  ];
  for (const key of keys) {
    try {
      const out = execFileSync("reg", ["query", key, "/v", "My Pictures"], {
        encoding: "utf8",
        timeout: 5000,
        windowsHide: true,
        stdio: ["ignore", "pipe", "ignore"],
      });
      const match = out.match(/My Pictures\s+REG_(?:EXPAND_)?SZ\s+(.+)/);
      if (match) return expand(match[1].trim());
    } catch {
      // reg.exe missing or the value isn't set: try the next one
    }
  }
  return undefined;
}

/** Linux: XDG_PICTURES_DIR, which may be translated (e.g. ~/Afbeeldingen). */
function xdgPictures(): string | undefined {
  const fromEnv = process.env.XDG_PICTURES_DIR;
  if (fromEnv && path.isAbsolute(expand(fromEnv))) return expand(fromEnv);
  try {
    const file = readFileSync(path.join(configDir(), "user-dirs.dirs"), "utf8");
    const match = file.match(/^\s*XDG_PICTURES_DIR\s*=\s*"([^"]*)"/m);
    if (match) {
      const dir = match[1].replace(/^\$HOME/, homedir());
      if (path.isAbsolute(dir)) return path.normalize(dir);
    }
  } catch {
    // no user-dirs.dirs
  }
  return undefined;
}

export function picturesDir(): string {
  // Windows: the real Pictures folder, also when OneDrive moved it. macOS: ~/Pictures
  const found = isWindows ? windowsPictures() : process.platform === "darwin" ? undefined : xdgPictures();
  return found ?? path.join(homedir(), "Pictures");
}

export function defaultOutputDir(): string {
  const custom = setting("OPENAI_IMAGE_OUTPUT_DIR");
  return custom ? expand(custom) : picturesDir();
}

// ---------- API key ----------

/**
 * Read a key file written by any editor or shell. Windows PowerShell 5
 * (`"sk-..." > api_key`) writes UTF-16 with a byte order mark, and Notepad may
 * add a UTF-8 one, so handle both, plus trailing newlines.
 */
export function readKeyFile(file: string): string {
  const raw = readFileSync(file);
  let text: string;
  if (raw[0] === 0xff && raw[1] === 0xfe) text = raw.subarray(2).toString("utf16le");
  else if (raw[0] === 0xfe && raw[1] === 0xff) text = Buffer.from(raw.subarray(2)).swap16().toString("utf16le");
  else text = raw.toString("utf8").replace(/^\uFEFF/, "");
  return text.trim();
}

export function findApiKey(): string | undefined {
  const fromEnv = setting("OPENAI_API_KEY");
  if (fromEnv) return fromEnv;
  for (const file of keyFiles()) {
    try {
      if (statSync(file).isFile()) {
        const key = readKeyFile(file);
        if (key) return key;
      }
    } catch {
      // not there
    }
  }
  return undefined;
}

export function makeClient(): OpenAI {
  const key = findApiKey();
  if (!key) {
    const places = keyFiles().map((p) => `  ${p}`).join("\n");
    throw new Error(
      "No OpenAI API key. Set OPENAI_API_KEY, or save the key in a file named " +
        `api_key in one of these places:\n${places}`
    );
  }
  return new OpenAI({ apiKey: key });
}

// ---------- output paths ----------

export function slug(text: string): string {
  const s = text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return s.slice(0, 40) || "image";
}

function stamp(d = new Date()): string {
  const two = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}${two(d.getMonth() + 1)}${two(d.getDate())}-` +
    `${two(d.getHours())}${two(d.getMinutes())}${two(d.getSeconds())}`
  );
}

/**
 * Work out where to save the image.
 * - nothing given: <default folder>/<time>-<prompt>.<format>
 * - a folder (existing, or ending in / or \): an auto-named file inside it
 * - a relative path: inside the default folder, because the server's working
 *   directory is unpredictable (on Windows it can be C:\Windows\System32)
 * - no image extension: the format's extension is added
 */
export function outputFile(outputPath: string | undefined, format: Format, prompt: string): string {
  const autoName = `${stamp()}-${slug(prompt)}.${format}`;
  if (!outputPath || !outputPath.trim()) return path.join(defaultOutputDir(), autoName);

  let p = expand(outputPath);
  if (!path.isAbsolute(p)) p = path.join(defaultOutputDir(), p);
  const isDir = existsSync(p) && statSync(p).isDirectory();
  if (isDir || /[\\/]$/.test(outputPath.trim())) return path.join(p, autoName);
  if (!IMAGE_SUFFIXES.has(path.extname(p).toLowerCase())) p = `${p}.${format}`;
  return p;
}

// ---------- the tool ----------

export const TOOL_DESCRIPTION = `Generate an image with OpenAI and save it to disk. Returns the saved file path.

QUALITY - choose carefully, higher quality costs much more:
  - "low"    (default) drafts, previews, trying out ideas, placeholders.
  - "medium" decent images for normal use when low looks too rough.
  - "high"   ONLY for final assets the user explicitly wants in high quality,
             or after a low-quality draft has been approved. Never use
             "high" for experiments or multiple variations.

size: 1024x1024 square, 1536x1024 landscape (hero banners), 1024x1536 portrait.
background: "transparent" for logos/icons/stickers (needs png or webp).
output_path: where to save, ideally an absolute path inside the user's project,
             e.g. "/Users/me/site/images/hero.png" or "C:\\Users\\me\\site\\hero.png".
             ~ and environment variables are expanded. A folder gets an
             auto-named file; a relative path is saved inside the default folder.
             If omitted, saves to the user's Pictures folder.
model: override the default model (normally leave empty).`;

export interface GenerateArgs {
  prompt: string;
  quality?: Quality;
  size?: Size;
  background?: Background;
  output_format?: Format;
  output_path?: string;
  model?: string;
}

/** Just the part of the OpenAI client this server uses, so tests can pass a fake. */
export interface ImageClient {
  images: {
    generate(params: Record<string, unknown>): Promise<{
      data?: { b64_json?: string | null }[] | null;
      usage?: { total_tokens?: number | null } | null;
    }>;
  };
}

let client: ImageClient | undefined;

/** Returns [message, isError]. Errors are passed back as text so the model can explain them. */
export async function generateImage(
  args: GenerateArgs,
  getClient: () => ImageClient = () => (client ??= makeClient() as unknown as ImageClient)
): Promise<[string, boolean]> {
  const quality = args.quality ?? "low";
  const size = args.size ?? "1024x1024";
  const background = args.background ?? "auto";
  let format: Format = args.output_format ?? "png";
  let model = args.model?.trim() || setting("OPENAI_IMAGE_MODEL") || "gpt-image-2";
  if (background === "transparent") {
    if (format === "jpeg") format = "png";
    if (model === "gpt-image-2") model = TRANSPARENT_MODEL;
  }

  let result;
  try {
    result = await getClient().images.generate({
      model,
      prompt: args.prompt,
      quality,
      size,
      background,
      output_format: format,
      n: 1,
    });
  } catch (e) {
    const err = e as Error;
    return [`ERROR (${err?.name ?? "Error"}): ${err?.message ?? String(e)}`, true];
  }

  const b64 = result.data?.[0]?.b64_json;
  if (!b64) return ["ERROR: OpenAI returned no image data", true];

  const file = outputFile(args.output_path, format, args.prompt);
  try {
    mkdirSync(path.dirname(file), { recursive: true });
    writeFileSync(file, Buffer.from(b64, "base64"));
  } catch (e) {
    // e.g. no permission, or a name Windows doesn't allow
    return [`ERROR: the image was generated but could not be saved to ${file}: ${(e as Error).message}`, true];
  }

  let info = `Saved: ${file}\nModel: ${model} | quality: ${quality} | size: ${size}`;
  if (result.usage?.total_tokens) info += `\nOpenAI tokens used: ${result.usage.total_tokens}`;
  return [info, false];
}
