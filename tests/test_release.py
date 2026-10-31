"""`scripts/release.py`, cutting a release against a local bare repository: it
refuses what is off, and tags and pushes only on the owner's word."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from tests.conftest import git

ROOT = Path(__file__).resolve().parent.parent


def release(source: Path, version: str, answer: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, source / "scripts" / "release.py", version],
        cwd=source,
        input=answer,
        capture_output=True,
        text=True,
    )


def test_a_release_is_tagged_and_pushed_only_when_everything_holds_and_the_owner_says_yes(
    tmp_path: Path,
) -> None:
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    source = tmp_path / "nock"
    (source / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "release.py", source / "scripts" / "release.py")
    (source / "pyproject.toml").write_text('[project]\nname = "nock"\nversion = "1.2.0"\n')
    git(source, "init", "-q", "-b", "main")
    git(source, "add", "-A")
    git(source, "commit", "-q", "-m", "nock 1.2.0")
    git(source, "remote", "add", "origin", str(origin))
    git(source, "push", "-q", "origin", "main")

    refused = release(source, "1.2")
    assert refused.returncode != 0
    assert "is not a version" in refused.stderr
    refused = release(source, "1.3.0")
    assert "pyproject.toml declares 1.2.0, not 1.3.0" in refused.stderr

    (source / "notes.txt").write_text("unfinished\n")
    refused = release(source, "1.2.0")
    assert "uncommitted changes" in refused.stderr
    (source / "notes.txt").unlink()

    declined = release(source, "1.2.0", "n\n")
    assert declined.returncode == 0
    assert "Tag" in declined.stdout and "v1.2.0" in declined.stdout
    assert "nothing tagged or pushed" in declined.stdout
    assert not git(source, "tag")
    assert not git(origin, "tag")

    accepted = release(source, "1.2.0", "y\n")
    assert accepted.returncode == 0, accepted.stderr
    assert "pushed v1.2.0 to origin" in accepted.stdout
    assert git(origin, "tag") == "v1.2.0"
    assert git(origin, "cat-file", "-t", "v1.2.0") == "tag"
    assert git(origin, "rev-parse", "v1.2.0^{commit}") == git(source, "rev-parse", "HEAD")

    refused = release(source, "1.2.0", "y\n")
    assert "tag v1.2.0 already exists here" in refused.stderr
    git(source, "tag", "--delete", "v1.2.0")
    refused = release(source, "1.2.0", "y\n")
    assert "tag v1.2.0 already exists on origin" in refused.stderr
    assert not git(source, "tag")
