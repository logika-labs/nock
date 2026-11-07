"""nock.dev, in `web/`: the pages built from this README and `web/`, and publishing to a
Pages repository — here a local bare one."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from tests.conftest import git

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def built(site: Path) -> dict[str, str]:
    """Build into `site`; every page by the path it is served at."""
    subprocess.run([sys.executable, WEB / "build.py", "--site", site], check=True)
    return {
        "/".join(["", *path.parent.relative_to(site).parts, ""]).replace(
            "//", "/"
        ): path.read_text()
        for path in site.rglob("index.html")
    }


def ids(text: str) -> set[str]:
    return set(re.findall(r'id="([^"]+)"', text))


def test_every_readme_section_is_a_page_with_its_own_contents_and_thanks_stays_off(
    tmp_path: Path,
) -> None:
    pages = built(tmp_path)
    readme = (ROOT / "README.md").read_text()
    sections = re.findall(r"^## (.+)$", re.sub(r"```.*?```", "", readme, flags=re.S), re.M)
    assert "Thanks" in sections and "Getting started" in sections
    for title in sections:
        homes = [
            url
            for url, text in pages.items()
            if re.search(
                rf"<h1 id=\"[^\"]+\">{re.escape(title)}</h1>",
                text.replace("&#x27;", "'").replace("’", "'"),
            )
        ]
        assert len(homes) == (0 if title == "Thanks" else 1), (title, homes)
    assert "/getting-started/" in pages and "/docs/why/" in pages
    for text in pages.values():
        assert "Eyk" not in text and 'id="thanks"' not in text
    topics = pages["/docs/topics/"]
    contents = topics.split('<nav class="contents"')[1].split("</nav>")[0]
    assert re.findall(r'href="#([^"]+)"', contents) == ["the-map", "consulting"]
    article = topics.split('<article class="card article">')[1]
    assert "**" not in re.sub(r"<pre>.*?</pre>|<code>.*?</code>", "", article, flags=re.S)


def test_every_link_between_pages_lands_and_old_anchors_are_sent_on(tmp_path: Path) -> None:
    pages = built(tmp_path)
    for url, text in pages.items():
        for href in re.findall(r'href="([^"]+)"', text):
            if href.startswith("#"):
                assert href[1:] in ids(text), (url, href)
            elif href.startswith("/") and not href.endswith((".css", ".woff2")):
                path, _, anchor = href.partition("#")
                assert path in pages, (url, href)
                assert not anchor or anchor in ids(pages[path]), (url, href)
    moved = json.loads(re.search(r"const moved = (\{.*?\});", pages["/docs/"]).group(1))
    headings = {
        anchor
        for url, text in pages.items()
        if url.startswith(("/docs/", "/getting-started/"))
        for anchor in re.findall(r'<h\d id="([^"]+)"', text)
    }
    assert headings - {"concepts", "evaluation", "reference", "docs"} <= set(moved)
    assert moved["a-tool"] == "/docs/a-tool/"
    assert moved["the-map"] == "/docs/topics/#the-map"
    assert moved["getting-started"] == "/getting-started/"


def test_the_telegram_link_is_one_constant_on_every_page(tmp_path: Path) -> None:
    pages = built(tmp_path)
    source = (WEB / "build.py").read_text()
    telegram = re.findall(r'^TELEGRAM = "([^"]+)"$', source, re.M)
    assert len(telegram) == 1 and len(re.findall(r"t\.me/", source)) == 1
    assert all(f'href="{telegram[0]}"' in text for text in pages.values())


def test_the_legal_pages_show_their_summary_above_the_unchanged_full_text(
    tmp_path: Path,
) -> None:
    pages = built(tmp_path)
    for name in ("privacy", "terms"):
        text = pages[f"/{name}/"]
        title = (WEB / "legal" / f"{name}.md").read_text().splitlines()[0].removeprefix("# ")
        assert "<h1" in text and title in text
        assert "{{" not in text
        assert "github.com/logika-labs/nock/blob/main//" not in text
        assert text.index('role="switch"') < text.index("<h1") < text.index('class="plain"')
        assert text.index('class="plain"') < text.index('class="full"')
        assert "nock.legal.tldr" in text.split("</head>")[0]
        full = html.unescape(re.sub(r"<[^>]+>", "", text.split('<section class="full"')[1]))
        for line in (WEB / "legal" / f"{name}.md").read_text().splitlines()[2:]:
            words = re.sub(
                r"[`*\[\]]|\(mailto:[^)]*\)|\(http[^)]*\)|\(/[^)]*\)|^[-|#\d. ]+", "", line
            )
            for phrase in re.findall(r"[A-Za-z][A-Za-z ,;]{24,}", words)[:2]:
                assert phrase in full, (name, phrase)
    privacy = (WEB / "legal" / "privacy.md").read_text()
    assert "local storage" in privacy and "keeps nothing in your browser" not in privacy
    for url in pages:
        text = pages[url]
        assert 'href="/privacy/"' in text and 'href="/terms/"' in text
        assert not re.search(r'(?:href|src)="https://(?!github\.com/)', text.split("<body")[0]), url


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

    def unbuilt(directory: str, names: list[str]) -> set[str]:
        """What the build makes and the checkout gitignores."""
        if Path(directory) == WEB / "site":
            return {name for name in names if name not in ("style.css", "fonts")}
        return {name for name in names if name in ("pages", "__pycache__")}

    shutil.copytree(WEB, source / "web", ignore=unbuilt)
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
        "getting-started",
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
