from io import BytesIO
from pathlib import Path

import pytest

from yushu_app.capture_inputs import CaptureInputError, CaptureInputs
from yushu_app.profile import Profile


def test_file_capture_stays_within_profile_imports_and_rejects_binary(tmp_path: Path):
    profile = Profile.initialize("test", home=tmp_path)
    imports = profile.root / "imports"
    imports.mkdir()
    (imports / "idea.md").write_text("一条想法", encoding="utf-8")
    reader = CaptureInputs(profile)
    result = reader.read_file("idea.md")
    assert result["source"] == "file"
    assert result["content"] == "一条想法"

    with pytest.raises(CaptureInputError):
        reader.read_file("../../outside.txt")
    with pytest.raises(CaptureInputError):
        reader.read_file("image.png")


def test_web_capture_requires_public_https_and_bounded_text(tmp_path: Path):
    profile = Profile.initialize("test", home=tmp_path)

    class Response:
        headers = {"Content-Type": "text/html"}

        def read(self, size):
            return b"<html><body><h1>Hello</h1><script>bad()</script></body></html>"

        def geturl(self):
            return "https://example.com/note"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    reader = CaptureInputs(profile, allowed_hosts={"example.com"},
                           resolver=lambda host: ["93.184.215.14"],
                           opener=lambda request, timeout: Response())
    result = reader.read_url("https://example.com/note")
    assert result["source"] == "web"
    assert "Hello" in result["content"]
    assert "bad()" not in result["content"]
    with pytest.raises(CaptureInputError):
        reader.read_url("http://example.com/note")
    with pytest.raises(CaptureInputError):
        reader.read_url("https://127.0.0.1/secret")
