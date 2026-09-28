from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Mapping


_PROFILE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_DEFAULT_AUTHORITIES = {"task": "local", "calendar": "local", "knowledge": "ima"}
_ALLOWED_AUTHORITIES = {
    "task": {"local", "feishu"},
    "calendar": {"local", "feishu"},
    "knowledge": {"ima"},
}


class ProfileError(ValueError):
    """Invalid or conflicting local profile configuration."""


def _home_path(home: str | Path | None) -> Path:
    if home is not None:
        return Path(home).resolve()
    configured = os.environ.get("YUSHU_HOME", "").strip()
    if configured:
        return Path(configured).resolve()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return (base / "YushuOS").resolve()


def _profile_root(profile_id: str, home: str | Path | None) -> Path:
    if not isinstance(profile_id, str) or not _PROFILE_ID.fullmatch(profile_id):
        raise ProfileError("profile_id must be a simple identifier")
    return _home_path(home) / "profiles" / profile_id


def _authorities(overrides: Mapping[str, str] | None) -> dict[str, str]:
    selected = dict(_DEFAULT_AUTHORITIES)
    for domain, provider in (overrides or {}).items():
        if domain not in _ALLOWED_AUTHORITIES or provider not in _ALLOWED_AUTHORITIES[domain]:
            raise ProfileError("unsupported domain authority")
        selected[domain] = provider
    return selected


@dataclass(frozen=True)
class Profile:
    profile_id: str
    root: Path
    authorities: Mapping[str, str]

    @property
    def database_path(self) -> Path:
        return self.root / "yushu.sqlite3"

    def authority(self, domain: str) -> str:
        try:
            return self.authorities[domain]
        except KeyError as exc:
            raise ProfileError("unknown authority domain") from exc

    @classmethod
    def initialize(
        cls,
        profile_id: str,
        *,
        home: str | Path | None = None,
        authorities: Mapping[str, str] | None = None,
    ) -> "Profile":
        root = _profile_root(profile_id, home)
        selected = _authorities(authorities)
        config_path = root / "profile.json"
        if config_path.exists():
            existing = cls.open(profile_id, home=home)
            if dict(existing.authorities) != selected:
                raise ProfileError("profile already exists with different authorities")
            return existing
        root.mkdir(parents=True, exist_ok=True)
        temporary = root / "profile.json.tmp"
        temporary.write_text(
            json.dumps({"schema_version": 1, "profile_id": profile_id, "authorities": selected}, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, config_path)
        with sqlite3.connect(root / "yushu.sqlite3") as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        return cls(profile_id, root, selected)

    @classmethod
    def open(cls, profile_id: str, *, home: str | Path | None = None) -> "Profile":
        root = _profile_root(profile_id, home)
        config_path = root / "profile.json"
        if not config_path.is_file():
            raise ProfileError("profile is not initialized")
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProfileError("profile configuration is invalid") from exc
        if payload.get("schema_version") != 1 or payload.get("profile_id") != profile_id:
            raise ProfileError("profile configuration is invalid")
        authorities = payload.get("authorities")
        if not isinstance(authorities, dict) or _authorities(authorities) != authorities:
            raise ProfileError("profile authorities are invalid")
        if not (root / "yushu.sqlite3").is_file():
            raise ProfileError("profile database is missing")
        return cls(profile_id, root, authorities)
