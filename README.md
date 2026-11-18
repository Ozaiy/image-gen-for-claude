# openai-image-mcp

An [MCP](https://modelcontextprotocol.io) server that lets Claude (or any MCP client) generate images with the OpenAI Images API.

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
| `output_path` | file to save to, e.g. `~/project/images/hero.png` | `~/Pictures/<time>-<prompt>.png` |
| `model` | any OpenAI image model | `gpt-image-2` |

Some details:

- **Quality defaults to `low`** because higher quality costs a lot more. The tool description tells the model to use `high` only for final images you asked for.
- **Transparent backgrounds** switch to `gpt-image-1.5`, because `gpt-image-2` doesn't support them. JPEG is changed to PNG, since JPEG can't be transparent.
- **If OpenAI returns an error**, the server passes the reason back to the model as text, so it can tell you what went wrong.

## Requirements

- An [OpenAI API key](https://platform.openai.com/api-keys) with access to the image models. Image generation is billed per image by OpenAI.
- [uv](https://docs.astral.sh/uv/), or Python 3.10 or newer with pip.

## Setup

### 1. Save your API key

The server reads the key from the `OPENAI_API_KEY` environment variable. If that isn't set, it reads `~/.config/openai/api_key`.

Using the file keeps the key out of your MCP config:

```sh
mkdir -p ~/.config/openai
read -s KEY && printf '%s' "$KEY" > ~/.config/openai/api_key && chmod 600 ~/.config/openai/api_key
```

Paste the key when it waits for input (nothing is shown), then press Enter.

### 2. Add the server to your client

**Claude Code**

```sh
claude mcp add openai-image -- uvx --from git+https://github.com/Ozaiy/openai-image-mcp openai-image-mcp
```

Add `--scope user` to make it available in all your projects.

**Claude Desktop**, and other clients that use an `mcpServers` JSON config:

```json
{
  "mcpServers": {
    "openai-image": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Ozaiy/openai-image-mcp", "openai-image-mcp"]
    }
  }
}
```

**Without uv**:

```sh
python3 -m venv ~/.venvs/openai-image-mcp
~/.venvs/openai-image-mcp/bin/pip install git+https://github.com/Ozaiy/openai-image-mcp
```

Then use `~/.venvs/openai-image-mcp/bin/openai-image-mcp` as the command, written out as a full path.

### 3. Try it

Ask Claude something like *"Generate a low-quality draft of a logo for a coffee shop called Bean There, transparent background"*. It replies with the path of the saved file.

## Settings

| Environment variable | What it does | Default |
|---|---|---|
| `OPENAI_API_KEY` | your OpenAI API key | read from `~/.config/openai/api_key` |
| `OPENAI_IMAGE_OUTPUT_DIR` | folder for images saved without an `output_path` | `~/Pictures` |
| `OPENAI_IMAGE_MODEL` | default model | `gpt-image-2` |

In Claude Code you can set these with `-e`, for example `claude mcp add openai-image -e OPENAI_IMAGE_OUTPUT_DIR=~/Images -- uvx ...`.

## Development

```sh
git clone https://github.com/Ozaiy/openai-image-mcp
cd openai-image-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/openai-image-mcp   # starts the server on stdio
```

The whole server is in [`src/openai_image_mcp/server.py`](src/openai_image_mcp/server.py).

## License

[MIT](LICENSE)
