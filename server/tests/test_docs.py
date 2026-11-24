"""nock's hosted docs on api.nock.dev, under real uvicorn on real Postgres: what `POST /docs` keeps and
refuses, which bundle `GET /docs/{cli}` serves, and the update path end to end, the real nock CLI asking
the real server: a newer bundle shown, an older, unfit or wrongly signed one never, the kept one while
the server is unreachable, the asks an hour apart, and `NOCK_DOCS=bundled`; then the publish script."""

import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from nock import hosted, signing
from nock.docs import DOCS, files
from nock.project import Project
from nock.setup import Installer

from tests.conftest import DOCS_KEY, DOCS_SEED, Api, Clock

OTHER_SEED = bytes(range(1, 33))
OTHER_KEY = base64.b64encode(signing.public_key(OTHER_SEED)).decode()
MARK = "This article came from the hosted bundle."
ROOT = Path(__file__).resolve().parents[2]


def changed(article: str = MARK) -> dict[str, str]:
    """nock's docs with the `run` term's article replaced."""
    texts = files(DOCS)
    front, _, _ = texts["run.md"].partition("\n---\n")
    texts["run.md"] = f"{front}\n---\n\n{article}\n"
    return texts


def bundle(
    version: int | None = None, min_cli: str = "0.1.0", seed: bytes = DOCS_SEED, article: str = MARK
) -> dict[str, Any]:
    stamp = int(time.time()) + 86400 if version is None else version
    return hosted.build(changed(article), stamp, min_cli, seed)


def raw(api: Api, path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(api.address + path, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_a_published_bundle_is_kept_for_its_minimum_and_served_as_sent(api: Api) -> None:
    first = bundle(version=5)
    assert api.post("/docs", first) == (201, {"min_cli": "0.1.0", "version": 5})
    status, body = raw(api, "/docs/0.3.0")
    assert status == 200 and json.loads(body) == first
    assert hosted.verified(json.loads(body), signing.public_key(DOCS_SEED)) is not None
    assert api.post("/docs", bundle(version=5)) == (201, {"min_cli": "0.1.0", "version": 5})
    assert api.post("/docs", bundle(version=7, article="Seven."))[0] == 201
    status, answer = api.post("/docs", bundle(version=6))
    assert status == 409 and "newer" in answer["error"]
    assert "Seven." in json.loads(raw(api, "/docs/0.3.0")[1])["docs"]["run.md"]


def test_the_newest_bundle_the_version_fits_is_served(api: Api) -> None:
    for version, min_cli in ((5, "0.1.0"), (10, "0.2.0"), (20, "9.0.0"), (8, "0.10.0")):
        assert api.post("/docs", bundle(version=version, min_cli=min_cli))[0] == 201
    served = {
        cli: json.loads(json.loads(raw(api, f"/docs/{cli}")[1])["manifest"])["version"]
        for cli in ("0.1.5", "0.3.0", "0.10.0", "9.0.0")
    }
    assert served == {"0.1.5": 5, "0.3.0": 10, "0.10.0": 10, "9.0.0": 20}
    assert raw(api, "/docs/0.0.9")[0] == 404
    assert raw(api, "/docs/latest")[0] == 400


def test_nothing_is_served_before_a_publish(api: Api) -> None:
    status, body = raw(api, "/docs/1.0.0")
    assert status == 404 and json.loads(body) == {"error": "no docs for nock 1.0.0"}


def resigned(good: dict[str, Any], **changes: Any) -> dict[str, Any]:
    manifest = json.dumps({**json.loads(good["manifest"]), **changes})
    signature = base64.b64encode(signing.sign(DOCS_SEED, manifest.encode())).decode()
    return {**good, "manifest": manifest, "signature": signature}


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda good: {**good, "signature": bundle(seed=OTHER_SEED)["signature"]}, "signature"),
        (lambda good: {**good, "signature": "not base64!"}, "signature"),
        (lambda good: {**good, "docs": {**good["docs"], "run.md": "changed"}}, "hash"),
        (lambda good: {**good, "docs": {**good["docs"], "extra.md": "x"}}, "files"),
        (lambda good: {**good, "kind": "x"}, "exactly"),
        (lambda good: resigned(good, format=2), "format"),
        (lambda good: resigned(good, version=-1), "version"),
        (lambda good: resigned(good, version="5"), "version"),
        (lambda good: resigned(good, min_cli="1.0"), "min_cli"),
        (lambda good: [good], "exactly"),
    ],
)
def test_a_bundle_not_whole_or_not_signed_with_the_key_is_refused(
    api: Api, change: Any, reason: str
) -> None:
    status, answer = api.post("/docs", change(bundle(version=5)))
    assert status == 400 and reason in answer["error"], answer
    assert raw(api, "/docs/1.0.0")[0] == 404


def git(directory: Path, *arguments: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(["git", *arguments], cwd=directory, check=True, capture_output=True, env=env)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api: Api) -> Iterator[Project]:
    """A repository with nock installed and committed, its docs asked of the test server."""
    for name in list(os.environ):
        if name.startswith(("CLAUDE", "NOCK_", "GIT_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")
    monkeypatch.setenv(hosted.KEY_VARIABLE, DOCS_KEY)
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    Installer(root).install()
    local = root / ".nock" / "local"
    local.mkdir(exist_ok=True)
    (local / "config.toml").write_text(
        f'[upgrade]\ncheck = false\n[endpoints]\ndocs = "{api.address}/docs"\n'
    )
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Add nock")
    yield Project.discover(root)


def article(project: Project) -> str:
    """`nock docs run` as an agent runs it: the vendored CLI, its own process."""
    done = subprocess.run(
        [str(project.root / ".nock" / "nock"), "docs", "run"],
        cwd=project.root,
        capture_output=True,
        text=True,
        env={**os.environ, "NOCK_PYTHON": sys.executable},
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def kept(project: Project) -> dict[str, Any]:
    return json.loads((project.local / hosted.CACHE).read_text())


def asked_long_ago(project: Project) -> None:
    (project.local / hosted.CACHE).write_text(json.dumps({**kept(project), "checked": 0}))


def test_a_newer_bundle_is_shown_and_kept(project: Project, api: Api) -> None:
    assert MARK not in article(project)
    asked_long_ago(project)
    assert api.post("/docs", bundle())[0] == 201
    assert MARK in article(project)
    assert hosted.verified(kept(project)["bundle"], signing.public_key(DOCS_SEED)) is not None


def test_an_older_bundle_than_the_shipped_docs_is_not_shown(project: Project, api: Api) -> None:
    assert api.post("/docs", bundle(version=1))[0] == 201
    assert MARK not in article(project)
    assert kept(project)["bundle"] is not None


def test_a_bundle_for_a_newer_nock_is_not_shown(project: Project, api: Api) -> None:
    assert api.post("/docs", bundle(min_cli="99.0.0"))[0] == 201
    assert MARK not in article(project)
    assert kept(project)["bundle"] is None


def test_a_bundle_signed_with_another_key_is_never_shown(
    project: Project, database_url: str, clock: Clock, api: Api
) -> None:
    impostor = Api(database_url, clock, api.limit, docs_key=OTHER_KEY)
    try:
        assert impostor.post("/docs", bundle(seed=OTHER_SEED))[0] == 201
        local = project.local / "config.toml"
        local.write_text(local.read_text().replace(api.address, impostor.address))
        assert MARK not in article(project)
        assert kept(project)["bundle"] is None
    finally:
        impostor.stop()


def test_offline_the_kept_bundle_is_shown_and_asks_are_an_hour_apart(
    project: Project, api: Api
) -> None:
    assert api.post("/docs", bundle(article="First."))[0] == 201
    assert "First." in article(project)
    assert api.post("/docs", bundle(version=int(time.time()) + 90000, article="Second."))[0] == 201
    assert "First." in article(project), "asked within the hour: not asked again"
    asked_long_ago(project)
    assert "Second." in article(project)
    api.stop()
    asked_long_ago(project)
    started = time.monotonic()
    assert "Second." in article(project)
    assert time.monotonic() - started < 20
    assert kept(project)["checked"] > 0


def test_bundled_docs_are_the_shipped_ones_and_ask_nothing(
    project: Project, api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert api.post("/docs", bundle())[0] == 201
    monkeypatch.setenv(hosted.MODE_VARIABLE, hosted.BUNDLED)
    assert MARK not in article(project)
    assert not (project.local / hosted.CACHE).exists()


def test_the_publish_script_sends_the_committed_docs_only_on_a_yes(
    tmp_path: Path, project: Project, api: Api
) -> None:
    source = tmp_path / "nock"
    shutil.copytree(ROOT / "scripts", source / "scripts")
    shutil.copytree(ROOT / "src" / "nock", source / "src" / "nock")
    run = source / "src" / "nock" / "docs" / "run.md"
    front, _, _ = run.read_text().partition("\n---\n")
    run.write_text(f"{front}\n---\n\n{MARK}\n")
    environment = {
        **os.environ,
        "NOCK_DOCS_SIGNING_KEY": base64.b64encode(DOCS_SEED).decode(),
        "GIT_COMMITTER_DATE": f"{int(time.time()) + 86400} +0000",
    }
    git(source, "init", "-q", "-b", "main")
    git(source, "add", "-A")
    git(source, "commit", "-q", "-m", "nock", env=environment)

    def publish(
        *arguments: str, answer: str = "", **extra: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(source / "scripts" / "publish_docs.py"), *arguments],
            cwd=source,
            input=answer,
            capture_output=True,
            text=True,
            env={**environment, **extra},
        )

    server = ("--server", api.address)
    refused = publish(*server, "--min-cli", "1.0")
    assert refused.returncode != 0 and "is not a version" in refused.stderr
    refused = publish(*server, NOCK_DOCS_SIGNING_KEY=base64.b64encode(OTHER_SEED).decode())
    assert refused.returncode != 0 and "not the private half" in refused.stderr
    run.write_text(run.read_text() + "\nUnfinished.\n")
    refused = publish(*server)
    assert refused.returncode != 0 and "uncommitted changes" in refused.stderr
    git(source, "checkout", "--", ".")
    declined = publish(*server, "--min-cli", "0.1.0", answer="n\n")
    assert declined.returncode == 0 and "nothing sent" in declined.stdout
    assert raw(api, "/docs/0.3.0")[0] == 404
    done = publish(*server, "--min-cli", "0.1.0", answer="y\n")
    assert done.returncode == 0, done.stderr
    assert "for nock 0.1.0 and newer" in done.stdout
    assert MARK in article(project)
