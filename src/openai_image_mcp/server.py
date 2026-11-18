"""Image generation MCP server for OpenAI (gpt-image) and Black Forest Labs (FLUX).

Gives an MCP client (such as Claude) a `generate_image` tool. Images are saved
to disk (default: your Pictures folder) at full resolution. The tool returns the
file path plus a small JPEG preview (at most 1024px, quality 80), so the model
can see the result without a multi-megabyte image filling up the conversation.

Works on Windows, macOS and Linux.

API keys: OPENAI_API_KEY and BFL_API_KEY, or a file named `api_key` in a folder
named after the service, `openai` or `bfl` (see key_files()):
  Windows  %APPDATA%\\openai\\api_key
  macOS    ~/Library/Application Support/openai/api_key
  Linux    $XDG_CONFIG_HOME/openai/api_key (normally ~/.config/openai/api_key)
  any OS   ~/.config/openai/api_key
Only one of the two is needed.

Optional env vars:
  OPENAI_IMAGE_OUTPUT_DIR  default save folder (default: the Pictures folder)
  OPENAI_IMAGE_MODEL       default model (default: gpt-image-2 with an OpenAI
                           key, otherwise flux-3-image with a FLUX key)
"""

import base64
import codecs
import io
import logging
import os
import re
import time
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import Image, MCPServer
from openai import OpenAI
from PIL import Image as PILImage
from platformdirs import user_config_dir, user_pictures_dir

TRANSPARENT_MODEL = "gpt-image-1.5"  # gpt-image-2 can't do transparent backgrounds
DEFAULT_FLUX_MODEL = "flux-3-image"
BFL_API = "https://api.bfl.ai/v1"
FLUX_POLL_TIMEOUT = 5 * 60  # seconds
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
PREVIEW_MAX_SIDE = 1024  # px; the full-resolution image stays on disk
PREVIEW_QUALITY = 80

KEY_ENV = {"openai": "OPENAI_API_KEY", "bfl": "BFL_API_KEY"}
PROVIDER_NAME = {"openai": "OpenAI", "bfl": "Black Forest Labs (FLUX)"}

# MCP Apps: hosts that support it (Claude Desktop, claude.ai) show the image large,
# inline in the chat, using this HTML view. Other clients ignore it.
VIEW_URI = "ui://openai-image/view.html"
VIEW_MIME_TYPE = "text/html;profile=mcp-app"

mcp = MCPServer("openai-image")
_client = None
# httpx logs every request, including FLUX's signed download URLs; keep only problems
logging.getLogger("httpx").setLevel(logging.WARNING)


@mcp.resource(VIEW_URI, name="image_view", title="Generated image", mime_type=VIEW_MIME_TYPE,
              meta={"ui": {"prefersBorder": False}})
def image_view() -> str:
    return files(__package__).joinpath("view.html").read_text(encoding="utf-8")


def expand(path: str) -> Path:
    """Expand ~ and environment variables ($HOME, %USERPROFILE%) in a path."""
    return Path(os.path.expanduser(os.path.expandvars(path.strip())))


# ---------- API keys ----------


def key_files(provider: str = "openai") -> list[Path]:
    """Files the API key is read from, in order. The first is the OS's usual config folder."""
    paths = [
        # Windows: %APPDATA%\openai   macOS: ~/Library/Application Support/openai
        # Linux: $XDG_CONFIG_HOME/openai, normally ~/.config/openai
        Path(user_config_dir(provider, appauthor=False, roaming=True)) / "api_key",
        # Also checked everywhere, because many macOS and Windows users keep CLI config here
        Path.home() / ".config" / provider / "api_key",
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


def find_api_key(provider: str = "openai") -> str | None:
    key = os.environ.get(KEY_ENV[provider], "").strip()
    if key:
        return key
    for path in key_files(provider):
        if path.is_file():
            key = read_key_file(path)
            if key:
                return key
    return None


def require_api_key(provider: str = "openai") -> str:
    """The API key, or an error saying exactly where to put it."""
    key = find_api_key(provider)
    if key:
        return key
    places = "\n".join(f"  {p}" for p in key_files(provider))
    raise RuntimeError(
        f"No {PROVIDER_NAME[provider]} API key. Set {KEY_ENV[provider]}, or save the key in a file "
        f"named api_key in one of these places:\n{places}"
    )


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=require_api_key("openai"))
    return _client


def default_model() -> str:
    """OPENAI_IMAGE_MODEL, else OpenAI if it has a key, else FLUX if it has one."""
    configured = os.environ.get("OPENAI_IMAGE_MODEL", "").strip()
    if configured:
        return configured
    if not find_api_key("openai") and find_api_key("bfl"):
        return DEFAULT_FLUX_MODEL
    return "gpt-image-2"


# ---------- output paths ----------


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


# ---------- images ----------


def _flatten(img: PILImage.Image) -> PILImage.Image:
    """RGB, with transparent areas on white (JPEG has no alpha channel)."""
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        flat = PILImage.new("RGB", rgba.size, "white")
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return img.convert("RGB")


def preview_jpeg(data: bytes) -> bytes:
    """A small JPEG of the image for the model to look at.

    Longest side at most PREVIEW_MAX_SIDE. Transparent areas become white,
    because JPEG has no alpha channel.
    """
    with PILImage.open(io.BytesIO(data)) as img:
        img.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE), PILImage.Resampling.LANCZOS)
        out = io.BytesIO()
        _flatten(img).save(out, "JPEG", quality=PREVIEW_QUALITY, optimize=True)
        return out.getvalue()


def image_format(data: bytes) -> str | None:
    """"png", "jpeg" or "webp", from the image bytes."""
    try:
        with PILImage.open(io.BytesIO(data)) as img:
            return {"PNG": "png", "JPEG": "jpeg", "WEBP": "webp"}.get(img.format or "")
    except Exception:
        return None


def convert_image(data: bytes, to: str) -> bytes:
    """Re-encode as png, jpeg (quality 95) or webp."""
    with PILImage.open(io.BytesIO(data)) as img:
        out = io.BytesIO()
        if to == "jpeg":
            _flatten(img).save(out, "JPEG", quality=95)
        elif to == "webp":
            img.save(out, "WEBP", quality=95)
        else:
            img.save(out, "PNG")
        return out.getvalue()


# ---------- FLUX (Black Forest Labs) ----------


def is_flux_model(model: str) -> bool:
    return model.startswith("flux-")


def flux_supported(model: str) -> bool:
    """FLUX 3 Image and the FLUX.2 family take width/height; the older FLUX.1 models take other fields."""
    return model.startswith("flux-3-image") or model.startswith("flux-2-")


def flux_body(model: str, prompt: str, size: str, output_format: str) -> dict[str, Any]:
    """The request body for a FLUX model. Endpoints reject unknown fields, so only send what each takes."""
    width, height = (int(n) for n in size.split("x"))
    body: dict[str, Any] = {"prompt": prompt, "width": width, "height": height}
    if model.startswith("flux-2-"):
        body["output_format"] = output_format  # jpeg, png or webp
    elif model.startswith("flux-3-image-klein") and output_format != "webp":
        body["output_format"] = output_format
    # flux-3-image has no output_format; what it returns is converted afterwards
    return body


def _http() -> httpx.Client:
    return httpx.Client(timeout=60)


def generate_flux(model: str, body: dict[str, Any], key: str, poll_seconds: float = 0.75) -> tuple[bytes, float | None]:
    """Submit, poll until ready, and download right away (the result URL expires).

    Returns the image bytes and the cost in credits.
    """
    headers = {"x-key": key, "accept": "application/json"}
    with _http() as http:
        submit = http.post(f"{BFL_API}/{model}", headers=headers, json=body)
        if submit.status_code == 402:
            raise RuntimeError("FLUX: not enough credits. Add credits at https://dashboard.bfl.ai")
        if submit.status_code == 429:
            raise RuntimeError("FLUX: too many requests at once. Try again in a moment.")
        if submit.status_code in (401, 403):
            raise RuntimeError(f"FLUX: the API key was refused (HTTP {submit.status_code}).")
        if submit.status_code == 404:
            raise RuntimeError(f'FLUX: unknown model "{model}" (HTTP 404).')
        if submit.status_code >= 400:
            raise RuntimeError(f"FLUX: HTTP {submit.status_code} {submit.text[:500]}")
        task = submit.json()
        if not task.get("polling_url"):
            raise RuntimeError("FLUX: no polling_url in the response")

        deadline = time.monotonic() + FLUX_POLL_TIMEOUT
        while True:
            time.sleep(poll_seconds)
            poll = http.get(task["polling_url"], headers=headers)
            # a failed task can come back as HTTP 503 with a JSON body, so read the body either way
            try:
                state = poll.json()
            except ValueError:
                state = {"status": f"HTTP {poll.status_code}"}
            status = state.get("status") or ""
            if status == "Ready":
                url = (state.get("result") or {}).get("sample")
                if not url:
                    raise RuntimeError("FLUX: the result has no image URL")
                download = http.get(url)
                if download.status_code >= 400:
                    raise RuntimeError(f"FLUX: downloading the image failed (HTTP {download.status_code})")
                return download.content, task.get("cost")
            if status in ("Pending", "Reasoning", "Generating"):
                if time.monotonic() > deadline:
                    raise RuntimeError("FLUX: still not ready after 5 minutes")
                continue
            if status in ("Request Moderated", "Content Moderated"):
                raise RuntimeError(f"FLUX: {status}. The prompt or result was blocked by moderation.")
            details = f" {str(state.get('details'))[:500]}" if state.get("details") else ""
            raise RuntimeError(f"FLUX: {status or 'unknown status'}.{details}")


# ---------- the tool ----------


# "ui/resourceUri" is the older spelling of the same key, for hosts that only know that one
@mcp.tool(meta={"ui": {"resourceUri": VIEW_URI}, "ui/resourceUri": VIEW_URI})
def generate_image(
    prompt: str,
    quality: Literal["low", "medium", "high"] = "low",
    size: Literal["1024x1024", "1536x1024", "1024x1536"] = "1024x1024",
    background: Literal["auto", "opaque", "transparent"] = "auto",
    output_format: Literal["png", "jpeg", "webp"] = "png",
    output_path: str | None = None,
    model: str | None = None,
) -> str | list[str | Image]:
    """Generate an image with OpenAI (gpt-image) or Black Forest Labs (FLUX) and save
    it to disk. Returns the saved file path and a small JPEG preview of the image
    (the saved file is full resolution).
    In your reply, always give the user the full path of the saved file.

    model: leave empty for the default (OpenAI gpt-image-2 if an OpenAI key is set
           up, otherwise FLUX flux-3-image). Use a FLUX model when the user asks for
           FLUX: "flux-3-image" (best), "flux-3-image-klein" (fast, cheap), or a
           FLUX.2 model such as "flux-2-pro". FLUX can't do transparent backgrounds
           and ignores quality.

    QUALITY (OpenAI only) - choose carefully, higher quality costs much more:
      - "low"    (default) drafts, previews, trying out ideas, placeholders.
      - "medium" decent images for normal use when low looks too rough.
      - "high"   ONLY for final assets the user explicitly wants in high quality,
                 or after a low-quality draft has been approved. Never use
                 "high" for experiments or multiple variations.

    size: 1024x1024 square, 1536x1024 landscape (hero banners), 1024x1536 portrait.
    background: "transparent" for logos/icons/stickers (needs png or webp; OpenAI only).
    output_path: where to save, ideally an absolute path inside the user's project,
                 e.g. "/Users/me/site/images/hero.png" or "C:\\Users\\me\\site\\hero.png".
                 ~ and environment variables are expanded. A folder gets an
                 auto-named file; a relative path is saved inside the default folder.
                 If omitted, saves to the user's Pictures folder.
    """
    model = (model or "").strip() or default_model()
    flux = is_flux_model(model)
    if background == "transparent":
        if flux:
            return ("ERROR: FLUX models can't make transparent backgrounds. Use an OpenAI model "
                    '(leave model empty or use "gpt-image-1.5").')
        if output_format == "jpeg":
            output_format = "png"
        if model == "gpt-image-2":
            model = TRANSPARENT_MODEL
    if flux and not flux_supported(model):
        return (f'ERROR: "{model}" isn\'t supported. Use flux-3-image, flux-3-image-klein, '
                "or a FLUX.2 model such as flux-2-pro.")

    usage = ""
    try:
        if flux:
            image, cost = generate_flux(model, flux_body(model, prompt, size, output_format), require_api_key("bfl"))
            if cost is not None:
                usage = f"\nFLUX cost: {cost} credits (${cost / 100:.2f})"
            # FLUX may answer in another format than asked (flux-3-image has no choice): convert
            actual = image_format(image)
            if actual and actual != output_format:
                image = convert_image(image, output_format)
        else:
            result = client().images.generate(
                model=model,
                prompt=prompt,
                quality=quality,
                size=size,
                background=background,
                output_format=output_format,
                n=1,
            )
            image = base64.b64decode(result.data[0].b64_json)
            tokens = getattr(getattr(result, "usage", None), "total_tokens", None)
            if tokens:
                usage = f"\nOpenAI tokens used: {tokens}"
    except Exception as e:  # pass the real reason back to the client
        return f"ERROR ({type(e).__name__}): {e}"

    path = output_file(output_path, output_format, prompt)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image)
    except OSError as e:  # e.g. no permission, or a name Windows doesn't allow
        return f"ERROR: the image was generated but could not be saved to {path}: {e}"

    details = f"size: {size}" if flux else f"quality: {quality} | size: {size}"
    info = f"Saved: {path}\nModel: {model} | {details}{usage}"

    try:
        preview = preview_jpeg(image)
    except Exception as e:  # the file is saved; a missing preview shouldn't fail the call
        return info + f"\n(No preview: {e})"
    info += "\nPreview below (small JPEG; the saved file is full resolution)."
    return [info, Image(data=preview, format="jpeg")]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
