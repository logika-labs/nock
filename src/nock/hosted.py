"""nock's docs as hosted on api.nock.dev, so they improve between releases: a
bundle is a signed manifest (its format, the docs' version — the Unix time of
the last commit to them — the oldest nock that may show them, a SHA-256 per
file) and the files themselves. `nock docs` asks for the newest bundle this
nock fits at most once an hour, with a short timeout, and keeps one that
verifies in `.nock/local/docs.json`; it shows the kept bundle instead of the
docs it shipped with while that verifies, fits and is newer than them.
`NOCK_DOCS=bundled` shows the shipped docs only. `scripts/publish_docs.py`
builds, signs and uploads a bundle."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock import signing
from nock.docs import DOCS, Docs, TermError
from nock.errors import PreconditionError
from nock.project import NOCK_DIRECTORY
from nock.releases import VERSION, parsed
from nock.utils import read_json, write_atomic

if TYPE_CHECKING:
    from nock.project import Project

FORMAT = 1
# The key every bundle nock shows is signed with; its private half signs a publish.
PUBLIC_KEY = "JJ8L2q+aI7j4FoC4NVZSmuSKUSs1by2G6Efqpg3ALTA="
# Stands in for PUBLIC_KEY, for tests that sign their own bundles.
KEY_VARIABLE = "NOCK_DOCS_PUBLIC_KEY"
# `bundled`: the docs nock shipped with, nothing hosted, for evals and reproducibility.
MODE_VARIABLE = "NOCK_DOCS"
BUNDLED = "bundled"
# The oldest nock a published bundle is for, unless the publisher says otherwise.
MINIMUM = "1.0.0"
CACHE = "docs.json"
# Seconds between two asks of the server, and how long one may take.
CHECK_EVERY = 3600
TIMEOUT = 2.0
SEMANTIC = re.compile(r"\d+\.\d+\.\d+")


@dataclass(frozen=True)
class Manifest:
    version: int
    min_cli: str


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def build(texts: dict[str, str], version: int, min_cli: str, seed: bytes) -> dict[str, Any]:
    """The bundle of `texts` (file texts by their path in the docs directory),
    signed with the 32-byte private `seed`."""
    manifest = json.dumps(
        {
            "format": FORMAT,
            "version": version,
            "min_cli": min_cli,
            "docs": {path: digest(text) for path, text in sorted(texts.items())},
        },
        separators=(",", ":"),
    )
    signature = base64.b64encode(signing.sign(seed, manifest.encode())).decode()
    return {"manifest": manifest, "signature": signature, "docs": dict(sorted(texts.items()))}


def verified(bundle: Any, key: bytes) -> Manifest | None:
    """What a bundle's manifest says, when the bundle is whole and signed with
    `key`; None for anything else."""
    if not isinstance(bundle, dict):
        return None
    manifest, signature, texts = bundle.get("manifest"), bundle.get("signature"), bundle.get("docs")
    if not (isinstance(manifest, str) and isinstance(signature, str) and isinstance(texts, dict)):
        return None
    raw = signing.decoded(signature, 64)
    if raw is None or not signing.verify(key, manifest.encode(), raw):
        return None
    try:
        said = json.loads(manifest)
    except ValueError:
        return None
    if not isinstance(said, dict) or said.get("format") != FORMAT:
        return None
    version, min_cli, hashes = said.get("version"), said.get("min_cli"), said.get("docs")
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        return None
    if not isinstance(min_cli, str) or not SEMANTIC.fullmatch(min_cli):
        return None
    if not isinstance(hashes, dict) or set(hashes) != set(texts):
        return None
    for path, text in texts.items():
        if not isinstance(text, str) or hashes[path] != digest(text):
            return None
    return Manifest(version, min_cli)


def fits(min_cli: str, version: str = VERSION) -> bool:
    return parsed(min_cli) <= parsed(version)


def key() -> bytes:
    """The public key bundles are verified with."""
    return signing.decoded(os.environ.get(KEY_VARIABLE) or PUBLIC_KEY, 32) or b""


def committed(directory: Path) -> int:
    """The Unix time of the last commit to `directory`; 0 when git cannot say."""
    try:
        done = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", "."],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    output = done.stdout.strip()
    return int(output) if done.returncode == 0 and output.isdigit() else 0


class Hosted:
    """The hosted docs as this project keeps them."""

    def __init__(self, project: Project, directory: Path = DOCS) -> None:
        self.project = project
        self.directory = directory
        self.path = project.local / CACHE
        self.endpoint = str(project.configuration.get("endpoints.docs")).rstrip("/")

    def cached(self) -> dict[str, Any]:
        try:
            kept = read_json(self.path) if self.path.is_file() else {}
        except PreconditionError:
            return {}
        return kept if isinstance(kept, dict) else {}

    def refresh(self) -> None:
        """Ask the server for the newest bundle this nock fits, unless asked
        within the hour; keep it when it verifies and fits. Whatever the answer,
        the ask is recorded, so a machine offline asks again an hour later."""
        cached = self.cached()
        moment = time.time()
        checked = cached.get("checked")
        if isinstance(checked, int | float) and 0 <= moment - checked < CHECK_EVERY:
            return
        bundle = cached.get("bundle")
        fetched = self.fetch()
        if fetched is not None:
            manifest = verified(fetched, key())
            if manifest is not None and fits(manifest.min_cli):
                bundle = fetched
        write_atomic(self.path, json.dumps({"checked": int(moment), "bundle": bundle}))

    def fetch(self) -> Any:
        request = urllib.request.Request(
            f"{self.endpoint}/{VERSION}", headers={"User-Agent": f"nock/{VERSION}"}
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return None

    def texts(self) -> dict[str, str] | None:
        """The kept bundle's files, when it verifies, fits, is newer than the
        docs nock shipped with and holds sound terms; else None."""
        bundle = self.cached().get("bundle")
        manifest = verified(bundle, key())
        if manifest is None or not fits(manifest.min_cli):
            return None
        if manifest.version <= committed(self.directory):
            return None
        assert isinstance(bundle, dict)
        texts: dict[str, str] = bundle["docs"]
        try:
            if Docs(hosted=texts).problems():
                return None
        except TermError:
            return None
        return texts


def shown(project: Project) -> Docs:
    """The docs `nock docs` shows: the hosted ones when they stand, refreshed
    first, else those nock shipped with; the project's own on top."""
    own = project.here / NOCK_DIRECTORY / "docs"
    if os.environ.get(MODE_VARIABLE) == BUNDLED:
        return Docs(project=own)
    hosted = Hosted(project)
    hosted.refresh()
    return Docs(project=own, hosted=hosted.texts())
