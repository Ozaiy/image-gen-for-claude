"""OpenAI image generation MCP server.

Gives an MCP client (such as Claude) a `generate_image` tool. Images are saved
to disk (default ~/Pictures) and only the file path is returned, so image data
never fills up the conversation.

API key: read from OPENAI_API_KEY, or from ~/.config/openai/api_key.
Optional env vars:
  OPENAI_IMAGE_OUTPUT_DIR  default save folder (default: ~/Pictures)
  OPENAI_IMAGE_MODEL       default model (default: gpt-image-2)
"""

import base64
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from openai import OpenAI

DEFAULT_DIR = Path(os.environ.get("OPENAI_IMAGE_OUTPUT_DIR", "~/Pictures")).expanduser()
DEFAULT_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2")
KEY_FILE = Path("~/.config/openai/api_key").expanduser()
TRANSPARENT_MODEL = "gpt-image-1.5"  # gpt-image-2 can't do transparent backgrounds

mcp = MCPServer("openai-image")
_client = None


def client() -> OpenAI:
    global _client
    if _client is None:
        key = os.environ.get("OPENAI_API_KEY")
        if not key and KEY_FILE.exists():
            key = KEY_FILE.read_text().strip()
        if not key:
            raise RuntimeError(
                f"No OpenAI API key. Set OPENAI_API_KEY or put the key in {KEY_FILE}"
            )
        _client = OpenAI(api_key=key)
    return _client


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "image"


@mcp.tool()
def generate_image(
    prompt: str,
    quality: Literal["low", "medium", "high"] = "low",
    size: Literal["1024x1024", "1536x1024", "1024x1536"] = "1024x1024",
    background: Literal["auto", "opaque", "transparent"] = "auto",
    output_format: Literal["png", "jpeg", "webp"] = "png",
    output_path: str | None = None,
    model: str | None = None,
) -> str:
    """Generate an image with OpenAI and save it to disk. Returns the saved file path.

    QUALITY - choose carefully, higher quality costs much more:
      - "low"    (default) drafts, previews, trying out ideas, placeholders.
      - "medium" decent images for normal use when low looks too rough.
      - "high"   ONLY for final assets the user explicitly wants in high quality,
                 or after a low-quality draft has been approved. Never use
                 "high" for experiments or multiple variations.

    size: 1024x1024 square, 1536x1024 landscape (hero banners), 1024x1536 portrait.
    background: "transparent" for logos/icons/stickers (needs png or webp).
    output_path: full file path to save to (e.g. inside a project folder).
                 If omitted, saves to the default Pictures folder.
    model: override the default model (normally leave empty).
    """
    model = model or DEFAULT_MODEL
    if background == "transparent":
        if output_format == "jpeg":
            output_format = "png"
        if model == "gpt-image-2":
            model = TRANSPARENT_MODEL

    try:
        result = client().images.generate(
            model=model,
            prompt=prompt,
            quality=quality,
            size=size,
            background=background,
            output_format=output_format,
            n=1,
        )
    except Exception as e:  # pass the real reason back to the client
        return f"ERROR ({type(e).__name__}): {e}"

    if output_path:
        path = Path(output_path).expanduser()
        if not path.suffix:
            path = path.with_suffix("." + output_format)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = DEFAULT_DIR / f"{stamp}-{slug(prompt)}.{output_format}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(result.data[0].b64_json))

    info = f"Saved: {path}\nModel: {model} | quality: {quality} | size: {size}"
    usage = getattr(result, "usage", None)
    if usage and getattr(usage, "total_tokens", None):
        info += f"\nOpenAI tokens used: {usage.total_tokens}"
    return info


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
