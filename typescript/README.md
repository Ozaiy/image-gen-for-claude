# image-gen-for-claude

An [MCP](https://modelcontextprotocol.io) server that lets Claude (or any MCP client) generate images with the OpenAI Images API (gpt-image) or FLUX from Black Forest Labs. Works on Windows, macOS and Linux.

Images are saved to disk at full resolution. The model gets back the file path and a small JPEG preview (at most 1024px, quality 80), so it can see what it made without a multi-megabyte image filling up the conversation. In Claude Desktop and claude.ai the image is also shown large, right in the chat (using MCP Apps).

**Full documentation:** https://github.com/Ozaiy/image-gen-for-claude

## Install

**Claude Desktop:** download the `.mcpb` file from the [latest release](https://github.com/Ozaiy/image-gen-for-claude/releases/latest) then open Claude Desktop, go to **Settings**, search for "extensions", open **Extensions** and drag the file onto that page (on Windows, double-clicking it doesn't install it). Nothing else to install; Claude Desktop asks for your OpenAI API key and keeps it in your system keychain.

**Claude Code** (needs Node.js 20 or newer):

```sh
# macOS / Linux
claude mcp add image-gen --scope user -- npx -y image-gen-for-claude

# Windows
claude mcp add image-gen --scope user -- cmd /c npx -y image-gen-for-claude
```

**Other MCP clients:**

```json
{
  "mcpServers": {
    "image-gen": { "command": "npx", "args": ["-y", "image-gen-for-claude"] }
  }
}
```

## API key

The server uses `OPENAI_API_KEY` if it's set. Otherwise it reads a file named `api_key` from:

| OS | Location |
|---|---|
| Windows | `%APPDATA%\openai\api_key` |
| macOS | `~/Library/Application Support/openai/api_key` |
| Linux | `~/.config/openai/api_key` |
| any OS | `~/.config/openai/api_key` |

For FLUX it's the same with `BFL_API_KEY` and a `bfl` folder instead of `openai`, e.g. `%APPDATA%\bfl\api_key`. You only need one of the two keys.

## The tool

`generate_image` takes `prompt`, `quality` (`low` by default, because higher costs much more), `size`, `background` (`transparent` for logos), `output_format`, `output_path` and `model`. Without an `output_path`, images go to your Pictures folder; set `OPENAI_IMAGE_OUTPUT_DIR` to change that.

See the [full README](https://github.com/Ozaiy/image-gen-for-claude#readme) for details and the Python version.

## License

MIT. `dist/THIRD_PARTY_LICENSES.txt` lists the open-source packages bundled into `dist/index.js`.
