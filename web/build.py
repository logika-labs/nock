"""Build nock.dev into `site/`: the landing page, About and Getting started from `landing/`; the docs from nock's guides and terms (`src/nock/terms/`, what
`nock docs` reads too), a page per guide in four groups, each with what an agent reads on it; the
legal pages from `legal/`, each with its plain-words summary. Every page is set in `layout.html`.
Standard library only, and nock's own `docs` module, to read the terms as `nock docs` does.

    python3 web/build.py [--site DIRECTORY]
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import NamedTuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from nock.docs import TERMS, Docs, Term  # noqa: E402  (nock's source, beside the site)

SITE = HERE / "site"
LAYOUT = HERE / "layout.html"
LANDING = HERE / "landing"
STUDIO = HERE.parent / "src" / "nock" / "pages"
GITHUB = "https://github.com/logika-labs/nock"
REPOSITORY = GITHUB + "/blob/main/"
LOGIKA = "https://logika.host"

# The story pages, by where they are served, with their title, description and template in landing/.
# nock's one line, everywhere it is named: the home page's title, its description's first sentence,
# llms.txt's summary and the JSON-LD.
TAGLINE = "A self-improving toolbox for coding agents."

STORY = {
    "/": (
        f"nock — {TAGLINE}",
        f"{TAGLINE} It lives in your repository, records every session, puts their work before you and writes the tools they need.",
        "home",
    ),
    "/about/": (
        "About · nock",
        "What nock is, the principles it keeps, and who makes it.",
        "about",
    ),
    "/getting-started/": (
        "Getting started · nock",
        "From uvx nock init to your first verdict on what an agent made, step by step.",
        "start",
    ),
}

# The docs: four groups, each a list of pages. A page is a guide (`nock docs guide.NAME`), served at
# /docs/NAME/, with the terms an agent reads on the same subject folded in under it; the terms page
# lists every term. A guide placed nowhere fails the build.
GROUPS = {
    "start": "Start",
    "every-day": "Every day",
    "extending": "Extending",
    "reference": "Reference",
}
PAGES: dict[str, tuple[str, tuple[str, ...]]] = {
    "why": ("start", ()),
    "install": ("start", ("setup", "checks", "checks.chains")),
    "session": ("start", ("reminders", "run", "status")),
    "work": ("every-day", ("studio", "topics.verdicts", "topics.search")),
    "chat": ("every-day", ("topics.threads",)),
    "tidy": ("every-day", ("topics.state",)),
    "topics": (
        "every-day",
        (
            "topics",
            "topics.items",
            "topics.decisions",
            "topics.derived",
            "topics.options",
            "topics.state",
            "topics.versions",
            "topics.revive",
        ),
    ),
    "consult": ("every-day", ("topics.map", "consult")),
    "reflection": (
        "every-day",
        ("reflection", "reflection.kinds", "reflection.record", "reflection.share"),
    ),
    "logika": ("every-day", ("reflection.logika", "logika")),
    "tool": (
        "extending",
        (
            "tools",
            "tools.signature",
            "fixtures",
            "sh",
            "sh.stream",
            "output",
            "output.cap",
            "errors",
            "tools.confirm",
            "tools.caching",
            "tools.examples",
            "tools.loading",
            "tools.records",
            "tools.retiring",
            "environment",
        ),
    ),
    "check": (
        "extending",
        (
            "checks",
            "checks.commands",
            "checks.chains",
            "checks.changed",
            "hooks",
            "generators",
            "generators.catalogs",
            "generators.templates",
        ),
    ),
    "evaluation": (
        "extending",
        (
            "eval",
            "eval.flow",
            "eval.steps",
            "eval.scenario",
            "eval.parameters",
            "eval.runs",
            "eval.query",
            "eval.compare",
        ),
    ),
    "commands": ("reference", ("exit-codes",)),
    "settings": ("reference", ("configuration",)),
    "terms": ("reference", ()),
    "telemetry": (
        "reference",
        ("telemetry", "telemetry.sessions", "telemetry.tables", "telemetry.unrecorded"),
    ),
    "permissions": ("reference", ("permissions",)),
    "sharing": ("reference", ("sharing", "report")),
    "developing": ("reference", ()),
}
TERMS_PAGE = (
    "The terms",
    "Every `nock docs` term: the short articles your agents read, each in full.",
)
# Headings of the one-page docs and of the README's sections before the guides, by the heading that
# has their text now: an old address, /docs/#ANCHOR, is sent on to it.
RENAMED = {
    "getting-started": "install",
    "what-agents-see": "the-first-session",
    "reflection": "reflection-rounds",
    "topics": "topics-and-items",
    "reference": "commands-and-exit-codes",
    "concepts": "what-changes-for-you",
    "evaluation": "evaluations",
}
# Each legal page: its source in legal/ (and its plain-words summary, NAME-plain.md), its description.
LEGAL = {
    "privacy": "What reaches nock's makers from nock.dev and from nock: the usage report, shared summaries, reports you write, and your rights.",
    "terms": "The terms of nock.dev and api.nock.dev; the software itself is MIT licensed.",
}
# The visitor's choice of the legal pages' summary, kept in their browser only once they turn it off.
TLDR_KEY = "nock.legal.tldr"

ICONS = {
    "github": '<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 0a8 8 0 0 0-2.53 15.59c.4.07.55-.17.55-.38v-1.33c-2.23.48-2.7-1.07-2.7-1.07-.36-.92-.89-1.17-.89-1.17-.73-.5.06-.49.06-.49.8.06 1.23.83 1.23.83.71 1.23 1.87.87 2.33.67.07-.52.28-.87.5-1.07-1.78-.2-3.65-.89-3.65-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 0 1 4 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.28.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48v2.2c0 .21.15.46.55.38A8 8 0 0 0 8 0z"/></svg>',
}


def slug(text: str) -> str:
    """GitHub's anchor for a heading, so the guides' own links land."""
    text = re.sub(r"<[^>]+>|`|['’]", "", text).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def inline(text: str) -> str:
    """Code, bold, italics and links, the rest escaped. Code spans are set aside
    first, so emphasis and links can wrap them and never reach inside them."""
    spans: list[str] = []

    def aside(match: re.Match[str]) -> str:
        spans.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\0{len(spans) - 1}\0"

    text = html.escape(re.sub(r"`([^`]+)`", aside, text), quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)

    def link(match: re.Match[str]) -> str:
        target = match.group(2)
        if not re.match(r"[a-z]+:|#|/", target):
            target = REPOSITORY + target
        return f'<a href="{html.escape(target)}">{match.group(1)}</a>'

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
    return re.sub(r"\0(\d+)\0", lambda match: spans[int(match.group(1))], text)


# --- code blocks: black, highlighted in nock's colours, as the studio's ---------------------------

STRINGS = r""""(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'"""
NUMBER = r"(?<![\w.:/-])(?:0x[0-9a-fA-F_]+|\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?)(?![\w.:/-])"
WORDS = {
    "python": set(
        [
            "and",
            "as",
            "assert",
            "async",
            "await",
            "break",
            "class",
            "continue",
            "def",
            "del",
            "elif",
            "else",
            "except",
            "False",
            "finally",
            "for",
            "from",
            "global",
            "if",
            "import",
            "in",
            "is",
            "lambda",
            "None",
            "nonlocal",
            "not",
            "or",
            "pass",
            "raise",
            "return",
            "True",
            "try",
            "while",
            "with",
            "yield",
            "match",
            "case",
            "self",
        ]
    ),
    "sh": set(
        [
            "if",
            "then",
            "else",
            "elif",
            "fi",
            "for",
            "while",
            "until",
            "do",
            "done",
            "case",
            "esac",
            "in",
            "function",
            "return",
            "export",
            "local",
            "echo",
            "exit",
            "set",
            "true",
            "false",
        ]
    ),
    "toml": {"true", "false"},
    "json": {"true", "false", "null"},
}
RULES = {
    "python": [
        ("comment", r"#.*"),
        ("string", rf'"""[\s\S]*?"""|[rbfu]?(?:{STRINGS})'),
        ("meta", r"@[\w.]+"),
        ("number", NUMBER),
    ],
    "sh": [
        ("comment", r"(?:^|(?<=\s))#.*"),
        ("string", STRINGS),
        ("meta", r"\$\{[^}]*\}|\$\w+"),
        ("number", NUMBER),
    ],
    "toml": [
        ("comment", r"#.*"),
        ("meta", r"^[ \t]*\[\[?[^\]\n]+\]\]?"),
        ("key", r"^[ \t]*[\w.\-\"']+(?=[ \t]*=)"),
        ("string", STRINGS),
        ("number", NUMBER),
    ],
    "json": [("key", r'"(?:\\.|[^"\\\n])*"(?=\s*:)'), ("string", STRINGS), ("number", NUMBER)],
}


def highlight(source: str, language: str) -> str:
    """`source` escaped, its tokens in the studio's `t-` classes; as it is for a language unknown."""
    rules = RULES.get(language)
    if not rules:
        return html.escape(source)
    rules = [*rules, ("word", r"[A-Za-z_$][\w$]*")]
    pattern = re.compile("|".join(f"({rule})" for _, rule in rules), re.M)
    out: list[str] = []
    at = 0
    for found in pattern.finditer(source):
        if not found.group(0):
            continue
        out.append(html.escape(source[at : found.start()]))
        index = next(index for index, group in enumerate(found.groups()) if group is not None)
        kind = rules[index][0]
        if kind == "word":
            word = found.group(0)
            following = source[found.end() : found.end() + 1]
            kind = (
                "keyword"
                if word in WORDS[language]
                else "call"
                if following == "("
                else "type"
                if re.match(r"[A-Z][a-z]", word)
                else ""
            )
        escaped = html.escape(found.group(0))
        out.append(f'<span class="t-{kind}">{escaped}</span>' if kind else escaped)
        at = found.end()
    return "".join(out) + html.escape(source[at:])


class Converter:
    """The Markdown nock's guides use: headings, paragraphs, nested lists,
    fenced code, tables, block quotes."""

    def __init__(self, text: str) -> None:
        self.lines = text.replace("\r", "").split("\n")
        self.index = 0
        self.headings: list[tuple[int, str, str]] = []

    def convert(self) -> str:
        return self.blocks(0)

    def blocks(self, indent: int) -> str:
        out: list[str] = []
        paragraph: list[str] = []

        def flush() -> None:
            if paragraph:
                out.append(f"<p>{inline(' '.join(paragraph))}</p>")
                paragraph.clear()

        while self.index < len(self.lines):
            raw = self.lines[self.index]
            stripped = raw.strip()
            current = len(raw) - len(raw.lstrip())
            if stripped and current < indent:
                break
            line = raw[indent:] if len(raw) >= indent else raw.lstrip()
            if not stripped:
                flush()
                # A blank line ends a list item's body unless the next line is still indented.
                following = next(
                    (item for item in self.lines[self.index + 1 :] if item.strip()), ""
                )
                if indent and len(following) - len(following.lstrip()) < indent:
                    self.index += 1
                    break
                self.index += 1
                continue
            if line.startswith("```"):
                flush()
                language = line[3:].strip()
                self.index += 1
                code = []
                while self.index < len(self.lines) and not self.lines[
                    self.index
                ].strip().startswith("```"):
                    code.append(self.lines[self.index][indent:])
                    self.index += 1
                self.index += 1
                shown = highlight("\n".join(code), language)
                out.append(f"<pre><code>{shown}</code></pre>")
                continue
            heading = re.match(r"(#{1,4})\s+(.*)", line)
            if heading and not indent:
                flush()
                level = len(heading.group(1))
                text = inline(heading.group(2))
                anchor = slug(heading.group(2))
                self.headings.append((level, anchor, text))
                out.append(f'<h{level} id="{anchor}">{text}</h{level}>')
                self.index += 1
                continue
            if line.startswith(">"):
                flush()
                quoted = []
                while self.index < len(self.lines) and self.lines[self.index][indent:].startswith(
                    ">"
                ):
                    quoted.append(self.lines[self.index][indent:].lstrip(">").strip())
                    self.index += 1
                body = Converter("\n".join(quoted)).convert()
                out.append(f"<blockquote>{body}</blockquote>")
                continue
            if line.startswith("|"):
                flush()
                out.append(self.table(indent))
                continue
            marker = re.match(r"([-*]|\d+[.)])\s+", line)
            if marker:
                flush()
                out.append(self.list(indent, marker.group(1)[0].isdigit()))
                continue
            paragraph.append(stripped)
            self.index += 1
        flush()
        return "\n".join(out)

    def list(self, indent: int, ordered: bool) -> str:
        items = []
        while self.index < len(self.lines):
            raw = self.lines[self.index]
            line = raw[indent:]
            marker = re.match(r"([-*]|\d+[.)])\s+", line)
            if not marker or len(raw) - len(raw.lstrip()) != indent:
                break
            body_indent = indent + marker.end()
            self.lines[self.index] = " " * body_indent + line[marker.end() :]
            items.append(f"<li>{self.blocks(body_indent)}</li>")
        tag = "ol" if ordered else "ul"
        return f"<{tag}>{''.join(items)}</{tag}>"

    def table(self, indent: int) -> str:
        rows = []
        while self.index < len(self.lines) and self.lines[self.index][indent:].startswith("|"):
            line = self.lines[self.index].strip().strip("|")
            # `\|` is a pipe inside a cell, as GitHub reads it.
            cells = [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", line)]
            rows.append(cells)
            self.index += 1
        head, body = rows[0], rows[2:]
        out = ['<div class="table"><table><thead><tr>']
        out += [f"<th>{inline(cell)}</th>" for cell in head]
        out.append("</tr></thead><tbody>")
        for row in body:
            out.append("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>")
        out.append("</tbody></table></div>")
        return "".join(out)


# --- the docs -------------------------------------------------------------------------------------


class Page(NamedTuple):
    """A docs page: its name (served at /docs/NAME/), its group, title, description, body, its own
    table of contents, and the terms an agent reads on it."""

    name: str
    group: str
    title: str
    description: str
    body: str
    contents: str
    reads: tuple[Term, ...]

    @property
    def url(self) -> str:
        return f"/docs/{self.name}/"


def contents_of(headings: list[tuple[int, str, str]]) -> str:
    links = "\n".join(
        f'<a class="level-{level}" href="#{anchor}">{text}</a>'
        for level, anchor, text in headings
        if level in (2, 3)
    )
    if not links:
        return ""
    return f'<nav class="contents" aria-label="On this page"><span class="label">On this page</span>\n{links}\n</nav>'


def term_article(term: Term, level: int = 3) -> str:
    """A term as an agent reads it: its `nock docs` line, its description and its article."""
    article = Converter(term.article).convert()
    return (
        f'<section class="term"><h{level} id="term-{slug(term.term)}"><code>nock docs {term.term}</code></h{level}>'
        f'<p class="description">{inline(term.description)}</p>\n{article}</section>'
    )


def guides(docs: Docs) -> dict[str, Term]:
    """The guides by name (`guide.install` is `install`), every one placed on a page."""
    found = {
        term.term.removeprefix("guide."): term
        for term in docs.terms
        if term.term.startswith("guide.")
    }
    unplaced = set(found) - set(PAGES)
    missing = set(PAGES) - set(found) - {"terms"}
    if unplaced or missing:
        raise SystemExit(
            "web/build.py places the guides by name: "
            + "; ".join(
                [f"guide.{name} is on no page (PAGES)" for name in sorted(unplaced)]
                + [f"guide.{name} is not a guide" for name in sorted(missing)]
            )
        )
    return found


def short_terms(docs: Docs) -> list[Term]:
    """The terms an agent reads at a glance: neither a guide nor a brief."""
    return [
        term
        for term in docs.terms
        if term.term != "guide"
        and not term.term.startswith("guide.")
        and docs.find(term.term) is term
        and len(term.article) <= 500
    ]


def terms_body(docs: Docs) -> tuple[str, list[tuple[int, str, str]]]:
    """Every short term, by its root: what `nock docs` prints for each, whole."""
    roots: dict[str, list[Term]] = {}
    for term in short_terms(docs):
        roots.setdefault(term.term.split(".")[0], []).append(term)
    headings: list[tuple[int, str, str]] = [(1, "the-terms", "The terms")]
    out = [
        '<h1 id="the-terms">The terms</h1>',
        "<p>What your agents read: <code>.nock/nock docs</code> lists these terms, "
        "<code>.nock/nock docs TERM</code> prints one, and a term it doesn't know answers with the "
        "three closest. Each is at most 500 characters, so an agent reads only what its next step "
        "needs; the guides (<code>.nock/nock docs guide</code>) are the long form, and the briefs "
        "the installed skills and subagents follow are left out here.</p>",
    ]
    for root, terms in roots.items():
        anchor = f"terms-{root}"
        headings.append((2, anchor, f"<code>{html.escape(root)}</code>"))
        out.append(f'<h2 id="{anchor}"><code>{html.escape(root)}</code></h2>')
        out += [term_article(term) for term in terms]
    return "\n".join(out), headings


def docs_pages(docs: Docs) -> list[Page]:
    found = guides(docs)
    pages = []
    for name, (group, reads) in PAGES.items():
        terms = []
        for word in reads:
            term = docs.find(word)
            if term is None:
                raise SystemExit(f"web/build.py: the docs page {name} reads `{word}`, not a term")
            terms.append(term)
        if name == "terms":
            body, headings = terms_body(docs)
            title, description = TERMS_PAGE
        else:
            converter = Converter(found[name].article)
            body = converter.convert()
            headings = converter.headings
            title = re.sub(r"<[^>]+>", "", headings[0][2])
            description = found[name].description
        page = Page(name, group, title, description, body, contents_of(headings), tuple(terms))
        pages.append(page)
    return pages


def relink(text: str, here: str, located: dict[str, str]) -> str:
    """Point a guide's link to a heading on another page at that page."""

    def target(match: re.Match[str]) -> str:
        anchor = match.group(1)
        where = located.get(anchor)
        if where is None or where.split("#")[0] == here:
            return match.group(0)
        return f'href="{where}"'

    return re.sub(r'href="#([^"]+)"', target, text)


def marked(current: bool) -> str:
    return ' aria-current="page"' if current else ""


def agent_reads(page: Page) -> str:
    """The terms an agent reads on the page's subject, folded under it."""
    if not page.reads:
        return ""
    names = " ".join(f"<code>{term.term}</code>" for term in page.reads)
    articles = "\n".join(term_article(term, 4) for term in page.reads)
    return f"""<details class="reads">
<summary><span class="label">What your agent reads</span><span class="names">{names}</span></summary>
<div class="body">
<p class="note">The same subject as <code>.nock/nock docs</code> gives it to your agents: a short article each.</p>
{articles}
</div>
</details>"""


def pager(previous: Page | None, following: Page | None) -> str:
    links = []
    if previous:
        title = html.escape(previous.title)
        links.append(
            f'<a class="previous" href="{previous.url}"><span class="label">Previous</span>{title}</a>'
        )
    if following:
        title = html.escape(following.title)
        links.append(
            f'<a class="next" href="{following.url}"><span class="label">Next</span>{title}</a>'
        )
    return f'<nav class="pager" aria-label="Pages">{"".join(links)}</nav>' if links else ""


def article(page: Page, located: dict[str, str], after: str) -> str:
    body = relink(page.body, page.url, located)
    heading, rest = body.split("\n", 1) if "\n" in body else (body, "")
    return (
        f'<article class="card article">\n{heading}\n{page.contents}\n{rest}\n{after}\n</article>'
    )


def groups_nav(current: str | None) -> str:
    return "\n".join(
        f'<a href="/docs/#{group}"{marked(group == current)}>{title}</a>'
        for group, title in GROUPS.items()
    )


def docs_index(pages: list[Page], located: dict[str, str]) -> str:
    """Every group, its pages with a line each; an address naming a heading of the old one-page docs
    goes to its page."""
    cards = []
    for group, title in GROUPS.items():
        entries = "\n".join(
            f'<li><a href="{page.url}">{html.escape(page.title)}</a><p>{inline(page.description)}</p></li>'
            for page in pages
            if page.group == group
        )
        cards.append(
            f'<section class="card group" id="{group}" aria-labelledby="{group}-title">'
            f'<h2 id="{group}-title">{title}</h2><ol class="entries">\n{entries}\n</ol></section>'
        )
    moved = {anchor: where for anchor, where in located.items() if anchor not in GROUPS}
    moved |= {old: located[new] for old, new in RENAMED.items() if new in located}
    return f"""<div class="frame docs">
<div class="card docs-head">
<h1>Docs</h1>
<p>By what you are doing. The same text is in nock itself, <code>.nock/nock docs guide</code>, and each page folds in what your agent reads on its subject.</p>
</div>
<div class="groups">
{"".join(cards)}
</div>
</div>
<script>
// The docs were one page; a link to one of its headings opens the page that has it now.
const moved = {json.dumps(moved, sort_keys=True)};
const anchor = decodeURIComponent(location.hash.slice(1));
if (Object.hasOwn(moved, anchor)) location.replace(moved[anchor]);
</script>"""


def docs_page(page: Page, pages: list[Page], located: dict[str, str]) -> str:
    index = pages.index(page)
    previous = pages[index - 1] if index else None
    following = pages[index + 1] if index + 1 < len(pages) else None
    siblings = "\n".join(
        f'<a href="{other.url}"{marked(other is page)}>{html.escape(other.title)}</a>'
        for other in pages
        if other.group == page.group
    )
    after = agent_reads(page) + pager(previous, following)
    return f"""<div class="frame docs">
<div class="controls">
<nav class="tabs" aria-label="Docs">
{groups_nav(page.group)}
</nav>
<nav class="pages" aria-label="{GROUPS[page.group]}">
{siblings}
</nav>
</div>
{article(page, located, after)}
</div>"""


# --- the frame and the story pages ----------------------------------------------------------------


def menu(current: str) -> str:
    items = [("Home", "/"), ("About", "/about/"), ("Get started", "/getting-started/")]
    links = [f'<a href="{path}"{marked(path == current)}>{name}</a>' for name, path in items]
    links.append(f'<a href="/docs/"{marked(current == "/docs/")}>Docs</a>')
    icons = f'<a class="icon" href="{GITHUB}" aria-label="nock on GitHub" title="GitHub">{ICONS["github"]}</a>'
    return "\n".join(links) + f'\n<span class="icons">{icons}</span>'


def layout(url: str, title: str, description: str, current: str, main: str, head: str = "") -> str:
    """A page in the site's frame, served at `url`: the band with the menu, the main column, the
    footer."""
    return (
        LAYOUT.read_text()
        .replace("{{ title }}", html.escape(title))
        .replace("{{ description }}", html.escape(description))
        .replace("{{ seo }}", seo_head(url) + "\n" + social_head(url, title, description))
        .replace("{{ head }}", head)
        .replace("{{ menu }}", menu(current))
        .replace("{{ main }}", main)
        .replace("{{ github }}", GITHUB)
    )


def blocks() -> dict[str, str]:
    """landing/copy.html's blocks by name: the words the story pages share."""
    text = (LANDING / "copy.html").read_text()
    return dict(re.findall(r"<!-- block (\S+) -->\n(.*?)\n<!-- end -->", text, re.S))


PLACEHOLDER = re.compile(r"\{\{ (copy|url):(\S+) \}\}")


def story_page(path: str, copy: dict[str, str]) -> str:
    """A story page: its template with the shared words and the addresses filled in."""
    name = STORY[path][2]
    filled = (LANDING / f"{name}.html").read_text()

    def fill(match: re.Match[str]) -> str:
        kind, key = match.group(1), match.group(2)
        if kind == "url":
            return key
        if key not in copy:
            raise SystemExit(f"web/landing/{name}.html names `{key}`, no block of copy.html")
        return copy[key]

    # A block may name addresses and other blocks, so fill until nothing is left.
    while PLACEHOLDER.search(filled):
        filled = PLACEHOLDER.sub(fill, filled)
    return filled.replace("{{ github }}", GITHUB).replace("{{ logika }}", LOGIKA)


STORY_HEAD = (
    '<link rel="stylesheet" href="/studio/topics.css">\n'
    '<link rel="stylesheet" href="/demo.css">\n'
    '<script src="/demo.js" defer></script>'
)


def legal_page(name: str) -> tuple[str, str]:
    """The page's title, and its main: the title with the switch at the right end of its line, the
    summary alone while the switch is on (the default), the full text alone while it is off; without
    script, both."""
    text = (HERE / "legal" / f"{name}.md").read_text()
    title = re.match(r"# (.+)\n", text)
    assert title, f"legal/{name}.md starts with its title"
    body = Converter(text).convert()
    heading, rest = body.split("\n", 1)
    summary = Converter((HERE / "legal" / f"{name}-plain.md").read_text()).convert()
    main = f"""<div class="frame legal">
<article class="card article">
<div class="legal-head">
{heading}
<div class="tldr-control" hidden><button type="button" class="switch" role="switch" id="tldr" aria-checked="true"><span></span></button><label for="tldr">TL;DR</label></div>
</div>
<section class="plain" aria-label="TL;DR">
{summary}
<p class="note">In short. The full text is the one that applies: turn TL;DR off to read it.</p>
</section>
<section class="full" aria-label="{html.escape(title.group(1))}">
{rest}
</section>
</article>
</div>
<script>
// The summary is on unless the visitor turned it off; only turning it off is kept, in their browser.
const control = document.querySelector(".tldr-control");
const toggle = document.getElementById("tldr");
const root = document.documentElement;
root.dataset.tldr = root.dataset.tldr === "off" ? "off" : "on";
control.hidden = false;
toggle.setAttribute("aria-checked", String(root.dataset.tldr === "on"));
toggle.addEventListener("click", () => {{
  const on = root.dataset.tldr !== "on";
  root.dataset.tldr = on ? "on" : "off";
  toggle.setAttribute("aria-checked", String(on));
  try {{
    if (on) localStorage.removeItem({json.dumps(TLDR_KEY)});
    else localStorage.setItem({json.dumps(TLDR_KEY)}, "off");
  }} catch {{}}
}});
</script>"""
    return title.group(1), main


# --- what crawlers and LLMs read: canonicals, JSON-LD, the sitemap, robots.txt, llms.txt --------

ORIGIN = "https://nock.dev"
COMPANY = "Parallel Labs, S.L."
CONTACT = "support@logika.host"
ORGANIZATION = {
    "@context": "https://schema.org",
    "@type": "Organization",
    "@id": f"{ORIGIN}/#organization",
    "name": COMPANY,
    "url": f"{ORIGIN}/",
    "email": CONTACT,
    "sameAs": ["https://github.com/logika-labs", LOGIKA],
}


def software() -> dict[str, object]:
    """nock as an open-source dev tool, free, MIT licensed, on PyPI."""
    return {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "nock",
        "url": f"{ORIGIN}/",
        "description": TAGLINE,
        "applicationCategory": "DeveloperApplication",
        "operatingSystem": "macOS, Linux",
        "license": "https://opensource.org/licenses/MIT",
        "isAccessibleForFree": True,
        "downloadUrl": "https://pypi.org/project/nock/",
        "installUrl": f"{ORIGIN}/getting-started/",
        "sameAs": GITHUB,
        "author": {"@id": ORGANIZATION["@id"]},
        "publisher": {"@id": ORGANIZATION["@id"]},
        "offers": {"@type": "Offer", "price": 0, "priceCurrency": "USD"},
    }


def structured_data(url: str) -> list[dict[str, object]]:
    """The JSON-LD a page carries: the maker on every page, and nock itself on the landing page."""
    return [ORGANIZATION, software()] if url == "/" else [ORGANIZATION]


def seo_head(url: str) -> str:
    """The page's canonical link and its JSON-LD, `<` escaped so no string closes the script."""
    scripts = [
        '<script type="application/ld+json">'
        + json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
        + "</script>"
        for data in structured_data(url)
    ]
    return "\n".join([f'<link rel="canonical" href="{ORIGIN}{url}">', *scripts])


# The preview a link to any page shows: the owner's art, cropped to 1200x630 from its 16:9 original
# around the large creature at the bottom left and the one at the top right.
OG_IMAGE = "/og.jpg"
OG_IMAGE_SIZE = (1200, 630)
OG_IMAGE_ALT = (
    "nock's pixel creatures, chunky black blocks with foil eyes, floating over an iridescent foil "
    "field on black halftone."
)


def social_head(url: str, title: str, description: str) -> str:
    """The OpenGraph and Twitter tags a shared link is previewed from: the page's own title,
    description and canonical address, and the site's one image."""
    width, height = OG_IMAGE_SIZE
    tags = [
        ("property", "og:type", "website"),
        ("property", "og:site_name", "nock"),
        ("property", "og:title", title),
        ("name", "twitter:title", title),
        ("property", "og:description", description),
        ("property", "og:url", f"{ORIGIN}{url}"),
        ("property", "og:image", f"{ORIGIN}{OG_IMAGE}"),
        ("property", "og:image:width", str(width)),
        ("property", "og:image:height", str(height)),
        ("property", "og:image:alt", OG_IMAGE_ALT),
        ("name", "twitter:card", "summary_large_image"),
        ("name", "twitter:image:alt", OG_IMAGE_ALT),
    ]
    return "\n".join(
        f'<meta {kind}="{name}" content="{html.escape(value)}">' for kind, name, value in tags
    )


def last_changed(sources: list[Path], today: str) -> str:
    """The day the sources last changed in git, or `today` for sources not yet committed."""
    found = subprocess.run(
        ["git", "log", "-1", "--format=%cs", "--", *(str(path) for path in sources)],
        cwd=HERE,
        capture_output=True,
        text=True,
    )
    return found.stdout.strip() or today


def sitemap(lastmod: dict[str, str]) -> str:
    urls = "".join(
        f"  <url>\n    <loc>{ORIGIN}{url}</loc>\n    <lastmod>{day}</lastmod>\n  </url>\n"
        for url, day in lastmod.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}</urlset>\n"
    )


def robots() -> str:
    return f"User-agent: *\nAllow: /\n\nSitemap: {ORIGIN}/sitemap.xml\n"


def bare(title: str) -> str:
    return title.removesuffix(" · nock")


def llms(pages: list[Page]) -> str:
    """llmstxt.org: an H1, a blockquote summary, then sections of links with a line each."""
    sections = [
        (
            "Start",
            [
                f"- [{bare(title) if path != '/' else 'What nock is'}]({ORIGIN}{path}): {description}"
                for path, (title, description, _) in STORY.items()
            ],
        ),
        *(
            (
                f"Docs: {name}",
                [
                    f"- [{page.title}]({ORIGIN}{page.url}): {page.description}"
                    for page in pages
                    if page.group == group
                ],
            )
            for group, name in GROUPS.items()
        ),
        (
            "Legal",
            [f"- [{legal_title(name)}]({ORIGIN}/{name}/): {line}" for name, line in LEGAL.items()],
        ),
        (
            "Optional",
            [
                f"- [Everything above in one file]({ORIGIN}/llms-full.txt): every guide and every term, as Markdown.",
                f"- [Source]({GITHUB}): nock's repository on GitHub, MIT licensed.",
            ],
        ),
    ]
    lines = [
        "# nock",
        "",
        f"> {STORY['/'][1]}",
        "",
        f"nock is open source under the MIT License, standard-library Python with no dependencies, "
        f"vendored into the repository that uses it: `uvx nock init`. Made by {COMPANY} for Claude Code; "
        f"contact {CONTACT}.",
        "",
    ]
    for title, links in sections:
        lines += [f"## {title}", "", *links, ""]
    return "\n".join(lines)


def absolute_links(text: str, here: str, located: dict[str, str]) -> str:
    """A guide's Markdown links made absolute, outside its code: a heading on any page, a page of
    the site, a file of the repository."""

    def target(match: re.Match[str]) -> str:
        label, where = match.group(1), match.group(2)
        if where.startswith("#"):
            where = ORIGIN + located.get(where[1:], here + where)
        elif where.startswith("/"):
            where = ORIGIN + where
        elif not re.match(r"[a-z]+:", where):
            where = REPOSITORY + where
        return f"[{label}]({where})"

    parts = re.split(r"(```.*?```|`[^`\n]*`)", text, flags=re.S)
    return "".join(
        part if index % 2 else re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", target, part)
        for index, part in enumerate(parts)
    )


def llms_full(docs: Docs, pages: list[Page], located: dict[str, str]) -> str:
    """The guides and the terms as Markdown in one file, from the same sources the pages are."""
    found = guides(docs)
    out = ["# nock", "", f"> {STORY['/'][1]}", ""]
    for page in pages:
        out += [f"# {page.title}", "", f"Source: {ORIGIN}{page.url}", ""]
        if page.name == "terms":
            out += [TERMS_PAGE[1], ""]
            for term in short_terms(docs):
                article = absolute_links(term.article.strip(), page.url, located)
                out += [f"## nock docs {term.term}", "", term.description, "", article, ""]
            continue
        article = re.sub(r"\A# .*\n+", "", found[page.name].article.strip())
        out += [absolute_links(article, page.url, located), ""]
    return "\n".join(out)


def legal_title(name: str) -> str:
    return (HERE / "legal" / f"{name}.md").read_text().splitlines()[0].removeprefix("# ")


def build(site: Path, terms: Path | None = None, today: str | None = None) -> list[Path]:
    """Write every page under `site`, and what crawlers read beside them; the files written. A
    page's sitemap date is the day its sources last changed in git, `today` (the build's day by
    default) for sources not yet committed."""
    terms = terms or TERMS
    today = today or date.today().isoformat()
    docs = Docs(terms)
    pages = docs_pages(docs)
    located: dict[str, str] = {}
    for page in pages:
        for anchor in re.findall(r'<h\d id="([^"]+)"', page.body):
            whole = anchor == slug(page.title)
            located.setdefault(anchor, page.url if whole else f"{page.url}#{anchor}")
    copy = blocks()
    written: dict[str, str] = {}
    sources: dict[str, list[Path]] = {}
    for path, (title, description, template) in STORY.items():
        relative = path.lstrip("/") + "index.html"
        written[relative] = layout(
            path, title, description, path, story_page(path, copy), STORY_HEAD
        )
        sources[path] = [LANDING / f"{template}.html", LANDING / "copy.html"]
    sources["/docs/"] = [terms / "guides"]
    written["docs/index.html"] = layout(
        "/docs/",
        "Docs · nock",
        "nock's documentation, by what you are doing: start, every day, extending, and the reference.",
        "/docs/",
        docs_index(pages, located),
    )
    for page in pages:
        written[f"docs/{page.name}/index.html"] = layout(
            page.url,
            f"{page.title} · nock",
            page.description,
            "/docs/",
            docs_page(page, pages, located),
        )
        guide = [terms / "guides" / f"guide.{page.name}.md"] if page.name != "terms" else [terms]
        sources[page.url] = [
            *guide,
            *(path for term in page.reads for path in terms.rglob(f"{term.term}.md")),
        ]
    for name, description in LEGAL.items():
        title, main = legal_page(name)
        head = (
            f'<script>try {{ if (localStorage.getItem({json.dumps(TLDR_KEY)}) === "off") '
            'document.documentElement.dataset.tldr = "off"; } catch {}</script>'
        )
        written[f"{name}/index.html"] = layout(
            f"/{name}/", f"{title} · nock", description, "", main, head
        )
        sources[f"/{name}/"] = [HERE / "legal" / f"{name}.md", HERE / "legal" / f"{name}-plain.md"]
    written["robots.txt"] = robots()
    written["sitemap.xml"] = sitemap(
        {url: last_changed(paths, today) for url, paths in sources.items()}
    )
    written["llms.txt"] = llms(pages)
    written["llms-full.txt"] = llms_full(docs, pages, located)
    paths = []
    for relative, text in written.items():
        path = site / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        paths.append(path)
    # The demo's Work scene is drawn in the studio's own classes, so it wears the studio's own sheet.
    (site / "studio").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(STUDIO / "topics.css", site / "studio" / "topics.css")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--site", type=Path, default=SITE, help="where to write the pages")
    arguments = parser.parse_args()
    for path in build(arguments.site):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
