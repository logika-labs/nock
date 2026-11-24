"""Hosted docs: Ed25519 held to RFC 8032's vectors; a bundle shown only whole,
signed with nock's key, fit for this nock and newer than its own docs; never
the network under `NOCK_DOCS=bundled`, and an offline machine answered at once
from what it has. The update path against the real api.nock.dev server is in
`server/tests/test_docs.py`."""

from __future__ import annotations

import base64
import json
import socket
import time
from pathlib import Path
from typing import Any

import pytest

from nock import hosted, signing
from nock.docs import DOCS, files
from nock.project import Project

from .conftest import nock

# RFC 8032 §7.1, TEST 1 to 3: private seed, public key, message, signature.
VECTORS = [
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
        "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
    (
        "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "af82",
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
        "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
    ),
]
SEED = bytes(range(32))
OTHER_SEED = bytes(range(1, 33))
MARK = "This article came from the hosted bundle."


@pytest.mark.parametrize(("seed", "public", "message", "signature"), VECTORS)
def test_ed25519_holds_to_rfc_8032(seed: str, public: str, message: str, signature: str) -> None:
    secret, key, text = bytes.fromhex(seed), bytes.fromhex(public), bytes.fromhex(message)
    assert signing.public_key(secret) == key
    assert signing.sign(secret, text).hex() == signature
    assert signing.verify(key, text, bytes.fromhex(signature))
    assert not signing.verify(key, text + b"!", bytes.fromhex(signature))
    forged = bytearray(bytes.fromhex(signature))
    forged[40] ^= 1
    assert not signing.verify(key, text, bytes(forged))


def changed(article: str = MARK) -> dict[str, str]:
    """nock's docs with the `run` term's article replaced."""
    texts = files(DOCS)
    front, _, _ = texts["run.md"].partition("\n---\n")
    texts["run.md"] = f"{front}\n---\n\n{article}\n"
    return texts


def bundle(
    version: int | None = None, min_cli: str = "0.1.0", seed: bytes = SEED
) -> dict[str, Any]:
    stamp = int(time.time()) + 3600 if version is None else version
    return hosted.build(changed(), stamp, min_cli, seed)


def test_a_bundle_verifies_only_whole_and_signed_with_the_key() -> None:
    key = signing.public_key(SEED)
    good = bundle(version=1234)
    assert hosted.verified(good, key) == hosted.Manifest(1234, "0.1.0")
    assert hosted.verified(good, signing.public_key(OTHER_SEED)) is None
    tampered_doc = {**good, "docs": {**good["docs"], "run.md": good["docs"]["run.md"] + "!"}}
    assert hosted.verified(tampered_doc, key) is None
    extra = {**good, "docs": {**good["docs"], "more.md": "x"}}
    assert hosted.verified(extra, key) is None
    tampered_manifest = {**good, "manifest": good["manifest"].replace("1234", "9999")}
    assert hosted.verified(tampered_manifest, key) is None
    for wrong in ({"format": 2}, {"version": -1}, {"version": "1"}, {"min_cli": "1.0"}):
        manifest = {**json.loads(good["manifest"]), **wrong}
        text = json.dumps(manifest)
        resigned = {
            **good,
            "manifest": text,
            "signature": base64.b64encode(signing.sign(SEED, text.encode())).decode(),
        }
        assert hosted.verified(resigned, key) is None, wrong
    assert hosted.verified({**good, "signature": "not base64!"}, key) is None
    assert hosted.verified("a bundle", key) is None


def test_a_bundle_fits_this_nock_by_its_minimum() -> None:
    assert hosted.fits("0.1.0", "0.3.0")
    assert hosted.fits("0.3.0", "0.3.0")
    assert not hosted.fits("1.0.0", "0.3.0")
    assert not hosted.fits("0.10.0", "0.9.9")


def keep(project: Project, kept: dict[str, Any]) -> None:
    (project.local / hosted.CACHE).write_text(json.dumps(kept))


def run_article(project: Project) -> str:
    done = nock(project.root, "docs", "run")
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_a_kept_bundle_is_shown_unless_the_docs_are_forced_bundled(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(hosted.KEY_VARIABLE, base64.b64encode(signing.public_key(SEED)).decode())
    keep(project, {"checked": int(time.time()), "bundle": bundle()})
    assert MARK in run_article(project)
    monkeypatch.setenv(hosted.MODE_VARIABLE, hosted.BUNDLED)
    assert MARK not in run_article(project)


def test_a_kept_bundle_is_not_shown_when_older_unfit_or_not_ours(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(hosted.KEY_VARIABLE, base64.b64encode(signing.public_key(SEED)).decode())
    now = int(time.time())
    for kept in (bundle(version=1), bundle(min_cli="99.0.0"), bundle(seed=OTHER_SEED)):
        keep(project, {"checked": now, "bundle": kept})
        assert MARK not in run_article(project)


def test_offline_the_docs_answer_at_once_and_the_ask_waits_an_hour(project: Project) -> None:
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()
    local = project.local / "config.toml"
    local.write_text(local.read_text() + f'[endpoints]\ndocs = "http://127.0.0.1:{port}/docs"\n')
    started = time.monotonic()
    article = run_article(project)
    assert time.monotonic() - started < 10
    assert MARK not in article and article.strip()
    kept = json.loads((project.local / hosted.CACHE).read_text())
    assert kept["bundle"] is None
    assert abs(kept["checked"] - time.time()) < 60


def test_bundled_docs_never_ask_the_server(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(hosted.MODE_VARIABLE, hosted.BUNDLED)
    assert run_article(project).strip()
    assert not (project.local / hosted.CACHE).exists()


def test_a_bundle_holds_every_docs_file_by_its_path() -> None:
    texts = files(DOCS)
    assert "run.md" in texts and "briefs/work.md" in texts and "guides/guide.cli.md" in texts
    assert all(not Path(path).is_absolute() for path in texts)
