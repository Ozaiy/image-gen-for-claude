"""Tests for paths and API key loading. GitHub Actions runs these on Windows, macOS and Linux."""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from openai_image_mcp import server


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake home folder, set the way each OS looks it up."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))  # macOS, Linux
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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


def test_generate_image_saves_file(out, monkeypatch):
    png = b"\x89PNG\r\n\x1a\nfake"
    fake = SimpleNamespace(
        images=SimpleNamespace(
            generate=lambda **kw: SimpleNamespace(
                data=[SimpleNamespace(b64_json=base64.b64encode(png).decode())], usage=None
            )
        )
    )
    monkeypatch.setattr(server, "client", lambda: fake)
    result = server.generate_image("a test image", output_path="sub/test")
    saved = out / "sub" / "test.png"
    assert result.startswith(f"Saved: {saved}")
    assert saved.read_bytes() == png


# ---------- the server starts and speaks MCP ----------


def test_server_lists_tool_over_stdio():
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "openai_image_mcp.server"],
        input="".join(json.dumps(m) + "\n" for m in messages),
        capture_output=True, text=True, timeout=60,
    )
    replies = {r.get("id"): r for r in map(json.loads, proc.stdout.splitlines()) if r.get("id")}
    assert [t["name"] for t in replies[2]["result"]["tools"]] == ["generate_image"], proc.stderr
