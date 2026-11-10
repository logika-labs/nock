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


def built(site: Path, moved: bool = False) -> dict[str, str]:
    """Build into `site`; every page by the address it is served at (with `moved`, the pages that
    only send a visitor on, instead)."""
    subprocess.run([sys.executable, WEB / "build.py", "--site", site], check=True)
    pages = {}
    for path in site.rglob("*.html"):
        folder = "/".join(["", *path.parent.relative_to(site).parts, ""]).replace("//", "/")
        text = path.read_text()
        if ('http-equiv="refresh"' in text) == moved:
            pages[folder if path.name == "index.html" else folder + path.name] = text
    return pages


def ids(text: str) -> set[str]:
    return set(re.findall(r'id="([^"]+)"', text))


ESSAYS = ["why", "reflection", "cli", "review", "evaluation", "logika", "setup"]


def test_the_docs_are_one_list_of_essays_each_with_its_art_and_a_reference_page_last(
    tmp_path: Path,
) -> None:
    pages = built(tmp_path)
    docs = Docs()
    guides = {
        term.term.removeprefix("guide."): term
        for term in docs.terms
        if term.term.startswith("guide.")
    }
    assert set(guides) == {*ESSAYS, "commands"}
    index = pages["/docs/"]
    listed = re.findall(r'<a class="essay-entry" href="([^"]+)">', index)
    assert listed == [f"/docs/{name}/" for name in ESSAYS] + ["/docs/terms/"]
    assert "tabs" not in index and 'class="group' not in index
    for position, name in enumerate(ESSAYS):
        title = guides[name].article.splitlines()[0].removeprefix("# ")
        page = pages[f"/docs/{name}/"]
        shown = html.unescape(page).replace("’", "'")
        assert re.search(rf'<h1 id="[^"]+">{re.escape(title)}</h1>', shown), name
        assert f'src="/art/{name}-480.webp"' in index and html.escape(title) in index
        article = page.split('<article class="card article essay with-art">')[1]
        assert article.lstrip().startswith(f'<figure class="essay-art"><img src="/art/{name}.webp"')
        head = article.split('<div class="essay-head">')[1].split("</div>")[0]
        assert head.index('<a class="back" href="/docs/"') < head.index("<h1")
        assert "On this page" not in page and 'class="contents"' not in page
        assert 'class="pages"' not in page and "What your agent reads" not in page
        assert "**" not in re.sub(r"<pre>.*?</pre>|<code>.*?</code>", "", article, flags=re.S)
        following = re.findall(
            r'<nav class="essay-next"[^>]*><a class="button primary" href="([^"]+)">Next: ([^<]+)</a>',
            page,
        )
        if position + 1 < len(ESSAYS):
            after = ESSAYS[position + 1]
            assert following == [
                (f"/docs/{after}/", html.escape(guides[after].article.splitlines()[0][2:]))
            ]
        else:
            assert following == []
        for art in (f"{name}.webp", f"{name}-480.webp", f"{name}.jpg"):
            assert (WEB / "site" / "art" / art).is_file(), art
    assert (
        len([url for url in pages if url.startswith("/docs/") and url != "/docs/"])
        == len(ESSAYS) + 1
    )
    reference = pages["/docs/terms/"]
    assert "essay-art" not in reference and "essay-next" not in reference
    assert '<h2 id="commands-and-exit-codes">' in reference
    for term in docs.terms:
        if term.term == "guide" or term.term.startswith("guide.") or len(term.article) > 500:
            continue
        assert f"<code>nock docs {term.term}</code>" in reference, term.term
    assert 'class="t-keyword">def</span>' in pages["/docs/cli/"]


def test_the_art_is_web_sized_and_small() -> None:
    for name in ESSAYS:
        wide, small, preview = (
            WEB / "site" / "art" / file
            for file in (f"{name}.webp", f"{name}-480.webp", f"{name}.jpg")
        )
        assert jpeg_size(preview.read_bytes()) == (1200, 630)
        assert wide.read_bytes()[:4] == b"RIFF" and wide.read_bytes()[8:12] == b"WEBP"
        assert wide.stat().st_size < 500_000 and small.stat().st_size < 80_000
        assert preview.stat().st_size < 300_000


def test_every_link_between_pages_lands_and_old_addresses_are_sent_on(tmp_path: Path) -> None:
    pages = built(tmp_path)
    for url, text in pages.items():
        for href in re.findall(r'href="([^"]+)"', text):
            if href.startswith("#"):
                assert href[1:] in ids(text), (url, href)
            elif href.endswith((".svg", ".png", ".ico")):
                assert (WEB / "site" / href.lstrip("/")).is_file(), (url, href)
            elif href.startswith("/") and not href.endswith((".css", ".woff2", ".js")):
                path, _, anchor = href.partition("#")
                assert path in pages, (url, href)
                assert not anchor or anchor in ids(pages[path]), (url, href)
    moved = json.loads(re.search(r"const moved = (\{.*?\});", pages["/docs/"]).group(1))
    assert moved["a-tool"] == "/docs/cli/#a-tool"
    assert moved["the-map"] == "/docs/review/#the-map-and-consulting"
    assert moved["getting-started"] == "/docs/setup/#install"
    assert moved["what-agents-see"] == "/docs/reflection/#the-first-session"
    assert moved["the-projects-environment"] == "/docs/cli/#the-projects-environment"
    for target in moved.values():
        path, _, anchor = target.partition("#")
        assert path in pages and (not anchor or anchor in ids(pages[path])), target
    sent = built(tmp_path, moved=True)
    old = {
        "install",
        "session",
        "work",
        "chat",
        "tidy",
        "topics",
        "consult",
        "tool",
        "check",
        "commands",
        "settings",
        "telemetry",
        "permissions",
        "sharing",
        "developing",
    }
    assert set(sent) == {f"/docs/{name}/" for name in old} | {"/about/"}
    for url, text in sent.items():
        if url == "/about/":
            continue
        target = re.findall(r'<meta http-equiv="refresh" content="0; url=([^"]+)">', text)[0]
        path, _, anchor = target.partition("#")
        assert path in pages and anchor in ids(pages[path]), (url, target)
        assert 'name="robots" content="noindex"' in text
    assert "/docs/review/#topics" in sent["/docs/topics/"]
    sitemap = (tmp_path / "sitemap.xml").read_text()
    assert not any(f"https://nock.dev{url}<" in sitemap for url in sent)


def test_the_story_pages_are_one_layout_with_a_minute_of_video_per_tab(tmp_path: Path) -> None:
    pages = built(tmp_path)
    home, start = (pages[path] for path in ("/", "/getting-started/"))
    for text in (home, start):
        assert "{{" not in text and "data-layout" not in text and 'class="layouts"' not in text
        menu = text.split('<nav class="menu"')[1].split("</nav>")[0]
        assert 'href="/about/"' not in menu and 'href="/getting-started/"' in menu
        assert '<script src="/story.js" defer></script>' in text
        assert "demo" not in text and "/studio/topics.css" not in text
    assert not [url for url in pages if "index-" in url]
    assert sorted(path.name for path in (WEB / "landing").iterdir()) == [
        "copy.html",
        "home.html",
        "start.html",
    ]
    assert "LAYOUTS" not in (WEB / "build.py").read_text()
    assert not (WEB / "site" / "demo.js").exists() and not (WEB / "site" / "demo.css").exists()
    assert not (tmp_path / "studio").exists()
    assert 'data-tabs-for="films"' in home
    tabs = re.findall(r'data-tab="(\w+)" aria-selected="(\w+)"', home)
    assert tabs == [("reflection", "true"), ("review", "false"), ("evaluation", "false")]
    for name, _ in tabs:
        film = home.split(
            f'<figure class="film" data-panel="{name}" data-panel-for="films" id="{name}">'
        )[1]
        film = film.split("</figure>")[0]
        assert f'poster="/videos/{name}.jpg"' in film
        assert f'<source src="/videos/{name}.webm" type="video/webm">' in film
        assert f'<source src="/videos/{name}.mp4" type="video/mp4">' in film
        assert f'<track kind="captions" src="/videos/{name}.vtt"' in film
        assert "<h2>" in film and "<p>" in film
        for made in (f"{name}.jpg", f"{name}.vtt"):
            assert (WEB / "site" / "videos" / made).is_file()
    assert "uvx nock init" in home and 'href="https://logika.host"' in home
    assert start.count('class="step"') == 7 and "data-stepper" in start
    for still in re.findall(r'<img class="still" src="/videos/([^"]+)"', start):
        assert (WEB / "site" / "videos" / still).is_file()
    assert start.count('class="still"') == 2


def test_a_page_that_is_gone_sends_its_visitor_on_and_is_not_listed(tmp_path: Path) -> None:
    pages = built(tmp_path)
    moved = built(tmp_path, moved=True)
    assert "/about/" in moved
    about = moved["/about/"]
    assert '<meta http-equiv="refresh" content="0; url=/docs/why/">' in about
    assert '<meta name="robots" content="noindex">' in about
    assert '<link rel="canonical" href="https://nock.dev/docs/why/">' in about
    assert "/about/" not in (tmp_path / "sitemap.xml").read_text()
    assert "/about/" not in (tmp_path / "llms.txt").read_text()
    assert not [url for url, text in pages.items() if 'href="/about/"' in text]


def test_the_home_page_shows_nock_in_logika_with_its_art_beside_and_no_logika_scene(
    tmp_path: Path,
) -> None:
    pages = built(tmp_path)
    home = pages["/"]
    section = home.split('id="logika"')[1].split("</section>")[0]
    assert "nock in Logika" in section
    assert "observability and analytics for coding agents" in section
    assert "The reflection round that catches bugs before they happen." in section
    assert 'href="https://logika.host"' in section and "logika.host</a>" not in section
    assert '<source srcset="/logika.webp" type="image/webp">' in section
    assert re.search(r'<img src="/logika.png" alt="" width="800" height="420"', section)
    for art in ("logika.webp", "logika.png"):
        assert (WEB / "site" / art).is_file()
    assert home.index('id="logika"') < home.index('id="community"')
    assert 'data-tab="logika"' not in home and 'data-panel="logika"' not in home


def test_no_page_or_source_names_a_community_channel(tmp_path: Path) -> None:
    pages = built(tmp_path)
    sources = [
        WEB / "build.py",
        WEB / "layout.html",
        WEB / "README.md",
        ROOT / "README.md",
        *(WEB / "landing").glob("*.html"),
        *(ROOT / "src" / "nock" / "terms").rglob("*.md"),
    ]
    for text in [*pages.values(), *(path.read_text() for path in sources)]:
        assert not re.search(r"telegram|t\.me/", text, re.I)
    community = pages["/"].split('id="community"')[1].split("</section>")[0]
    assert "coming soon" in community


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
        head = text.split('<div class="legal-head">')[1].split('<section class="plain"')[0]
        assert head.index("<h1") < head.index('role="switch"')
        assert text.index('class="legal-head"') < text.index('class="plain"')
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
        # The canonical link names the page itself; nothing in the head loads from elsewhere.
        head = re.sub(r'<link rel="canonical"[^>]*>', "", text.split("<body")[0])
        assert not re.search(r'(?:href|src)="https://(?!github\.com/)', head), url


def test_the_sitemap_lists_every_page_at_its_canonical_address_with_its_date(
    tmp_path: Path,
) -> None:
    pages = built(tmp_path)
    sitemap = (tmp_path / "sitemap.xml").read_text()
    listed = re.findall(r"<loc>https://nock\.dev(/[^<]*)</loc>", sitemap)
    assert sorted(listed) == sorted(pages) and len(set(listed)) == len(listed)
    assert len(re.findall(r"<lastmod>\d{4}-\d\d-\d\d</lastmod>", sitemap)) == len(pages)
    assert (tmp_path / "robots.txt").read_text() == (
        "User-agent: *\nAllow: /\n\nSitemap: https://nock.dev/sitemap.xml\n"
    )
    for url, text in pages.items():
        head = text.split("</head>")[0]
        assert re.findall(r'<link rel="canonical" href="([^"]+)">', head) == [
            f"https://nock.dev{url}"
        ], url
        assert "noindex" not in head, url


def jpeg_size(data: bytes) -> tuple[int, int]:
    """A baseline or progressive JPEG's width and height, from its start-of-frame segment."""
    assert data[:2] == b"\xff\xd8"
    at = 2
    while at < len(data):
        marker, length = data[at + 1], int.from_bytes(data[at + 2 : at + 4])
        if marker in (0xC0, 0xC1, 0xC2):
            height = int.from_bytes(data[at + 5 : at + 7])
            return int.from_bytes(data[at + 7 : at + 9]), height
        at += 2 + length
    raise AssertionError("no start-of-frame segment")


def test_every_page_is_previewed_by_its_own_title_description_and_address_with_the_site_image(
    tmp_path: Path,
) -> None:
    pages = built(tmp_path)
    for url, text in pages.items():
        head = text.split("</head>")[0]
        meta = {
            name: html.unescape(content)
            for name, content in re.findall(
                r'<meta (?:property|name)="((?:og|twitter):[^"]+)" content="([^"]*)">', head
            )
        }
        title = html.unescape(re.findall(r"<title>([^<]*)</title>", head)[0])
        description = html.unescape(
            re.findall(r'<meta name="description" content="([^"]*)">', head)[0]
        )
        assert meta["og:title"] == meta["twitter:title"] == title, url
        assert meta["og:description"] == description, url
        assert meta["og:url"] == f"https://nock.dev{url}", url
        essay = re.fullmatch(r"/docs/([a-z]+)/", url)
        if essay and essay.group(1) in ESSAYS:
            assert meta["og:image"] == f"https://nock.dev/art/{essay.group(1)}.jpg", url
        else:
            assert meta["og:image"] == "https://nock.dev/og.jpg", url
        assert (meta["og:image:width"], meta["og:image:height"]) == ("1200", "630"), url
        assert meta["og:image:alt"] and meta["twitter:image:alt"] == meta["og:image:alt"], url
        assert meta["twitter:card"] == "summary_large_image", url


def test_nock_is_named_by_its_one_line_wherever_it_is_summed_up(tmp_path: Path) -> None:
    tagline = "A self-improving toolbox for coding agents."
    home = built(tmp_path)["/"]
    assert f"<title>nock — {tagline}</title>" in home
    assert f'<meta name="twitter:title" content="nock — {tagline}">' in home
    assert f'<meta name="description" content="{tagline} ' in home
    software = json.loads(
        re.findall(r'<script type="application/ld\+json">([^<]*)</script>', home)[1]
    )
    assert software["description"] == tagline
    summary = (tmp_path / "llms.txt").read_text().split("\n> ", 1)[1]
    assert summary.startswith(f"{tagline} ")
    assert (ROOT / "README.md").read_text().split("\n")[2] == tagline


def test_the_preview_image_is_committed_at_1200_by_630_and_small() -> None:
    image = WEB / "site" / "og.jpg"
    assert jpeg_size(image.read_bytes()) == (1200, 630)
    assert image.stat().st_size < 1_000_000


def test_every_description_fits_a_search_result(tmp_path: Path) -> None:
    for url, text in built(tmp_path).items():
        description = html.unescape(
            re.findall(r'<meta name="description" content="([^"]*)">', text)[0]
        )
        assert 0 < len(description) <= 160, (url, len(description))


def test_every_page_carries_json_ld_naming_its_maker_and_the_landing_page_nock(
    tmp_path: Path,
) -> None:
    pages = built(tmp_path)
    for url, text in pages.items():
        found = re.findall(r'<script type="application/ld\+json">([^<]*)</script>', text)
        data = [json.loads(each) for each in found]
        assert data[0]["@type"] == "Organization" and data[0]["name"] == "Parallel Labs, S.L.", url
        assert all(each["@context"] == "https://schema.org" for each in data)
        assert [each["@type"] for each in data[1:]] == (
            ["SoftwareApplication"] if url == "/" else []
        ), url
    software = json.loads(
        re.findall(r'<script type="application/ld\+json">([^<]*)</script>', pages["/"])[1]
    )
    assert software["license"] == "https://opensource.org/licenses/MIT"
    assert software["offers"]["price"] == 0 and software["isAccessibleForFree"] is True


def test_llms_txt_links_every_page_with_a_line_and_resolves_to_built_pages(
    tmp_path: Path,
) -> None:
    pages = built(tmp_path)
    text = (tmp_path / "llms.txt").read_text()
    lines = text.splitlines()
    assert lines[0] == "# nock" and lines[2].startswith("> ")
    assert [line for line in lines if line.startswith("## ")] == [
        "## Start",
        "## Docs",
        "## Legal",
        "## Optional",
    ]
    for line in (line for line in lines if line.startswith("- ")):
        assert re.match(r"- \[[^\]]+\]\(https://[^)]+\): \S", line), line
    links = re.findall(r"\]\((https://[^)]+)\)", text)
    ours = [link.removeprefix("https://nock.dev") for link in links if "nock.dev" in link]
    for path in ours:
        assert path in pages or (tmp_path / path.lstrip("/")).is_file(), path
    assert set(pages) - {"/docs/"} <= set(ours)


def test_llms_full_txt_is_every_guide_and_every_term_as_markdown(tmp_path: Path) -> None:
    built(tmp_path)
    text = (tmp_path / "llms-full.txt").read_text()
    docs = Docs()
    for guide in docs.terms:
        if guide.term.startswith("guide."):
            title = guide.article.strip().splitlines()[0].removeprefix("# ")
            if guide.term[6:] in ESSAYS:
                assert f"\n# {title}\n\nSource: https://nock.dev/docs/{guide.term[6:]}/\n" in text
            else:
                assert f"\n## {title}\n" in text.split("Source: https://nock.dev/docs/terms/")[1]
    short = [
        term
        for term in docs.terms
        if term.term != "guide"
        and not term.term.startswith("guide.")
        and len(term.article) <= 500
        and docs.find(term.term) is term
    ]
    assert short
    for term in short:
        assert f"### nock docs {term.term}\n" in text, term.term
    prose = re.sub(r"```.*?```|`[^`\n]*`", "", text, flags=re.S)
    for target in re.findall(r"\]\(([^)\s]+)\)", prose):
        assert re.match(r"https?://|mailto:", target), target


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
            return {name for name in names if name not in ("style.css", "story.js", "fonts")}
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
        "robots.txt",
        "sitemap.xml",
        "llms.txt",
        "llms-full.txt",
        "style.css",
        "story.js",
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
