"""OpenAI image generation MCP server.

Gives an MCP client (such as Claude) a `generate_image` tool. Images are saved
to disk (default: your Pictures folder) and only the file path is returned, so
image data never fills up the conversation.

Works on Windows, macOS and Linux.

API key: read from OPENAI_API_KEY, or from a file named `api_key` in one of
(see key_files()):
  Windows  %APPDATA%\\openai\\api_key
  macOS    ~/Library/Application Support/openai/api_key
  Linux    $XDG_CONFIG_HOME/openai/api_key (normally ~/.config/openai/api_key)
  any OS   ~/.config/openai/api_key

Optional env vars:
  OPENAI_IMAGE_OUTPUT_DIR  default save folder (default: the Pictures folder)
  OPENAI_IMAGE_MODEL       default model (default: gpt-image-2)
"""

import base64
import codecs
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from openai import OpenAI
from platformdirs import user_config_dir, user_pictures_dir

DEFAULT_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2")
TRANSPARENT_MODEL = "gpt-image-1.5"  # gpt-image-2 can't do transparent backgrounds
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

mcp = MCPServer("openai-image")
_client = None


def expand(path: str) -> Path:
    """Expand ~ and environment variables ($HOME, %USERPROFILE%) in a path."""
    return Path(os.path.expanduser(os.path.expandvars(path.strip())))


def key_files() -> list[Path]:
    """Files the API key is read from, in order. The first is the OS's usual config folder."""
    paths = [
        # Windows: %APPDATA%\openai   macOS: ~/Library/Application Support/openai
        # Linux: $XDG_CONFIG_HOME/openai, normally ~/.config/openai
        Path(user_config_dir("openai", appauthor=False, roaming=True)) / "api_key",
        # Also checked everywhere, because many macOS and Windows users keep CLI config here
        Path.home() / ".config" / "openai" / "api_key",
    ]
    return list(dict.fromkeys(paths))


def read_key_file(path: Path) -> str:
    """Read a key file written by any editor or shell.

    Windows PowerShell 5 (`"sk-..." > api_key`) writes UTF-16 with a byte order mark,
    and Notepad may add a UTF-8 one, so handle both, plus trailing newlines.
    """
    raw = path.read_bytes()
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8-sig")
    return text.strip()


def find_api_key() -> str | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    for path in key_files():
        if path.is_file():
            key = read_key_file(path)
            if key:
                return key
    return None


def client() -> OpenAI:
    global _client
    if _client is None:
        key = find_api_key()
        if not key:
            places = "\n".join(f"  {p}" for p in key_files())
            raise RuntimeError(
                "No OpenAI API key. Set OPENAI_API_KEY, or save the key in a file named "
                f"api_key in one of these places:\n{places}"
            )
        _client = OpenAI(api_key=key)
    return _client


def default_output_dir() -> Path:
    custom = os.environ.get("OPENAI_IMAGE_OUTPUT_DIR", "").strip()
    if custom:
        return expand(custom)
    # Windows: the real Pictures folder, also when OneDrive moved it.
    # Linux: XDG_PICTURES_DIR, which may be translated (e.g. ~/Afbeeldingen). macOS: ~/Pictures
    return Path(user_pictures_dir())


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "image"


def output_file(output_path: str | None, output_format: str, prompt: str) -> Path:
    """Work out where to save the image.

    - nothing given: <default folder>/<time>-<prompt>.<format>
    - a folder (existing, or ending in / or \\): an auto-named file inside it
    - a relative path: inside the default folder, because the server's working
      directory is unpredictable (on Windows it can be C:\\Windows\\System32)
    - no image extension: the format's extension is added
    """
    auto_name = f"{datetime.now():%Y%m%d-%H%M%S}-{slug(prompt)}.{output_format}"
    if not output_path or not output_path.strip():
        return default_output_dir() / auto_name

    path = expand(output_path)
    if not path.is_absolute():
        path = default_output_dir() / path
    if path.is_dir() or output_path.rstrip().endswith(("/", "\\")):
        return path / auto_name
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        path = path.with_name(f"{path.name}.{output_format}")
    return path


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
    output_path: where to save, ideally an absolute path inside the user's project,
                 e.g. "/Users/me/site/images/hero.png" or "C:\\Users\\me\\site\\hero.png".
                 ~ and environment variables are expanded. A folder gets an
                 auto-named file; a relative path is saved inside the default folder.
                 If omitted, saves to the user's Pictures folder.
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

    path = output_file(output_path, output_format, prompt)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(result.data[0].b64_json))
    except OSError as e:  # e.g. no permission, or a name Windows doesn't allow
        return f"ERROR: the image was generated but could not be saved to {path}: {e}"

    info = f"Saved: {path}\nModel: {model} | quality: {quality} | size: {size}"
    usage = getattr(result, "usage", None)
    if usage and getattr(usage, "total_tokens", None):
        info += f"\nOpenAI tokens used: {usage.total_tokens}"
    return info


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
