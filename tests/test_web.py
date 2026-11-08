"""nock.dev, in `web/`: the pages built from nock's guides and terms and `web/`, and publishing
to a Pages repository — here a local bare one."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from nock.docs import Docs
from tests.conftest import git

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def built(site: Path) -> dict[str, str]:
    """Build into `site`; every page by the address it is served at."""
    subprocess.run([sys.executable, WEB / "build.py", "--site", site], check=True)
    pages = {}
    for path in site.rglob("*.html"):
        folder = "/".join(["", *path.parent.relative_to(site).parts, ""]).replace("//", "/")
        pages[folder if path.name == "index.html" else folder + path.name] = path.read_text()
    return pages


def ids(text: str) -> set[str]:
    return set(re.findall(r'id="([^"]+)"', text))


def test_every_guide_is_a_docs_page_with_what_an_agent_reads_and_every_term_is_listed(
    tmp_path: Path,
) -> None:
    pages = built(tmp_path)
    docs = Docs()
    guides = [term for term in docs.terms if term.term.startswith("guide.")]
    for guide in guides:
        title = guide.article.splitlines()[0].removeprefix("# ")
        page = pages[f"/docs/{guide.term.removeprefix('guide.')}/"]
        shown = html.unescape(page).replace("’", "'")
        assert re.search(rf'<h1 id="[^"]+">{re.escape(title)}</h1>', shown), guide.term
        article = page.split('<article class="card article">')[1]
        assert "**" not in re.sub(r"<pre>.*?</pre>|<code>.*?</code>", "", article, flags=re.S)
    homes = [url for url in pages if url.startswith("/docs/") and url != "/docs/"]
    assert len(homes) == len(guides) + 1
    topics = pages["/docs/topics/"]
    assert "What your agent reads" in topics and "nock docs topics.items" in topics
    contents = topics.split('<nav class="contents"')[1].split("</nav>")[0]
    assert re.findall(r'href="#([^"]+)"', contents)[:2] == ["topics", "items"]
    listed = pages["/docs/terms/"]
    for term in docs.terms:
        if term.term == "guide" or term.term.startswith("guide.") or len(term.article) > 500:
            continue
        assert f"<code>nock docs {term.term}</code>" in listed, term.term
    assert 'class="t-keyword">def</span>' in pages["/docs/tool/"]
    for group in ("start", "every-day", "extending", "reference"):
        assert f'id="{group}"' in pages["/docs/"]


def test_every_link_between_pages_lands_and_old_anchors_are_sent_on(tmp_path: Path) -> None:
    pages = built(tmp_path)
    for url, text in pages.items():
        for href in re.findall(r'href="([^"]+)"', text):
            if href.startswith("#"):
                assert href[1:] in ids(text), (url, href)
            elif href.startswith("/") and not href.endswith((".css", ".woff2", ".js")):
                path, _, anchor = href.partition("#")
                assert path in pages, (url, href)
                assert not anchor or anchor in ids(pages[path]), (url, href)
    moved = json.loads(re.search(r"const moved = (\{.*?\});", pages["/docs/"]).group(1))
    assert moved["a-tool"] == "/docs/tool/"
    assert moved["the-map"] == "/docs/consult/#the-map"
    assert moved["getting-started"] == "/docs/install/"
    assert moved["what-agents-see"] == "/docs/session/"
    assert moved["the-projects-environment"] == "/docs/tool/#the-projects-environment"


def test_each_layout_is_its_own_set_of_story_pages_with_the_demo(tmp_path: Path) -> None:
    pages = built(tmp_path)
    demo = (WEB / "site" / "demo.js").read_text()
    scenes = set(re.findall(r"^    (\w+): \{\n      label:", demo, re.M))
    assert scenes == {"reflection", "review", "logika"}
    for layout, prefix in (("a", ""), ("b", "index-b.html"), ("c", "index-c.html")):
        home, about, start = (
            pages[f"{path}{prefix}"] for path in ("/", "/about/", "/getting-started/")
        )
        for text in (home, about, start):
            assert f'data-layout="{layout}"' in text and "{{" not in text
            menu = text.split('<nav class="menu"')[1].split("</nav>")[0]
            assert f'href="/about/{prefix}"' in menu and f'href="/getting-started/{prefix}"' in menu
        named = {
            name for value in re.findall(r'data-demo="([^"]+)"', home) for name in value.split()
        }
        assert named == scenes, layout
        assert "uvx nock init" in home and 'href="https://logika.host"' in home
        assert start.count('class="step"') == 7
    assert (tmp_path / "studio" / "topics.css").read_text() == (
        ROOT / "src" / "nock" / "pages" / "topics.css"
    ).read_text()
    assert 'data-demo-still="review:3"' in pages["/getting-started/"]


def test_the_telegram_link_is_one_constant_on_every_page(tmp_path: Path) -> None:
    pages = built(tmp_path)
    source = (WEB / "build.py").read_text()
    telegram = re.findall(r'^TELEGRAM = "([^"]+)"$', source, re.M)
    assert len(telegram) == 1 and len(re.findall(r"t\.me/", source)) == 1
    assert all(f'href="{telegram[0]}"' in text for text in pages.values())


def test_the_legal_pages_show_their_summary_or_their_unchanged_full_text(
    tmp_path: Path,
) -> None:
    pages = built(tmp_path)
    style = (WEB / "site" / "style.css").read_text()
    assert '[data-tldr="on"] .full, [data-tldr="off"] .plain { display: none; }' in style
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
            return {
                name for name in names if name not in ("style.css", "demo.js", "demo.css", "fonts")
            }
        return {name for name in names if name in ("pages", "__pycache__")}

    shutil.copytree(WEB, source / "web", ignore=unbuilt)
    shutil.copytree(ROOT / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__"))
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
        "index-b.html",
        "index-c.html",
        "style.css",
        "demo.js",
        "demo.css",
        "studio",
        "about",
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
