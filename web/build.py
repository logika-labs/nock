"""Build nock.dev into `site/`: the home page from `home.html`; Getting started
and the docs from the repository's README, the product's documentation kept
true beside the code, one page per section, each with its own table of
contents; the legal pages from `legal/`, each with its plain-words summary.
Every page is set in `layout.html`. Standard library only.

    python3 web/build.py [--site DIRECTORY]
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import NamedTuple

HERE = Path(__file__).resolve().parent
README = HERE.parent / "README.md"
SITE = HERE / "site"
LAYOUT = HERE / "layout.html"
HOME = HERE / "home.html"
GITHUB = "https://github.com/logika-labs/nock"
REPOSITORY = GITHUB + "/blob/main/"
# PLACEHOLDER: the community's Telegram channel, which the owner is creating. Replace this one line.
TELEGRAM = "https://t.me/PLACEHOLDER"

# The README's sections by their anchors: Getting started is a page of its own, Thanks stays on
# PyPI, and every other section is a docs page, served at /docs/ANCHOR/, in its tab, in reading
# order, with its line on the docs index. A section the README gains and this does not place fails
# the build.
START = "getting-started"
LEFT_OUT = {"thanks"}
TABS = {"concepts": "Concepts", "evaluation": "Evaluation", "reference": "Reference"}
DOCS = {
    "why": (
        "concepts",
        "Agents repeat themselves and prose goes stale: why nock's fix is code, and its three principles.",
    ),
    "a-tool": (
        "concepts",
        "A tool is a function; nock owns its arguments, output, exit codes and help. The project's environment, long-running commands, checks, hooks and generators.",
    ),
    "what-agents-see": (
        "concepts",
        "The tools listed at every session's start, the primer, and the few things nock says unasked.",
    ),
    "telemetry": (
        "concepts",
        "Every call and session in a local SQLite file, never committed, and how to read it.",
    ),
    "topics": (
        "concepts",
        "Agents put their work before you in topics: decisions, project files, what they made to show it. You accept or reject each and talk in its thread. The map, and consulting before a change.",
    ),
    "reflection": (
        "concepts",
        "Rounds that read the record and improve the toolbox, keep the map and judge how nock is doing; the logika round.",
    ),
    "what-nocks-agents-may-do": (
        "concepts",
        "The permissions nock writes, and what its own agents may and may not do.",
    ),
    "what-nock-shares": (
        "concepts",
        "Nothing without your yes: the weekly usage report, a round's summary, and telling nock's makers what you need.",
    ),
    "evaluations": (
        "evaluation",
        "Whether a change makes the agents better, answered with real runs: Snakemake scenarios, a provenance cache, SQL and comparisons.",
    ),
    "reference": ("reference", "Every command, the exit codes and the settings."),
    "developing-nock": (
        "reference",
        "Working on nock itself: the tests, the gate and how a release goes.",
    ),
}
# Each legal page: its source in legal/ (and its plain-words summary, NAME-plain.md), its description.
LEGAL = {
    "privacy": "What reaches nock's makers from nock.dev and from nock: the usage report, shared summaries, reports you write, and your rights.",
    "terms": "The terms of nock.dev and api.nock.dev; the software itself is MIT licensed.",
}
# The visitor's choice of the legal pages' summary, kept in their browser only.
TLDR_KEY = "nock.legal.tldr"


def slug(text: str) -> str:
    """GitHub's anchor for a heading, so the README's own links land."""
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


class Converter:
    """The Markdown nock's README uses: headings, paragraphs, nested lists,
    fenced code, tables, block quotes."""

    def __init__(self, text: str, offset: int = 0) -> None:
        self.lines = text.replace("\r", "").split("\n")
        self.index = 0
        # A README section is a page of its own, so its "## " is the page's <h1>.
        self.offset = offset
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
                self.index += 1
                code = []
                while self.index < len(self.lines) and not self.lines[
                    self.index
                ].strip().startswith("```"):
                    code.append(self.lines[self.index][indent:])
                    self.index += 1
                self.index += 1
                out.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
                continue
            heading = re.match(r"(#{1,4})\s+(.*)", line)
            if heading and not indent:
                flush()
                level = max(1, len(heading.group(1)) - self.offset)
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
            cells = [cell.strip() for cell in self.lines[self.index].strip().strip("|").split("|")]
            rows.append(cells)
            self.index += 1
        head, body = rows[0], [row for row in rows[2:]]
        out = ['<div class="table"><table><thead><tr>']
        out += [f"<th>{inline(cell)}</th>" for cell in head]
        out.append("</tr></thead><tbody>")
        for row in body:
            out.append("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>")
        out.append("</tbody></table></div>")
        return "".join(out)


class Section(NamedTuple):
    """A "## " section of the README: its anchor, its title and its Markdown."""

    anchor: str
    title: str
    text: str


class Page(NamedTuple):
    """A page made from a section: where it is served, its body and its table of contents."""

    section: Section
    url: str
    body: str
    contents: str


def sections(text: str) -> list[Section]:
    """The README cut at its "## " headings, outside code; the title and tagline before the first
    are the site's own."""
    found: list[Section] = []
    fenced = False
    current: list[str] | None = None
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            current = [line]
            title = line.removeprefix("## ").strip()
            found.append(Section(slug(title), title, ""))
        elif current is not None:
            current.append(line)
        if current is not None:
            found[-1] = found[-1]._replace(text="\n".join(current))
    return found


def placed(found: list[Section]) -> dict[str, Section]:
    """The sections by anchor, every one placed: a page, Getting started, or left out."""
    by_anchor = {section.anchor: section for section in found}
    unplaced = set(by_anchor) - set(DOCS) - LEFT_OUT - {START}
    missing = (set(DOCS) | {START}) - set(by_anchor)
    if unplaced or missing:
        raise SystemExit(
            "web/build.py places the README's sections by anchor: "
            + "; ".join(
                [f"{anchor} is not placed (DOCS, START or LEFT_OUT)" for anchor in sorted(unplaced)]
                + [f"{anchor} is not in the README" for anchor in sorted(missing)]
            )
        )
    return by_anchor


def render(section: Section, url: str) -> Page:
    converter = Converter(section.text, offset=1)
    body = converter.convert()
    links = "\n".join(
        f'<a class="level-{level}" href="#{anchor}">{text}</a>'
        for level, anchor, text in converter.headings
        if level in (2, 3)
    )
    contents = (
        f'<nav class="contents" aria-label="On this page"><span class="label">On this page</span>\n{links}\n</nav>'
        if links
        else ""
    )
    return Page(section, url, body, contents)


def relink(text: str, here: str, located: dict[str, str]) -> str:
    """Point a README link to a section on another page at that page."""

    def target(match: re.Match[str]) -> str:
        anchor = match.group(1)
        where = located.get(anchor)
        if where is None or where.split("#")[0] == here:
            return match.group(0)
        return f'href="{where}"'

    return re.sub(r'href="#([^"]+)"', target, text)


def marked(current: bool) -> str:
    return ' aria-current="page"' if current else ""


def menu(current: str) -> str:
    items = [("Start", "/getting-started/"), ("Docs", "/docs/"), ("GitHub", GITHUB)]
    return "\n".join(
        f'<a href="{href}"{marked(href == current)}>{name}</a>' for name, href in items
    )


def layout(title: str, description: str, current: str, main: str, head: str = "") -> str:
    """A page in the site's frame: the band with the menu, the main column, the footer."""
    return (
        LAYOUT.read_text()
        .replace("{{ title }}", html.escape(title))
        .replace("{{ description }}", html.escape(description))
        .replace("{{ head }}", head)
        .replace("{{ menu }}", menu(current))
        .replace("{{ main }}", main)
        .replace("{{ telegram }}", TELEGRAM)
    )


def plain(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def pager(previous: Page | None, following: Page | None) -> str:
    links = []
    if previous:
        links.append(
            f'<a class="previous" href="{previous.url}"><span class="label">Previous</span>{previous.section.title}</a>'
        )
    if following:
        links.append(
            f'<a class="next" href="{following.url}"><span class="label">Next</span>{following.section.title}</a>'
        )
    return f'<nav class="pager" aria-label="Pages">{"".join(links)}</nav>' if links else ""


def article(page: Page, located: dict[str, str], after: str) -> str:
    body = relink(page.body, page.url, located)
    heading, rest = body.split("\n", 1) if "\n" in body else (body, "")
    return (
        f'<article class="card article">\n{heading}\n{page.contents}\n{rest}\n{after}\n</article>'
    )


def tabs(current: str | None) -> str:
    return "\n".join(
        f'<a href="/docs/#{tab}" data-tab="{tab}"{marked(tab == current)}>{title}</a>'
        for tab, title in TABS.items()
    )


def docs_index(pages: list[Page], located: dict[str, str]) -> str:
    """Every tab in the markup, the one the address names shown (style.css), the first when it
    names none; an address naming a heading of the old one-page docs goes to its page."""
    anchors = "".join(f'<span id="{tab}" data-anchor="{tab}" hidden></span>' for tab in TABS)
    panels = []
    for number, tab in enumerate(TABS):
        entries = "\n".join(
            f'<li><span class="number">{index:02}</span><div><a href="{page.url}">{page.section.title}</a>'
            f"<p>{html.escape(DOCS[page.section.anchor][1])}</p></div></li>"
            for index, page in enumerate(
                (page for page in pages if DOCS[page.section.anchor][0] == tab), start=1
            )
        )
        default = " data-default" if number == 0 else ""
        panels.append(
            f'<section class="panel" data-panel="{tab}"{default} aria-label="{TABS[tab]}"><ol class="entries">\n{entries}\n</ol></section>'
        )
    moved = {anchor: where for anchor, where in located.items() if anchor not in TABS}
    return f"""<div class="frame docs" data-docs-index>
{anchors}
<div class="controls"><nav class="tabs" aria-label="Docs">
{tabs(None).replace('href="/docs/#', 'href="#')}
</nav></div>
<div class="card">
<h1>Docs</h1>
{"".join(panels)}
</div>
</div>
<script>
// The docs were one page; a link to one of its headings opens the page that has it now.
const moved = {json.dumps(moved, sort_keys=True)};
const anchor = decodeURIComponent(location.hash.slice(1));
if (Object.hasOwn(moved, anchor)) location.replace(moved[anchor]);
</script>"""


def docs_page(page: Page, pages: list[Page], located: dict[str, str]) -> str:
    tab = DOCS[page.section.anchor][0]
    index = pages.index(page)
    previous = pages[index - 1] if index else None
    following = pages[index + 1] if index + 1 < len(pages) else None
    siblings = "\n".join(
        f'<a href="{other.url}"{marked(other is page)}>{other.section.title}</a>'
        for other in pages
        if DOCS[other.section.anchor][0] == tab
    )
    return f"""<div class="frame docs">
<div class="controls">
<nav class="tabs" aria-label="Docs">
{tabs(tab)}
</nav>
<nav class="pages" aria-label="{TABS[tab]}">
{siblings}
</nav>
</div>
{article(page, located, pager(previous, following))}
</div>"""


def legal_page(name: str) -> tuple[str, str]:
    """The page's title, and its main: the switch, the title, the summary (shown while the switch is
    on) and the full text, which is always shown and never changes with it."""
    text = (HERE / "legal" / f"{name}.md").read_text()
    title = re.match(r"# (.+)\n", text)
    assert title, f"legal/{name}.md starts with its title"
    body = Converter(text).convert()
    heading, rest = body.split("\n", 1)
    summary = Converter((HERE / "legal" / f"{name}-plain.md").read_text()).convert()
    main = f"""<div class="frame legal">
<article class="card article">
<div class="tldr-control" hidden><button type="button" class="switch" role="switch" id="tldr" aria-checked="true"><span></span></button><label for="tldr">tl;dr</label></div>
{heading}
<section class="plain" aria-label="tl;dr">
<p class="note">A summary in plain words. The full text below is the one that applies; where the two differ, the full text applies.</p>
{summary}
</section>
<section class="full" aria-label="{html.escape(title.group(1))}">
{rest}
</section>
</article>
</div>
<script>
// The summary is on unless the visitor turned it off; the choice stays in their browser.
const control = document.querySelector(".tldr-control");
const toggle = document.getElementById("tldr");
const shown = () => document.documentElement.dataset.tldr !== "off";
control.hidden = false;
toggle.setAttribute("aria-checked", String(shown()));
toggle.addEventListener("click", () => {{
  const on = !shown();
  document.documentElement.dataset.tldr = on ? "on" : "off";
  toggle.setAttribute("aria-checked", String(on));
  try {{ localStorage.setItem({json.dumps(TLDR_KEY)}, on ? "on" : "off"); }} catch {{}}
}});
</script>"""
    return title.group(1), main


def build(site: Path, readme: Path = README) -> list[Path]:
    """Write every page under `site`; the pages written."""
    by_anchor = placed(sections(readme.read_text()))
    start = render(by_anchor[START], "/getting-started/")
    pages = [render(by_anchor[anchor], f"/docs/{anchor}/") for anchor in DOCS]
    located: dict[str, str] = {}
    for page in [start, *pages]:
        for anchor in re.findall(r'<h\d id="([^"]+)"', page.body):
            located.setdefault(
                anchor, page.url if anchor == page.section.anchor else f"{page.url}#{anchor}"
            )
    written: dict[str, str] = {
        "index.html": layout(
            "nock",
            "nock is a community learning to work with AI as software engineers, and the open-source toolbox they learn with: reflection, review, evaluation, and Logika.",
            "/",
            HOME.read_text(),
        ),
        "getting-started/index.html": layout(
            "Getting started · nock",
            "Install nock in a repository, commit it, and make your tests and linters its checks.",
            "/getting-started/",
            f'<div class="frame docs">\n{article(start, located, pager(None, pages[0]))}\n</div>',
        ),
        "docs/index.html": layout(
            "Docs · nock",
            "nock's documentation, built from its README: concepts, evaluation and reference.",
            "/docs/",
            docs_index(pages, located),
        ),
    }
    for page in pages:
        written[f"docs/{page.section.anchor}/index.html"] = layout(
            f"{plain(page.section.title)} · nock",
            DOCS[page.section.anchor][1],
            "/docs/",
            docs_page(page, pages, located),
        )
    for name, description in LEGAL.items():
        title, main = legal_page(name)
        head = (
            f'<script>try {{ if (localStorage.getItem({json.dumps(TLDR_KEY)}) === "off") '
            'document.documentElement.dataset.tldr = "off"; } catch {}</script>'
        )
        written[f"{name}/index.html"] = layout(f"{title} · nock", description, "", main, head)
    paths = []
    for relative, text in written.items():
        path = site / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--site", type=Path, default=SITE, help="where to write the pages")
    arguments = parser.parse_args()
    for path in build(arguments.site):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
