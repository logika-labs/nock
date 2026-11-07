"""Release nock in one command, only when the owner says yes on the terminal:
bump the version (the next patch unless VERSION is given) in pyproject.toml,
src/nock/releases.py and uv.lock, commit it, tag it vVERSION and push the
branch and the tag, which starts the release workflow
(.github/workflows/release.yaml): the gate on the tagged commit, the sdist
and the wheel built, and both published to PyPI. On a clean tree, on a
branch, with no tag vVERSION here or on the remote; nothing changes before
the yes. Standard library only.

    python3 scripts/release.py [VERSION] [--remote REMOTE]
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
# Where the version is declared, each with the pattern of the line that holds it.
DECLARED = {
    "pyproject.toml": re.compile(r'^(version = ")([^"]+)(")$', re.MULTILINE),
    "src/nock/releases.py": re.compile(r'^(VERSION = ")([^"]+)(")$', re.MULTILINE),
    "uv.lock": re.compile(r'^(name = "nock"\nversion = ")([^"]+)(")$', re.MULTILINE),
}


class Refused(Exception):
    """What is off about the release, in words the owner reads."""


def git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *arguments], cwd=ROOT, text=True, capture_output=True)


def run(*arguments: str) -> None:
    print("$ git", " ".join(arguments), file=sys.stderr)
    done = git(*arguments)
    if done.returncode != 0:
        raise Refused(f"git {' '.join(arguments)} failed:\n{done.stderr.strip()}")


def numbers(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def declared() -> str:
    with (ROOT / "pyproject.toml").open("rb") as file:
        return str(tomllib.load(file)["project"]["version"])


def next_patch(version: str) -> str:
    major, minor, patch = numbers(version)[:3]
    return f"{major}.{minor}.{patch + 1}"


def bump(version: str) -> list[str]:
    """The version written wherever it is declared; the files that hold it."""
    found = []
    for name, pattern in DECLARED.items():
        path = ROOT / name
        if not path.is_file():
            continue
        bumped, count = pattern.subn(rf"\g<1>{version}\g<3>", path.read_text())
        if count != 1:
            raise Refused(f"{name} does not declare nock's version exactly once")
        path.write_text(bumped)
        found.append(name)
    return found


def release(version: str | None, remote: str) -> str:
    current = declared()
    version = version or next_patch(current)
    tag = f"v{version}"
    if VERSION.fullmatch(version) is None:
        raise Refused(f"{version!r} is not a version (MAJOR.MINOR.PATCH, optionally aN, bN or rcN)")
    if numbers(version) < numbers(current):
        raise Refused(f"{version} is older than the {current} pyproject.toml declares")
    if git("status", "--porcelain").stdout.strip():
        raise Refused("the working tree has uncommitted changes; release only committed code")
    branch = git("symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    if not branch:
        raise Refused("HEAD is detached; release from a branch")
    if git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}").returncode == 0:
        raise Refused(f"tag {tag} already exists here")
    remote_tags = git("ls-remote", "--tags", remote, f"refs/tags/{tag}")
    if remote_tags.returncode != 0:
        raise Refused(f"could not read {remote}'s tags:\n{remote_tags.stderr.strip()}")
    if remote_tags.stdout.strip():
        raise Refused(f"tag {tag} already exists on {remote}")
    bumping = f"bump {current} to {version} in a commit, " if version != current else ""
    question = (
        f"Release nock {version}: {bumping}tag it {tag} and push {branch} and the tag to "
        f"{remote}, which publishes it to PyPI? [y/N] "
    )
    if input(question).strip().lower() != "y":
        return "nothing changed, tagged or pushed"
    if version != current:
        run("add", *bump(version))
        run("commit", "--quiet", "--message", f"nock {version}")
    run("tag", "--annotate", tag, "--message", f"nock {version}")
    try:
        run("push", "--atomic", remote, branch, f"refs/tags/{tag}")
    except Refused as refused:
        raise Refused(
            f"{refused}\n{tag} was created but not pushed; push it with: "
            f"git push --atomic {remote} {branch} {tag}"
        ) from refused
    return (
        f"pushed {branch} and {tag} to {remote}: the release workflow is running (`gh run watch`)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "version", nargs="?", help="the version, such as 0.3.1; the next patch when left out"
    )
    parser.add_argument("--remote", default="origin", help="where to push the branch and the tag")
    arguments = parser.parse_args()
    try:
        print(release(arguments.version, arguments.remote))
    except Refused as refused:
        raise SystemExit(f"not released: {refused}") from refused


if __name__ == "__main__":
    main()
