# openai-image-mcp-for-claude

An [MCP](https://modelcontextprotocol.io) server that lets Claude (or any MCP client) generate images with the OpenAI Images API. Works on Windows, macOS and Linux.

Images are saved to disk and only the file path goes back to the model, so no image data ends up in the conversation. That keeps the context small and lets the model save images straight into the project it's working on.

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
| `model` | any OpenAI image model | `gpt-image-2` |

Some details:

- **Quality defaults to `low`** because higher quality costs a lot more. The tool description tells the model to use `high` only for final images you asked for.
- **Transparent backgrounds** switch to `gpt-image-1.5`, because `gpt-image-2` doesn't support them. JPEG is changed to PNG, since JPEG can't be transparent.
- **If OpenAI returns an error**, the server passes the reason back to the model as text, so it can tell you what went wrong.

### Where images are saved

- **No `output_path`:** your Pictures folder. On Windows that's the real Pictures folder, also when OneDrive has moved it. On macOS it's `~/Pictures`. On Linux it's the folder set in `XDG_PICTURES_DIR`, which may have a translated name such as `~/Afbeeldingen`.
- **A full path** (`/Users/me/site/hero.png`, `C:\Users\me\site\hero.png`): saved exactly there. Missing folders are created.
- **A folder** (one that exists, or a path ending in `/` or `\`): an auto-named file inside it.
- **A relative path** (`logos/logo.png`): saved inside the default folder. The server's working directory depends on the client, and on Windows it can even be `C:\Windows\System32`, so relative paths aren't resolved against it.
- `~`, `$HOME` and `%USERPROFILE%`-style environment variables are expanded. If the path has no image extension, one is added, so `hero` becomes `hero.png`.

## Requirements

- An [OpenAI API key](https://platform.openai.com/api-keys) with access to the image models. Image generation is billed per image by OpenAI.
- [uv](https://docs.astral.sh/uv/), or Python 3.10 or newer with pip.

## Setup

### 1. Save your API key

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

If the key can't be found, the tool's error message lists the exact paths it checked on your computer.

### 2. Install uv

[uv](https://docs.astral.sh/uv/getting-started/installation/) downloads and runs the server for you.

- **macOS / Linux:** `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Windows:** `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

### 3. Add the server to your client

**Claude Code** (all platforms):

```sh
claude mcp add openai-image --scope user -- uvx --from git+https://github.com/Ozaiy/openai-image-mcp-for-claude openai-image-mcp
```

**Claude Desktop**, and other clients with an `mcpServers` JSON config. Claude Desktop's config file is in:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "openai-image": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Ozaiy/openai-image-mcp-for-claude", "openai-image-mcp"]
    }
  }
}
```

Restart Claude Desktop after changing it.

> **"uvx not found" / server fails to start:** desktop apps often don't see the folder uv was installed to, especially on macOS. Use the full path as `command` instead:
> - macOS / Linux: `/Users/me/.local/bin/uvx` or `/home/me/.local/bin/uvx` (run `which uvx` to find it)
> - Windows: `C:\\Users\\me\\.local\\bin\\uvx.exe` (run `where.exe uvx`; in JSON, write each `\` as `\\`)

**Without uv:**

```sh
# macOS / Linux
python3 -m venv ~/.venvs/openai-image-mcp
~/.venvs/openai-image-mcp/bin/pip install git+https://github.com/Ozaiy/openai-image-mcp-for-claude
# command: /Users/me/.venvs/openai-image-mcp/bin/openai-image-mcp
```

```powershell
# Windows
py -m venv $HOME\.venvs\openai-image-mcp
& $HOME\.venvs\openai-image-mcp\Scripts\pip install git+https://github.com/Ozaiy/openai-image-mcp-for-claude
# command: C:\Users\me\.venvs\openai-image-mcp\Scripts\openai-image-mcp.exe
```

Use that full path as the `command` in your client config.

### 4. Try it

Ask Claude something like *"Generate a low-quality draft of a logo for a coffee shop called Bean There, transparent background"*. It replies with the path of the saved file.

## Settings

| Environment variable | What it does | Default |
|---|---|---|
| `OPENAI_API_KEY` | your OpenAI API key | read from the `api_key` file (see above) |
| `OPENAI_IMAGE_OUTPUT_DIR` | folder for images saved without a full `output_path` | your Pictures folder |
| `OPENAI_IMAGE_MODEL` | default model | `gpt-image-2` |

In Claude Code you can set these with `-e`, for example `claude mcp add openai-image -e OPENAI_IMAGE_OUTPUT_DIR=~/Images -- uvx ...`.

## Development

```sh
git clone https://github.com/Ozaiy/openai-image-mcp-for-claude
cd openai-image-mcp-for-claude
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"     # Windows: .venv\Scripts\pip install -e ".[test]"
.venv/bin/python -m pytest             # Windows: .venv\Scripts\python -m pytest
```

The whole server is in [`src/openai_image_mcp/server.py`](src/openai_image_mcp/server.py). The tests run on Windows, macOS and Linux with GitHub Actions on every push.

## License

[MIT](LICENSE)
