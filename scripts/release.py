"""Cut a nock release: on a clean tree whose pyproject.toml declares VERSION
(bump it in a commit first), with no tag vVERSION here or on the remote, create
the annotated tag and push it, which starts the release workflow
(.github/workflows/release.yml), only when the owner says yes on the terminal.
Standard library only.

    python3 scripts/release.py VERSION [--remote REMOTE]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = re.compile(r"\d+\.\d+\.\d+((a|b|rc)\d+)?")


class Refused(Exception):
    """What is off about the release, in words the owner reads."""


def git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *arguments], cwd=ROOT, text=True, capture_output=True)


def run(*arguments: str) -> None:
    print("$ git", " ".join(arguments), file=sys.stderr)
    done = git(*arguments)
    if done.returncode != 0:
        raise Refused(f"git {' '.join(arguments)} failed:\n{done.stderr.strip()}")


def declared() -> str:
    with (ROOT / "pyproject.toml").open("rb") as file:
        return str(tomllib.load(file)["project"]["version"])


def release(version: str, remote: str) -> str:
    tag = f"v{version}"
    if VERSION.fullmatch(version) is None:
        raise Refused(f"{version!r} is not a version (MAJOR.MINOR.PATCH, optionally aN, bN or rcN)")
    if (found := declared()) != version:
        raise Refused(f"pyproject.toml declares {found}, not {version}: bump it in a commit first")
    if git("status", "--porcelain").stdout.strip():
        raise Refused("the working tree has uncommitted changes; release only committed code")
    if git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}").returncode == 0:
        raise Refused(f"tag {tag} already exists here")
    remote_tags = git("ls-remote", "--tags", remote, f"refs/tags/{tag}")
    if remote_tags.returncode != 0:
        raise Refused(f"could not read {remote}'s tags:\n{remote_tags.stderr.strip()}")
    if remote_tags.stdout.strip():
        raise Refused(f"tag {tag} already exists on {remote}")
    head = git("log", "-1", "--format=%h %s").stdout.strip()
    question = (
        f"Tag {head} as {tag} and push it to {remote}, publishing nock {version} to PyPI? [y/N] "
    )
    if input(question).strip().lower() != "y":
        return "nothing tagged or pushed"
    run("tag", "--annotate", tag, "--message", f"nock {version}")
    try:
        run("push", remote, f"refs/tags/{tag}")
    except Refused as refused:
        raise Refused(
            f"{refused}\n{tag} was created but not pushed; push it with: git push {remote} {tag}"
        ) from refused
    return f"pushed {tag} to {remote}: the release workflow is running (`gh run watch`)"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("version", help="the version pyproject.toml declares, such as 0.3.0")
    parser.add_argument("--remote", default="origin", help="where to push the tag")
    arguments = parser.parse_args()
    try:
        print(release(arguments.version, arguments.remote))
    except Refused as refused:
        raise SystemExit(f"not released: {refused}") from refused


if __name__ == "__main__":
    main()
