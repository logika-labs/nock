"""`scripts/release.py`, releasing against a local bare repository: it
refuses what is off, and bumps, commits, tags and pushes only on the owner's
word."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

from tests.conftest import git

ROOT = Path(__file__).resolve().parent.parent
LOCK = """[[package]]
name = "iniconfig"
version = "2.3.1"

[[package]]
name = "nock"
version = "1.2.0"
source = { editable = "." }
"""


def release(source: Path, *arguments: str, answer: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, source / "scripts" / "release.py", *arguments],
        cwd=source,
        input=answer,
        capture_output=True,
        text=True,
    )


def test_a_release_bumps_tags_and_pushes_only_when_everything_holds_and_the_owner_says_yes(
    tmp_path: Path,
) -> None:
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    source = tmp_path / "nock"
    (source / "scripts").mkdir(parents=True)
    (source / "src" / "nock").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "release.py", source / "scripts" / "release.py")
    (source / "pyproject.toml").write_text('[project]\nname = "nock"\nversion = "1.2.0"\n')
    (source / "src" / "nock" / "releases.py").write_text('VERSION = "1.2.0"\nNAME = "nock"\n')
    (source / "uv.lock").write_text(LOCK)
    git(source, "init", "-q", "-b", "main")
    git(source, "add", "-A")
    git(source, "commit", "-q", "-m", "nock 1.2.0")
    git(source, "remote", "add", "origin", str(origin))
    git(source, "push", "-q", "origin", "main")

    refused = release(source, "1.2")
    assert refused.returncode != 0 and "is not a version" in refused.stderr
    refused = release(source, "1.1.9")
    assert "1.1.9 is older than the 1.2.0 pyproject.toml declares" in refused.stderr
    (source / "notes.txt").write_text("unfinished\n")
    refused = release(source)
    assert "uncommitted changes" in refused.stderr
    (source / "notes.txt").unlink()

    declined = release(source, answer="n\n")
    assert declined.returncode == 0
    assert "Release nock 1.2.1: bump 1.2.0 to 1.2.1 in a commit, tag it v1.2.1" in declined.stdout
    assert "nothing changed, tagged or pushed" in declined.stdout
    assert not git(source, "tag") and not git(origin, "tag")
    assert git(source, "status", "--porcelain") == ""

    accepted = release(source, answer="y\n")
    assert accepted.returncode == 0, accepted.stderr
    assert "pushed main and v1.2.1 to origin" in accepted.stdout
    assert git(source, "log", "-1", "--format=%s") == "nock 1.2.1"
    assert 'version = "1.2.1"' in (source / "pyproject.toml").read_text()
    assert (source / "src" / "nock" / "releases.py").read_text().startswith('VERSION = "1.2.1"')
    assert (source / "uv.lock").read_text() == LOCK.replace('"1.2.0"', '"1.2.1"')
    assert git(origin, "tag") == "v1.2.1" and git(origin, "cat-file", "-t", "v1.2.1") == "tag"
    assert git(origin, "rev-parse", "v1.2.1^{commit}") == git(source, "rev-parse", "HEAD")
    assert git(origin, "rev-parse", "main") == git(source, "rev-parse", "HEAD")

    refused = release(source, "1.2.1", answer="y\n")
    assert "tag v1.2.1 already exists here" in refused.stderr
    git(source, "tag", "--delete", "v1.2.1")
    refused = release(source, "1.2.1", answer="y\n")
    assert "tag v1.2.1 already exists on origin" in refused.stderr

    named = release(source, "2.0.0", answer="y\n")
    assert named.returncode == 0, named.stderr
    assert git(origin, "tag").splitlines() == ["v1.2.1", "v2.0.0"]


def test_every_file_the_release_bumps_declares_this_version_once() -> None:
    spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    declared = module.DECLARED
    pyproject = (ROOT / "pyproject.toml").read_text()
    for name, pattern in declared.items():
        found = pattern.findall((ROOT / name).read_text())
        assert len(found) == 1 and f'version = "{found[0][1]}"' in pyproject, name
