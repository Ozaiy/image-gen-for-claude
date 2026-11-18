# image-gen-for-claude

An [MCP](https://modelcontextprotocol.io) server that lets Claude (or any MCP client) generate images with the OpenAI Images API (gpt-image) or the [FLUX API](https://docs.bfl.ai) from Black Forest Labs. Works on Windows, macOS and Linux.

> **Renamed in 0.6.0** from `openai-image-mcp-for-claude`, since it does more than OpenAI now. The npm package is now `image-gen-for-claude`, the server and tool are called `image-gen`, and the Claude Code plugin is `image-gen@ozaiy`. Old links to the GitHub repository still work. To move over, remove the old setup (`claude mcp remove openai-image --scope user`, or the old extension in Claude Desktop) and install again with the commands below. Your API key files and `OPENAI_IMAGE_*` settings keep working unchanged.

Images are saved to disk at full resolution, straight into the project the model is working on if it names a path. The model gets back the file path and a small JPEG preview (at most 1024px, quality 80), so it can see what it made without a multi-megabyte image filling up the conversation.

In Claude Desktop and claude.ai the image is also shown large, right in the chat. Click the image to view it full screen. In every client Claude gives you the saved path in its reply as a clickable link (the tool result includes a `file:///` URL for it), so in Claude Code you can click it to open the image: in VS Code it opens in an editor tab, and in a terminal that supports links it opens in your image viewer.

## What it does

The server gives you one tool, `generate_image`:

| Parameter | Values | Default |
|---|---|---|
| `prompt` | what to draw | required |
| `quality` | `low`, `medium`, `high` | `low` |
| `size` | `1024x1024`, `1536x1024` (landscape), `1024x1536` (portrait) | `1024x1024` |
| `background` | `auto`, `opaque`, `transparent` | `auto` |
| `output_format` | `png`, `jpeg`, `webp` | `png` |
| `output_path` | file or folder to save to, e.g. `~/site/images/hero.png` or `C:\Users\me\site\images\` | your Pictures folder, as `<time>-<prompt>.png` |
| `model` | an OpenAI image model (`gpt-image-2`, `gpt-image-1.5`, ...) or a FLUX model (`flux-3-image`, `flux-3-image-klein`, `flux-2-pro`, ...) | `gpt-image-2`, or `flux-3-image` if you only set up a FLUX key |

Some details:

- **Quality defaults to `low`** because higher quality costs a lot more. The tool description tells the model to use `high` only for final images you asked for.
- **Transparent backgrounds** switch to `gpt-image-1.5`, because `gpt-image-2` doesn't support them. JPEG is changed to PNG, since JPEG can't be transparent.
- **FLUX** is used when `model` starts with `flux-`. Supported are FLUX 3 Image (`flux-3-image`, `flux-3-image-klein`) and the FLUX.2 models (`flux-2-pro`, `flux-2-max`, `flux-2-flex`, `flux-2-klein-4b`, `flux-2-klein-9b`). Ask Claude for "a FLUX image" and it picks the model. FLUX ignores `quality` and can't make transparent backgrounds. The image is saved in the `output_format` you asked for, converted if FLUX sent another format. As a guide, a 1024×1024 image cost 4.8 credits ($0.05) with `flux-3-image` and 1.1 credits ($0.01) with `flux-3-image-klein` when tested; the tool reports the actual cost of each image. See [bfl.ai/pricing](https://bfl.ai/pricing).
- **The preview** is a JPEG with its longest side at most 1024px, sent as `image/jpeg`. Transparent areas show as white in it; the saved file keeps its transparency. In the npx and Claude Desktop versions a WebP can't be shrunk, so it's sent unchanged (`image/webp`) when it's under 512 KB and left out when it's bigger.
- **Showing the image in the chat** uses [MCP Apps](https://github.com/modelcontextprotocol/ext-apps): the tool comes with a small HTML view (`src/image_gen_for_claude/view.html`) that the client draws inline, filled with the preview from the tool result. It loads nothing from the internet. Clients without MCP Apps support, such as Claude Code, ignore it and show the result as before.
- **If OpenAI or FLUX returns an error** (no credits, blocked by moderation, ...), the server passes the reason back to the model as text, so it can tell you what went wrong.

### Where images are saved

- **No `output_path`:** your Pictures folder. On Windows that's the real Pictures folder, also when OneDrive has moved it. On macOS it's `~/Pictures`. On Linux it's the folder set in `XDG_PICTURES_DIR`, which may have a translated name such as `~/Afbeeldingen`.
- **A full path** (`/Users/me/site/hero.png`, `C:\Users\me\site\hero.png`): saved exactly there. Missing folders are created.
- **A folder** (one that exists, or a path ending in `/` or `\`): an auto-named file inside it.
- **A relative path** (`logos/logo.png`): saved inside the default folder. The server's working directory depends on the client, and on Windows it can even be `C:\Windows\System32`, so relative paths aren't resolved against it.
- `~`, `$HOME` and `%USERPROFILE%`-style environment variables are expanded. If the path has no image extension, one is added, so `hero` becomes `hero.png`.

## Install

Pick one. All four give you the same tool and behave the same way.

| Option | You need to install first | Best for |
|---|---|---|
| [1. Claude Desktop extension](#option-1-claude-desktop-extension) | nothing | Claude Desktop |
| [2. Claude Code plugin](#option-2-claude-code-plugin) | [Node.js](https://nodejs.org) 20 or newer | Claude Code (terminal and VS Code) |
| [3. npx](#option-3-npx-nodejs) | [Node.js](https://nodejs.org) 20 or newer | other MCP clients |
| [4. uvx](#option-4-uvx-python) | [uv](https://docs.astral.sh/uv/getting-started/installation/) | people who prefer Python |

You also need an API key for at least one of the two services: an [OpenAI API key](https://platform.openai.com/api-keys) with access to the image models, or a [FLUX API key](https://dashboard.bfl.ai) from Black Forest Labs. Both bill per image.

### Option 1: Claude Desktop extension

1. Download `image-gen-for-claude-<version>.mcpb` from the [latest release](https://github.com/Ozaiy/image-gen-for-claude/releases/latest).
2. Open Claude Desktop, go to **Settings**, search for "extensions" and open **Extensions**. Drag the `.mcpb` file onto that page. (On Windows, double-clicking the file doesn't install it.)
3. Enter your OpenAI API key, your FLUX API key, or both, when asked. Claude Desktop stores it in your system keychain (Keychain on macOS, Credential Manager on Windows). You can also choose a save folder there; leave it empty for your Pictures folder.

It runs on the Node.js that ships with Claude Desktop, so there's nothing else to install, and you don't need the API key file described below.

### Option 2: Claude Code plugin

Claude Code asks for your API keys in a form and stores them in your system keychain, so you don't need the API key file described below. Works in the terminal and in the VS Code extension, on Windows, macOS and Linux. Needs [Node.js](https://nodejs.org) 20 or newer on your `PATH`.

**Terminal:** in a Claude Code session, run

```text
/plugin install image-gen --marketplace Ozaiy/image-gen-for-claude
```

choose a scope (**Install for you** makes it available in every project), and fill in your OpenAI key, your FLUX key, or both. You can also choose a save folder; leave it empty for your Pictures folder. To change a key later, run `/plugin configure image-gen@ozaiy`.

**VS Code:** type `/plugins` in the Claude Code panel. On the **Marketplaces** tab add `Ozaiy/image-gen-for-claude`, then install **Image Generation (OpenAI & FLUX)** on the **Plugins** tab. Claude Code shows the form for the keys after the install; the gear icon on the plugin's row opens it again.

The tool is then called `mcp__plugin_image-gen_image-gen__generate_image`. If you set up the server with `claude mcp add` before, remove that one (`claude mcp remove image-gen --scope user`, or `claude mcp remove openai-image --scope user` for a setup from before 0.6.0), or Claude sees two image tools.

Updates come from this repository's main branch. Run `/plugin`, open **Image Generation (OpenAI & FLUX)** on the **Installed** tab and choose **Update now**, or turn on auto-update for the `ozaiy` marketplace on the **Marketplaces** tab.

### Option 3: npx (Node.js)

Save your API key first (see [API key](#api-key-for-options-3-and-4)).

**Claude Code** on macOS and Linux:

```sh
claude mcp add image-gen --scope user -- npx -y image-gen-for-claude
```

**Claude Code** on Windows (`npx` needs to be started through `cmd`):

```sh
claude mcp add image-gen --scope user -- cmd /c npx -y image-gen-for-claude
```

**Other clients** with an `mcpServers` JSON config:

```json
{
  "mcpServers": {
    "image-gen": {
      "command": "npx",
      "args": ["-y", "image-gen-for-claude"]
    }
  }
}
```

The package has no dependencies (everything is bundled into one file), so `npx` starts it quickly.

### Option 4: uvx (Python)

Save your API key first (see [API key](#api-key-for-options-3-and-4)). Install uv if you don't have it:

- **macOS / Linux:** `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Windows:** `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

**Claude Code** (all platforms):

```sh
claude mcp add image-gen --scope user -- uvx --from git+https://github.com/Ozaiy/image-gen-for-claude image-gen-for-claude
```

**Other clients** with an `mcpServers` JSON config:

```json
{
  "mcpServers": {
    "image-gen": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Ozaiy/image-gen-for-claude", "image-gen-for-claude"]
    }
  }
}
```

**Without uv:**

```sh
# macOS / Linux
python3 -m venv ~/.venvs/image-gen-for-claude
~/.venvs/image-gen-for-claude/bin/pip install git+https://github.com/Ozaiy/image-gen-for-claude
# command: /Users/me/.venvs/image-gen-for-claude/bin/image-gen-for-claude
```

```powershell
# Windows
py -m venv $HOME\.venvs\image-gen-for-claude
& $HOME\.venvs\image-gen-for-claude\Scripts\pip install git+https://github.com/Ozaiy/image-gen-for-claude
# command: C:\Users\me\.venvs\image-gen-for-claude\Scripts\image-gen-for-claude.exe
```

Use that full path as the `command` in your client config.

### "npx/uvx not found" or the server fails to start

Desktop apps often don't see the folder Node.js or uv was installed in, especially on macOS. Use the full path as `command` instead. Run `which npx` / `which uvx` (macOS, Linux) or `where.exe npx` / `where.exe uvx` (Windows) to find it. In JSON on Windows, write each `\` as `\\`, e.g. `C:\\Users\\me\\.local\\bin\\uvx.exe`.

Restart your client after changing its config.

### API key (for options 3 and 4)

The server uses the `OPENAI_API_KEY` environment variable if it's set. Otherwise it reads the key from a file named `api_key`, in the first of these places that exists:

| OS | Location |
|---|---|
| Windows | `%APPDATA%\openai\api_key` (e.g. `C:\Users\me\AppData\Roaming\openai\api_key`) |
| macOS | `~/Library/Application Support/openai/api_key` |
| Linux | `~/.config/openai/api_key` (or `$XDG_CONFIG_HOME/openai/api_key`) |
| any OS | `~/.config/openai/api_key` |

A file keeps the key out of your MCP config. The commands below create it; paste your key when asked.

**macOS / Linux** (nothing is shown while you paste; press Enter after):

```sh
mkdir -p ~/.config/openai
read -s KEY && printf '%s' "$KEY" > ~/.config/openai/api_key && chmod 600 ~/.config/openai/api_key
```

**Windows** (PowerShell):

```powershell
New-Item -ItemType Directory -Force "$env:APPDATA\openai" | Out-Null
Read-Host "OpenAI API key" | Set-Content -NoNewline -Encoding ascii "$env:APPDATA\openai\api_key"
```

You can also make the file in Notepad. Any encoding works, including the UTF-16 that `"sk-..." > api_key` produces in Windows PowerShell 5.

**FLUX key:** the same, with `BFL_API_KEY` as the environment variable and a folder named `bfl` instead of `openai`, for example `~/.config/bfl/api_key` or `%APPDATA%\bfl\api_key`:

```sh
mkdir -p ~/.config/bfl
read -s KEY && printf '%s' "$KEY" > ~/.config/bfl/api_key && chmod 600 ~/.config/bfl/api_key
```

```powershell
New-Item -ItemType Directory -Force "$env:APPDATA\bfl" | Out-Null
Read-Host "FLUX API key" | Set-Content -NoNewline -Encoding ascii "$env:APPDATA\bfl\api_key"
```

If the key can't be found, the tool's error message lists the exact paths it checked on your computer.

### Try it

Ask Claude something like *"Generate a low-quality draft of a logo for a coffee shop called Bean There, transparent background"*, or *"Make a FLUX image of a lighthouse at sunset, landscape"*. It replies with the path of the saved file and can see a preview of the image.

## Settings

| Environment variable | What it does | Default |
|---|---|---|
| `OPENAI_API_KEY` | your OpenAI API key | read from the `api_key` file (see above) |
| `BFL_API_KEY` | your FLUX API key | read from the `bfl/api_key` file (see above) |
| `OPENAI_IMAGE_OUTPUT_DIR` | folder for images saved without a full `output_path` | your Pictures folder |
| `OPENAI_IMAGE_MODEL` | default model, OpenAI or FLUX (e.g. `flux-3-image`) | `gpt-image-2`, or `flux-3-image` if only a FLUX key is set up |

In Claude Code you can set these with `-e`, for example `claude mcp add image-gen -e OPENAI_IMAGE_OUTPUT_DIR=~/Images -- npx -y image-gen-for-claude`. The Claude Desktop extension sets the two keys and the save folder from its settings screen.

## Development

There are two implementations with the same behavior and the same tests:

- **Python** in [`src/image_gen_for_claude/server.py`](src/image_gen_for_claude/server.py), used by option 4.
- **TypeScript** in [`typescript/src/`](typescript/src), used by options 1, 2 and 3. `npm run build` bundles it and its dependencies into the single file `typescript/dist/index.js`, which the npm package and the `.mcpb` contain. The build also copies it to `plugin/server/index.js` for the Claude Code plugin; that copy is committed, because Claude Code installs the plugin straight from this repository, so commit `plugin/` after a build. CI fails if the committed copy is out of date.

```sh
git clone https://github.com/Ozaiy/image-gen-for-claude
cd image-gen-for-claude

# Python
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"     # Windows: .venv\Scripts\pip install -e ".[test]"
.venv/bin/python -m pytest             # Windows: .venv\Scripts\python -m pytest

# TypeScript
cd typescript
npm ci
npm run build
npm test
npm run pack:mcpb                      # builds build/image-gen-for-claude-<version>.mcpb
```

The tests run on Windows, macOS and Linux with GitHub Actions on every push.

**Releasing:** set the same version in `pyproject.toml`, `src/image_gen_for_claude/__init__.py`, `typescript/package.json`, `typescript/manifest.json`, `typescript/src/lib.ts` and `plugin/.claude-plugin/plugin.json`, run `npm run build` in `typescript/` and commit, then push a tag such as `v0.3.0`. The release workflow builds the `.mcpb`, attaches it to a GitHub release, and publishes the npm package if the repository has an `NPM_TOKEN` secret. The Claude Code plugin is updated by the push to main itself.

## License

[MIT](LICENSE)
