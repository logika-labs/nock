"""Deploy api.nock.dev: `python3 server/deploy/deploy.py HOST`, from a clean checkout.

There is no default host: the box is always named on the command line (an SSH destination with sudo,
e.g. ops@box-1). The release is assembled under `server/build/release/ID/` (the server's wheel, its
hashed third-party requirements, the migrations, `deploy/` and the ledger `logika.json`), packed as one
tarball, copied over SSH, unpacked under `/opt/nock-api/releases/ID`, and installed there by
`deploy/install.sh`: interpreter and packages, migrations, the unit and the Caddy site, the `current`
symlink, the restart, and the five newest releases kept. The steps are printed first, and nothing runs
before the answer is yes. Standard library only.
"""

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
RELEASES = "/opt/nock-api/releases"


@dataclass(frozen=True)
class Step:
    what: str
    command: list[str]


def plan(host: str, release: str, build: Path) -> list[Step]:
    """Every command of a deploy, in order, run in `server/`; the release is staged under `build`."""
    stage = build / release
    tarball = build / f"{release}.tar.gz"
    remote = f"/tmp/nock-api-{release}.tar.gz"
    box = f"{RELEASES}/{release}"
    unpack = f"mkdir -p {RELEASES} && tar -C {RELEASES} -xzf {remote} && rm {remote}"
    return [
        Step("stage the release", ["mkdir", "-p", f"{stage}/wheels"]),
        Step(
            "pin the third-party requirements",
            [
                *("uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-editable"),
                *("--format", "requirements-txt", "--output-file", f"{stage}/requirements.txt"),
                "--quiet",
            ],
        ),
        Step(
            "build the wheel", ["uv", "build", "--wheel", "--out-dir", f"{stage}/wheels", "--quiet"]
        ),
        Step("copy the migrations", ["cp", "-R", "migrations", f"{stage}/migrations"]),
        Step("copy the deploy files", ["cp", "-R", "deploy", f"{stage}/deploy"]),
        Step("copy the ledger", ["cp", "logika.json", f"{stage}/logika.json"]),
        # macOS tar otherwise adds an AppleDouble `._NAME` beside every file with extended attributes.
        Step(
            "pack the release",
            ["env", "COPYFILE_DISABLE=1", "tar", "-C", str(build), "-czf", str(tarball), release],
        ),
        Step(f"copy it to {host}", ["scp", "-q", str(tarball), f"{host}:{remote}"]),
        Step(f"unpack it on {host}", ["ssh", host, shlex.join(["sudo", "sh", "-c", unpack])]),
        Step(
            f"install it on {host}",
            ["ssh", host, shlex.join(["sudo", "sh", f"{box}/deploy/install.sh", box])],
        ),
    ]


def release_id(now: datetime, head: str) -> str:
    """Names sort by age: the box keeps the newest five."""
    return f"{now:%Y%m%dT%H%M%SZ}-{head}"


def destination_problem(host: str) -> str | None:
    """Why HOST cannot be the box: empty, or an option ssh would read."""
    if not host.strip() or host.startswith("-"):
        return "name the box as an SSH destination, e.g. ops@box-1"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deploy.py", description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("host", help="the box, as an SSH destination with sudo")
    host: str = parser.parse_args(argv).host
    problem = destination_problem(host)
    if problem:
        print(f"deploy: {problem}", file=sys.stderr)
        return 2

    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments], cwd=SERVER, check=True, capture_output=True, text=True
        ).stdout.strip()

    if git("status", "--porcelain", "--", "."):
        print("deploy: server/ has uncommitted changes; commit them first", file=sys.stderr)
        return 1
    release = release_id(datetime.now(UTC), git("rev-parse", "--short=12", "HEAD"))
    steps = plan(host, release, SERVER / "build" / "release")
    for step in steps:
        print(f"- {step.what}: {shlex.join(step.command)}")
    if input(f"Deploy {release} to {host}? [y/N] ").strip().lower() != "y":
        print("deploy: nothing done")
        return 1
    for step in steps:
        print(f"== {step.what}", flush=True)
        if subprocess.run(step.command, cwd=SERVER).returncode != 0:
            print(f"deploy: failed to {step.what}", file=sys.stderr)
            return 1
    print(f"deployed {release} to {host}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
