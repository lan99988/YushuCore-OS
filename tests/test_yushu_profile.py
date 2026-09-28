from __future__ import annotations

from pathlib import Path

import pytest

from yushu_app.profile import Profile, ProfileError


def test_profile_initializes_outside_repository_and_reopens(tmp_path: Path):
    profile = Profile.initialize("default", home=tmp_path)

    assert profile.root == tmp_path / "profiles" / "default"
    assert profile.database_path.is_file()
    assert profile.authority("task") == "local"
    assert profile.authority("calendar") == "local"
    assert profile.authority("knowledge") == "ima"
    assert Profile.open("default", home=tmp_path).root == profile.root


def test_profile_rejects_path_traversal(tmp_path: Path):
    with pytest.raises(ProfileError, match="profile_id"):
        Profile.initialize("../outside", home=tmp_path)


def test_profile_does_not_silently_change_authority(tmp_path: Path):
    Profile.initialize("owner", home=tmp_path, authorities={"task": "feishu"})

    with pytest.raises(ProfileError, match="already exists"):
        Profile.initialize("owner", home=tmp_path, authorities={"task": "local"})

    assert Profile.open("owner", home=tmp_path).authority("task") == "feishu"
