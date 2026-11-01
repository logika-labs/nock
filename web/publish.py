"""Publish nock.dev to GitHub Pages: build the site, clone its Pages repository
into `web/pages/` (gitignored), make that checkout's tree exactly the site plus
Pages' `CNAME` and `.nojekyll`, commit, show the change, and push only when the
owner says yes on the terminal. Standard library only.

    python3 web/publish.py [--no-push]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from build import OUTPUT, README, build, build_legal

HERE = Path(__file__).resolve().parent
SITE = HERE / "site"
CHECKOUT = HERE / "pages"
REPOSITORY = "git@github.com:logika-labs/nock.dev.git"
DOMAIN = "nock.dev"
BRANCH = "main"


def run(*command: str, cwd: Path | None = None) -> str:
    print("$", " ".join(command), file=sys.stderr)
    return subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True).stdout


def problems(site: Path) -> list[str]:
    """Why `site` must not be published."""
    return [
        f"{relative} is missing"
        for relative in ("index.html", "style.css", "docs/index.html")
        if not (site / relative).is_file()
    ]


def stage(site: Path, checkout: Path) -> None:
    """Make the checkout's tree exactly the site's, keeping its `.git`."""
    for entry in checkout.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    shutil.copytree(site, checkout, dirs_exist_ok=True)
    (checkout / "CNAME").write_text(f"{DOMAIN}\n")
    (checkout / ".nojekyll").write_text("")


def publish(repository: str, push: bool) -> str:
    build(README, OUTPUT)
    build_legal(SITE)
    if found := problems(SITE):
        raise SystemExit("the site is not publishable: " + "; ".join(found))
    head = run("git", "rev-parse", "--short=12", "HEAD", cwd=HERE).strip()
    if CHECKOUT.exists():
        shutil.rmtree(CHECKOUT)
    run("git", "clone", "--quiet", "--depth", "1", repository, str(CHECKOUT))
    stage(SITE, CHECKOUT)
    run("git", "add", "--all", cwd=CHECKOUT)
    if not run("git", "status", "--porcelain", cwd=CHECKOUT).strip():
        return "the published site is already up to date"
    run("git", "commit", "--quiet", "-m", f"Publish the site from nock {head}", cwd=CHECKOUT)
    print(run("git", "show", "--stat", "--format=%s", "HEAD", cwd=CHECKOUT))
    if not push:
        return f"committed in {CHECKOUT}; not pushed (`git -C {CHECKOUT} show` for the diff)"
    if input(f"Push to {repository}, publishing https://{DOMAIN}? [y/N] ").strip().lower() != "y":
        return f"not pushed; the commit is in {CHECKOUT}"
    run("git", "push", "--quiet", "origin", f"HEAD:{BRANCH}", cwd=CHECKOUT)
    return f"published to https://{DOMAIN}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--no-push", action="store_true", help="build, stage and commit in web/pages; push nothing"
    )
    parser.add_argument("--repository", default=REPOSITORY, help="the Pages repository to clone")
    arguments = parser.parse_args()
    try:
        print(publish(arguments.repository, push=not arguments.no_push))
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"{' '.join(error.cmd)} failed:\n{error.stderr}") from error


if __name__ == "__main__":
    main()
