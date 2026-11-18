"""Tests for paths and API key loading. GitHub Actions runs these on Windows, macOS and Linux."""

import base64
import io
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image as PILImage

from openai_image_mcp import server


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake home folder, set the way each OS looks it up."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))  # macOS, Linux
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BFL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_OUTPUT_DIR", raising=False)
    config = tmp_path / "config"
    monkeypatch.setattr(server, "user_config_dir", lambda *a, **k: str(config / a[0]))
    monkeypatch.setattr(server, "_client", None)
    return home


# ---------- the OS's real folders (no fakes) ----------


def test_key_file_is_in_the_os_config_folder(monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    first = server.key_files()[0]
    if sys.platform == "win32":
        expected = Path(os.environ["APPDATA"]) / "openai" / "api_key"
    elif sys.platform == "darwin":
        expected = Path.home() / "Library" / "Application Support" / "openai" / "api_key"
    else:
        expected = Path.home() / ".config" / "openai" / "api_key"
    assert first == expected
    assert server.key_files()[-1] == Path.home() / ".config" / "openai" / "api_key"


def test_default_output_dir_is_the_pictures_folder(monkeypatch):
    monkeypatch.delenv("OPENAI_IMAGE_OUTPUT_DIR", raising=False)
    pictures = server.default_output_dir()
    assert pictures.is_absolute()
    if sys.platform == "darwin":
        assert pictures == Path.home() / "Pictures"


# ---------- API key ----------


def test_key_from_env_wins(home, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "  sk-env \n")
    (home / ".config" / "openai").mkdir(parents=True)
    (home / ".config" / "openai" / "api_key").write_text("sk-file")
    assert server.find_api_key() == "sk-env"


def test_key_from_os_config_folder(home):
    path = server.key_files()[0]
    path.parent.mkdir(parents=True)
    path.write_text("sk-config\n")
    assert server.find_api_key() == "sk-config"


def test_key_from_dot_config_on_every_os(home):
    path = home / ".config" / "openai" / "api_key"
    path.parent.mkdir(parents=True)
    path.write_text("sk-dotconfig")
    assert server.find_api_key() == "sk-dotconfig"


@pytest.mark.parametrize(
    "data",
    [
        "sk-utf16\r\n".encode("utf-16"),  # Windows PowerShell 5: "sk-..." > api_key
        b"\xef\xbb\xbfsk-utf16\r\n",  # UTF-8 with BOM (Notepad)
        b"sk-utf16\r\n",  # Windows line ending
    ],
)
def test_key_file_encodings(home, data):
    path = server.key_files()[0]
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    assert server.find_api_key() == "sk-utf16"


def test_missing_key_lists_where_to_put_it(home):
    with pytest.raises(RuntimeError) as err:
        server.client()
    for path in server.key_files():
        assert str(path) in str(err.value)


# ---------- output paths ----------


@pytest.fixture
def out(home, tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("OPENAI_IMAGE_OUTPUT_DIR", str(out))
    return out


def test_no_path_uses_default_folder(out):
    path = server.output_file(None, "png", "A red logo!")
    assert path.parent == out
    assert path.name.endswith("-a-red-logo.png")


def test_absolute_path(out, tmp_path):
    target = tmp_path / "site" / "hero.webp"
    assert server.output_file(str(target), "webp", "x") == target


def test_relative_path_goes_inside_default_folder(out):
    assert server.output_file("logos/logo.png", "png", "x") == out / "logos" / "logo.png"


def test_tilde_is_expanded(out, home):
    assert server.output_file("~/Desktop/a.png", "png", "x") == home / "Desktop" / "a.png"


def test_env_var_is_expanded(out, home, monkeypatch):
    monkeypatch.setenv("MY_IMAGES", str(home / "imgs"))
    var = "%MY_IMAGES%" if sys.platform == "win32" else "$MY_IMAGES"
    assert server.output_file(f"{var}/a.png", "png", "x") == home / "imgs" / "a.png"


def test_existing_folder_gets_auto_name(out, tmp_path):
    folder = tmp_path / "existing"
    folder.mkdir()
    path = server.output_file(str(folder), "png", "cat")
    assert path.parent == folder and path.name.endswith("-cat.png")


def test_trailing_separator_means_folder(out, tmp_path):
    sep = "\\" if sys.platform == "win32" else "/"
    path = server.output_file(str(tmp_path / "new") + sep, "jpeg", "dog")
    assert path.parent == tmp_path / "new" and path.name.endswith("-dog.jpeg")


def test_extension_is_added(out, tmp_path):
    assert server.output_file(str(tmp_path / "hero"), "webp", "x") == tmp_path / "hero.webp"
    assert server.output_file(str(tmp_path / "hero.v2"), "png", "x") == tmp_path / "hero.v2.png"


def test_env_output_dir_with_tilde(home, monkeypatch):
    monkeypatch.setenv("OPENAI_IMAGE_OUTPUT_DIR", "~/Generated")
    assert server.default_output_dir() == home / "Generated"


# ---------- full tool call with a fake OpenAI client ----------


def fake_client(image: bytes):
    return SimpleNamespace(
        images=SimpleNamespace(
            generate=lambda **kw: SimpleNamespace(
                data=[SimpleNamespace(b64_json=base64.b64encode(image).decode())], usage=None
            )
        )
    )


def png_bytes(size, mode="RGB", color=(200, 30, 30)):
    buf = io.BytesIO()
    PILImage.new(mode, size, color).save(buf, "PNG")
    return buf.getvalue()


def test_generate_image_saves_file_and_returns_preview(out, monkeypatch):
    png = png_bytes((1536, 1024))
    monkeypatch.setattr(server, "client", lambda: fake_client(png))
    text, preview = server.generate_image("a test image", output_path="sub/test")
    saved = out / "sub" / "test.png"
    assert text.startswith(f"Saved: {saved}\nLink: {saved.absolute().as_uri()}\n")
    assert saved.read_bytes() == png  # full resolution on disk

    content = preview.to_image_content()
    assert content.mime_type == "image/jpeg"
    with PILImage.open(io.BytesIO(base64.b64decode(content.data))) as img:
        assert img.format == "JPEG" and img.size == (1024, 683)


def test_preview_of_transparent_image_is_jpeg():
    jpeg = server.preview_jpeg(png_bytes((1024, 1536), "RGBA", (0, 0, 0, 0)))
    with PILImage.open(io.BytesIO(jpeg)) as img:
        assert img.format == "JPEG" and img.size == (683, 1024)
        assert img.getpixel((10, 10)) == (255, 255, 255)  # transparent -> white


def test_unreadable_image_is_still_saved(out, monkeypatch):
    monkeypatch.setattr(server, "client", lambda: fake_client(b"not an image"))
    result = server.generate_image("x", output_path="broken")
    assert isinstance(result, str) and "No preview" in result
    assert (out / "broken.png").read_bytes() == b"not an image"


# ---------- the server starts and speaks MCP ----------


def test_server_lists_tool_over_stdio():
    # Like a real client: keep stdin open and wait for each reply. Closing stdin early
    # makes the server shut down, sometimes before it answers (seen on macOS).
    proc = subprocess.Popen(
        [sys.executable, "-m", "openai_image_mcp.server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    lines = queue.Queue()
    # A thread, because select() doesn't work on pipes on Windows
    threading.Thread(target=lambda: [lines.put(l) for l in proc.stdout], daemon=True).start()

    def send(message):
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    def reply(id):
        while True:
            message = json.loads(lines.get(timeout=30))
            if message.get("id") == id:
                return message

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"}}})
        reply(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = reply(2)["result"]["tools"]
        assert [t["name"] for t in tools] == ["generate_image"]
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        proc.stdout.close()
        proc.stderr.close()


def test_tool_points_at_the_image_view():
    # MCP Apps: hosts that support it render this view inline with the image
    import asyncio

    tool = asyncio.run(server.mcp.list_tools())[0]
    assert tool.meta["ui"]["resourceUri"] == server.VIEW_URI
    [view] = asyncio.run(server.mcp.read_resource(server.VIEW_URI))
    assert view.mime_type == "text/html;profile=mcp-app"
    assert "ui/notifications/tool-result" in view.content


# ---------- FLUX with a fake Black Forest Labs API ----------


class FakeResponse:
    def __init__(self, status_code, body=None, content=b""):
        self.status_code = status_code
        self._body = body
        self.content = content
        self.text = json.dumps(body)

    def json(self):
        if self._body is None:
            raise ValueError("no JSON")
        return self._body


class FakeBfl:
    """Answers submit, then `pending` polls, then Ready with a download URL."""

    def __init__(self, image=None, pending=1, status=None, submit_status=None):
        self.image = image or png_bytes((64, 64))
        self.pending, self.status, self.submit_status = pending, status, submit_status
        self.calls = []
        self.polls = 0

    def __call__(self):
        return self  # stands in for server._http()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, headers=None, json=None):
        self.calls.append(("POST", url, headers, json))
        if self.submit_status:
            return FakeResponse(self.submit_status, {"detail": "nope"})
        return FakeResponse(200, {"id": "t1", "polling_url": "https://api.eu.bfl.ai/v1/get_result?id=t1", "cost": 4.8})

    def get(self, url, headers=None):
        self.calls.append(("GET", url, headers, None))
        if "get_result" in url:
            self.polls += 1
            if self.polls <= self.pending:
                return FakeResponse(200, {"id": "t1", "status": "Pending" if self.polls == 1 else "Generating"})
            if self.status:
                return FakeResponse(503, {"id": "t1", "status": self.status})
            return FakeResponse(200, {"id": "t1", "status": "Ready", "result": {"sample": "https://delivery.eu.bfl.ai/x.png"}})
        return FakeResponse(200, content=self.image)


@pytest.fixture
def bfl(out, monkeypatch):
    monkeypatch.setenv("BFL_API_KEY", "bfl-test-key")
    monkeypatch.setattr(server.time, "sleep", lambda s: None)
    fake = FakeBfl()
    monkeypatch.setattr(server, "_http", fake)
    return fake


def test_flux_is_the_default_with_only_a_flux_key(bfl, monkeypatch):
    assert server.default_model() == "flux-3-image"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert server.default_model() == "gpt-image-2"


def test_flux_submits_polls_downloads_and_saves(bfl, out):
    bfl.pending = 2
    text, preview = server.generate_image("a cat", size="1536x1024", output_path="flux/cat")
    method, url, headers, body = bfl.calls[0]
    assert (method, url) == ("POST", "https://api.bfl.ai/v1/flux-3-image")
    assert headers["x-key"] == "bfl-test-key"
    assert body == {"prompt": "a cat", "width": 1536, "height": 1024}  # flux-3-image takes no output_format
    polls = [c for c in bfl.calls if "get_result" in c[1]]
    assert len(polls) == 3 and all(c[1].startswith("https://api.eu.bfl.ai") for c in polls)
    assert "FLUX cost: 4.8 credits ($0.05)" in text and "quality" not in text
    assert server.image_format((out / "flux" / "cat.png").read_bytes()) == "png"
    assert preview.to_image_content().mime_type == "image/jpeg"


def test_flux_result_is_converted_to_the_format_asked_for(bfl, out):
    server.generate_image("x", model="flux-3-image", output_format="webp", output_path="conv")
    assert server.image_format((out / "conv.webp").read_bytes()) == "webp"


def test_flux_bodies_per_model():
    assert server.flux_body("flux-2-pro", "x", "1024x1024", "webp")["output_format"] == "webp"
    assert server.flux_body("flux-3-image-klein", "x", "1024x1024", "png")["output_format"] == "png"
    assert "output_format" not in server.flux_body("flux-3-image", "x", "1024x1024", "png")


def test_flux_errors_are_clear(bfl, monkeypatch):
    monkeypatch.setattr(server, "_http", FakeBfl(status="Content Moderated"))
    assert "Content Moderated" in server.generate_image("x", model="flux-3-image")
    monkeypatch.setattr(server, "_http", FakeBfl(submit_status=402))
    assert "not enough credits" in server.generate_image("x", model="flux-3-image")
    assert "transparent" in server.generate_image("x", model="flux-3-image", background="transparent")
    assert "isn't supported" in server.generate_image("x", model="flux-pro-1.1")


def test_missing_flux_key_says_where_to_put_it(bfl, monkeypatch):
    monkeypatch.delenv("BFL_API_KEY")
    text = server.generate_image("x", model="flux-3-image")
    assert text.startswith("ERROR") and "BFL_API_KEY" in text
    for path in server.key_files("bfl"):
        assert str(path) in text
