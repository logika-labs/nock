"""Publish nock's docs to api.nock.dev in one command, only when the owner says
yes on the terminal: the committed `src/nock/docs` built into a bundle (its
version the Unix time of the last commit to them, the oldest nock that may
show it `--min-cli`, 1.0.0 unless given), signed with the private key in
`NOCK_DOCS_SIGNING_KEY` (a base64 32-byte seed) and posted to the server,
which keeps the newest per minimum. Every nock that fits it shows it in place
of the docs it shipped with from its next hourly ask on (`nock docs
docs.hosted`). On docs with no uncommitted change; nothing is sent before the
yes. Standard library only.

    NOCK_DOCS_SIGNING_KEY=… python3 scripts/publish_docs.py [--min-cli VERSION] [--server URL]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from nock import hosted, signing  # noqa: E402
from nock.docs import DOCS, Docs, files  # noqa: E402

DOCS_PATH = "src/nock/docs"
KEY_VARIABLE = "NOCK_DOCS_SIGNING_KEY"


class Refused(Exception):
    """What is off about the publish, in words the owner reads."""


def git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *arguments], cwd=ROOT, text=True, capture_output=True)


def publish(min_cli: str, server: str) -> str:
    if not hosted.SEMANTIC.fullmatch(min_cli):
        raise Refused(f"{min_cli!r} is not a version (MAJOR.MINOR.PATCH)")
    seed = signing.decoded(os.environ.get(KEY_VARIABLE, "").strip(), 32)
    if seed is None:
        raise Refused(f"{KEY_VARIABLE} does not hold a base64 32-byte Ed25519 seed")
    if signing.public_key(seed) != hosted.key():
        raise Refused(f"{KEY_VARIABLE} is not the private half of nock's built-in public key")
    if git("status", "--porcelain", "--", DOCS_PATH).stdout.strip():
        raise Refused(f"{DOCS_PATH} has uncommitted changes; publish only committed docs")
    version = hosted.committed(DOCS)
    if not version:
        raise Refused(f"git has no commit of {DOCS_PATH}")
    texts = files(DOCS)
    problems = Docs(hosted=texts).problems()
    if problems:
        raise Refused("the docs break their rules:\n" + "\n".join(problems))
    bundle = hosted.build(texts, version, min_cli, seed)
    url = f"{server.rstrip('/')}/docs"
    question = (
        f"Publish nock's docs ({len(texts)} files, version {version}) for nock {min_cli} and"
        f" newer to {url}, where every nock that fits shows them? [y/N] "
    )
    if input(question).strip().lower() != "y":
        return "nothing sent"
    request = urllib.request.Request(
        url,
        data=json.dumps(bundle).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            answer = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        said = error.read().decode(errors="replace").strip()
        raise Refused(f"{url} refused it ({error.code}): {said}") from error
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise Refused(f"could not reach {url}: {error}") from error
    return (
        f"published {len(texts)} files as version {answer.get('version')} for nock"
        f" {answer.get('min_cli')} and newer to {url}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--min-cli",
        default=hosted.MINIMUM,
        help=f"the oldest nock the docs are for (default: {hosted.MINIMUM})",
    )
    parser.add_argument("--server", default="https://api.nock.dev", help="the API to publish to")
    arguments = parser.parse_args()
    try:
        print(publish(arguments.min_cli, arguments.server))
    except Refused as refused:
        raise SystemExit(f"not published: {refused}") from refused


if __name__ == "__main__":
    main()
