"""Bounded Capture adapters for staged local text and allowlisted public web pages."""

from __future__ import annotations

from html.parser import HTMLParser
import ipaddress
from pathlib import Path
import socket
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .profile import Profile


class CaptureInputError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def _resolve_public(host: str) -> list[str]:
    return sorted({entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})


class CaptureInputs:
    def __init__(self, profile: Profile, *, allowed_hosts: Iterable[str] = (),
                 resolver: Callable[[str], list[str]] | None = None,
                 opener: Callable[..., Any] | None = None, max_bytes: int = 1_000_000) -> None:
        self.profile = profile
        self.allowed_hosts = {host.lower().strip() for host in allowed_hosts}
        self.resolver = resolver or _resolve_public
        self.opener = opener or urlopen
        self.max_bytes = max_bytes

    def read_file(self, relative_path: str) -> dict[str, str]:
        root = (self.profile.root / "imports").resolve()
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise CaptureInputError("file_outside_imports_or_missing")
        if path.suffix.lower() not in {".txt", ".md"}:
            raise CaptureInputError("file_type_unsupported")
        if path.stat().st_size > self.max_bytes:
            raise CaptureInputError("file_too_large")
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise CaptureInputError("file_read_failed") from None
        if not content.strip():
            raise CaptureInputError("file_empty")
        return {"source": "file", "title": path.stem, "content": content,
                "source_ref": path.relative_to(root).as_posix()}

    def read_url(self, url: str) -> dict[str, str]:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or not host or parsed.username or parsed.password
                or parsed.port not in (None, 443) or host not in self.allowed_hosts):
            raise CaptureInputError("web_source_not_allowed")
        try:
            addresses = self.resolver(host)
            if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
                raise CaptureInputError("web_source_not_public")
            request = Request(url, headers={"User-Agent": "YushuOS/0.1"}, method="GET")
            with self.opener(request, timeout=5) as response:
                final = urlsplit(response.geturl())
                if final.scheme != "https" or final.hostname != host:
                    raise CaptureInputError("web_redirect_not_allowed")
                content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].lower()
                if content_type not in {"text/html", "text/plain"}:
                    raise CaptureInputError("web_type_unsupported")
                body = response.read(self.max_bytes + 1)
                if len(body) > self.max_bytes:
                    raise CaptureInputError("web_too_large")
        except CaptureInputError:
            raise
        except Exception:
            raise CaptureInputError("web_fetch_failed") from None
        try:
            decoded = body.decode("utf-8")
        except UnicodeError:
            raise CaptureInputError("web_encoding_unsupported") from None
        if content_type == "text/html":
            parser = _TextParser()
            parser.feed(decoded)
            decoded = "\n".join(parser.parts)
        if not decoded.strip():
            raise CaptureInputError("web_empty")
        return {"source": "web", "title": host, "content": decoded, "source_ref": url}
