"""nock.dev's release to Logika's box (`web/deploy.py`): the site staged from the committed tree, the plan
in order, the closed site (`--coming-soon`), and the box's side of a release and a rollback run for real on a temporary directory standing in
for /srv/sites and /etc/caddy/sites, with `caddy` and `systemctl` recording what they were asked."""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

WEB = Path(__file__).resolve().parent.parent / "web"


def load() -> ModuleType:
    sys.path.insert(0, str(WEB))
    specification = importlib.util.spec_from_file_location("web_deploy", WEB / "deploy.py")
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules["web_deploy"] = module
    specification.loader.exec_module(module)
    return module


DEPLOY = load()
CADDY_SITE = (WEB / "nock.dev.caddy").read_text()


class Box:
    """A stand-in box: the sites and Caddy's site directories, and stub `caddy` and `systemctl` on PATH
    that append their arguments to a log; `caddy validate` fails while `refuse` exists."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.sites = root / "srv-sites"
        self.caddy = root / "caddy-sites"
        self.local = root / "local"
        self.local.mkdir(parents=True)
        self.log = root / "log"
        self.refuse = root / "refuse"
        stubs = root / "stubs"
        stubs.mkdir()
        for tool in ("caddy", "systemctl"):
            stub = stubs / tool
            stub.write_text(
                f'#!/bin/sh\necho "{tool} $*" >> {self.log}\n'
                f'[ "{tool}" != caddy ] || [ ! -e {self.refuse} ]\n'
            )
            stub.chmod(0o755)
        self.path = f"{stubs}:{os.environ['PATH']}"

    def run(self, script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", "-c", script],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PATH": self.path},
        )

    def release(
        self, name: str, text: str, caddy_site: str = CADDY_SITE
    ) -> subprocess.CompletedProcess[str]:
        staged = self.local / name
        (staged / "docs").mkdir(parents=True)
        (staged / "index.html").write_text(text)
        (staged / "docs" / "index.html").write_text("docs")
        tarball = self.local / f"{name}.tar.gz"
        subprocess.run(["tar", "-C", str(self.local), "-czf", str(tarball), name], check=True)
        shutil.rmtree(staged)
        return self.run(
            DEPLOY.activate(str(self.sites), str(self.caddy), name, str(tarball), caddy_site)
        )

    def served(self) -> str:
        return (self.sites / "nock.dev" / "current" / "index.html").read_text()

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []


def test_a_release_installs_the_caddy_site_once_and_switches_current(tmp_path: Path) -> None:
    box = Box(tmp_path)
    first = box.release("20261101T000000Z-a", "first")
    assert first.returncode == 0, first.stderr
    assert box.served() == "first"
    assert (box.caddy / "nock.dev.caddy").read_text() == CADDY_SITE
    assert box.calls() == [
        "caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile",
        "systemctl reload caddy.service",
    ]
    second = box.release("20261102T000000Z-b", "second")
    assert second.returncode == 0, second.stderr
    current = box.sites / "nock.dev" / "current"
    assert os.readlink(current) == "releases/20261102T000000Z-b" and box.served() == "second"
    # An unchanged Caddy site is neither validated nor reloaded again.
    assert len(box.calls()) == 2
    assert (
        not list(box.caddy.glob("*.new")) and not (box.sites / "nock.dev" / "current.new").exists()
    )


def test_a_caddy_site_caddy_refuses_is_taken_back_and_nothing_switches(tmp_path: Path) -> None:
    box = Box(tmp_path)
    assert box.release("20261101T000000Z-a", "first").returncode == 0
    box.refuse.touch()
    refused = box.release("20261102T000000Z-b", "second", CADDY_SITE + "broken {\n")
    assert refused.returncode == 1 and "Caddy refuses the new site" in refused.stderr
    assert (box.caddy / "nock.dev.caddy").read_text() == CADDY_SITE
    assert box.served() == "first"
    assert box.calls()[-1].startswith("caddy validate")


def test_the_five_newest_releases_are_kept_and_a_rollback_steps_back(tmp_path: Path) -> None:
    box = Box(tmp_path)
    names = [f"2026110{day}T000000Z-r{day}" for day in range(1, 8)]
    for name in names:
        assert box.release(name, name).returncode == 0
    kept = sorted(path.name for path in (box.sites / "nock.dev" / "releases").iterdir())
    assert kept == names[-DEPLOY.KEEP :]
    assert box.run(DEPLOY.rollback(str(box.sites))).returncode == 0
    assert box.served() == names[-2]
    for _ in range(3):
        assert box.run(DEPLOY.rollback(str(box.sites))).returncode == 0
    oldest = box.run(DEPLOY.rollback(str(box.sites)))
    assert oldest.returncode == 1 and f"no release before {names[-5]}" in oldest.stderr
    assert box.served() == names[-5]


def test_the_release_is_staged_from_the_committed_tree_and_switched_last(tmp_path: Path) -> None:
    staged = tmp_path / "release" / "20261105T120000Z-abc"
    DEPLOY.stage(staged)
    assert DEPLOY.problems(staged) == []
    assert (staged / "fonts" / "OFL.txt").is_file() and (staged / "studio" / "topics.css").is_file()
    steps = DEPLOY.plan("ops@box-1", "20261105T120000Z-abc", tmp_path / "release")
    assert [step.what for step in steps] == [
        "pack the release",
        "copy it to ops@box-1",
        "switch ops@box-1 to it",
    ]
    for step in steps[:1]:
        subprocess.run(step.command, check=True)
    listed = subprocess.run(
        ["tar", "-tzf", str(tmp_path / "release" / "20261105T120000Z-abc.tar.gz")],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert "20261105T120000Z-abc/index.html" in listed
    assert not [name for name in listed if Path(name).name.startswith("._")]
    switch = steps[-1].command
    assert switch[:2] == ["ssh", "ops@box-1"] and "/srv/sites/nock.dev" in switch[2]
    assert "/etc/caddy/sites/nock.dev.caddy" in switch[2]


def test_a_closed_site_is_the_coming_soon_page_and_the_legal_pages(tmp_path: Path) -> None:
    staged = tmp_path / "release" / "20261105T120000Z-abc"
    DEPLOY.stage(staged)
    terms = (staged / "terms" / "index.html").read_text()
    DEPLOY.close(staged)
    assert sorted(entry.name for entry in staged.iterdir()) == sorted(DEPLOY.OPEN_WHILE_CLOSED)
    assert (staged / "terms" / "index.html").read_text() == terms
    assert (staged / "privacy" / "index.html").is_file() and (
        staged / "fonts" / "OFL.txt"
    ).is_file()
    home = (staged / "index.html").read_text()
    assert "<title>nock — coming soon</title>" in home
    assert '<h1 id="coming-soon-title">Coming soon</h1>' in home
    assert "<p>A self-improving toolbox for coding agents.</p>" in home
    assert '<meta property="og:title" content="nock — coming soon">' in home
    assert '<meta property="og:url" content="https://nock.dev/">' in home
    links = re.findall(r'href="(/[^"]*)"', home)
    assert {link for link in links if not link.startswith(("/fonts/", "/style.css"))} == {
        "/",
        "/privacy/",
        "/terms/",
        "/favicon.svg",
        "/favicon-32.png",
        "/favicon-16.png",
        "/apple-touch-icon.png",
    }
    assert all((staged / icon).is_file() for icon in DEPLOY.ICONS)
    assert not re.search(r"<script(?! type=\"application/ld\+json\")[^>]*\ssrc=", home)


def test_the_box_is_always_named() -> None:
    assert DEPLOY.destination_problem("ops@box-1") is None
    assert DEPLOY.destination_problem("") and DEPLOY.destination_problem("-oProxyCommand=x")
    assert DEPLOY.main(["--", "-oProxyCommand=x"]) == 2
