"""nock.dev, in `web/`: the docs page built from this README, and publishing to a
Pages repository — here a local bare one."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from tests.conftest import git

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def test_the_docs_page_is_built_from_the_readme_with_contents(tmp_path: Path) -> None:
    page = tmp_path / "index.html"
    subprocess.run([sys.executable, WEB / "build.py", "--output", page], check=True)
    text = page.read_text()
    contents = text.split('<nav class="contents" aria-label="Contents">')[1].split("</nav>")[0]
    sections = re.findall(r"^## (.+)$", (ROOT / "README.md").read_text(), re.M)
    assert sections
    assert len(re.findall(r'class="level-2"', contents)) == len(sections)
    anchors = set(re.findall(r'id="([^"]+)"', text))
    assert set(re.findall(r'href="#([^"]+)"', text)) <= anchors
    article = text.split('<article class="article">')[1]
    assert "**" not in re.sub(r"<pre>.*?</pre>|<code>.*?</code>", "", article, flags=re.S)


def test_the_legal_pages_are_built_from_web_legal_and_linked_from_every_page(
    tmp_path: Path,
) -> None:
    subprocess.run(
        [sys.executable, WEB / "build.py", "--output", tmp_path / "docs" / "index.html"], check=True
    )
    for name in ("privacy", "terms"):
        text = (tmp_path / name / "index.html").read_text()
        title = (WEB / "legal" / f"{name}.md").read_text().splitlines()[0].removeprefix("# ")
        assert "<h1" in text and title in text
        assert "{{" not in text
        assert "github.com/logika-labs/nock/blob/main//" not in text
    for page in (
        tmp_path / "docs" / "index.html",
        WEB / "site" / "index.html",
        tmp_path / "terms" / "index.html",
    ):
        text = page.read_text()
        assert 'href="/privacy/"' in text and 'href="/terms/"' in text
        assert not re.search(r'(?:href|src)="https://(?!github\.com/)', text.split("<body")[0]), (
            page
        )


def publish(source: Path, pages: Path, answer: str = "", *options: str) -> str:
    return subprocess.run(
        [sys.executable, source / "web" / "publish.py", "--repository", str(pages), *options],
        input=answer,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_publishing_replaces_the_pages_tree_and_pushes_only_on_the_word(tmp_path: Path) -> None:
    source = tmp_path / "nock"
    shutil.copytree(
        WEB, source / "web", ignore=shutil.ignore_patterns("pages", "docs", "__pycache__")
    )
    shutil.copy(ROOT / "README.md", source / "README.md")
    git(source, "init", "-q", "-b", "main")
    git(source, "add", "-A")
    git(source, "commit", "-q", "-m", "init")
    pages = tmp_path / "pages.git"
    git(tmp_path, "init", "-q", "--bare", str(pages))

    assert "not pushed" in publish(source, pages, "", "--no-push")
    checkout = source / "web" / "pages"
    published = {path.name for path in checkout.iterdir()} - {".git"}
    assert published == {
        "CNAME",
        ".nojekyll",
        "index.html",
        "style.css",
        "docs",
        "privacy",
        "terms",
        "fonts",
    }
    assert (checkout / "CNAME").read_text() == "nock.dev\n"
    assert not git(pages, "for-each-ref")

    assert "not pushed" in publish(source, pages, "n\n")
    assert not git(pages, "for-each-ref")

    assert "published to https://nock.dev" in publish(source, pages, "y\n")
    files = git(pages, "ls-tree", "-r", "--name-only", "main").splitlines()
    assert {"CNAME", ".nojekyll", "index.html", "docs/index.html"} <= set(files)

    assert "already up to date" in publish(source, pages, "", "--no-push")
