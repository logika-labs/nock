"""Build nock.dev's documentation from the repository's README — the product's
documentation, kept true beside the code — into `site/docs/index.html`, in the
site's look, with a table of contents; and the legal pages from `legal/` into
`site/privacy/` and `site/terms/`. Standard library only.

    python3 web/build.py [--output PATH]
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
README = HERE.parent / "README.md"
TEMPLATE = HERE / "docs.html"
OUTPUT = HERE / "site" / "docs" / "index.html"
PAGE = HERE / "page.html"
# Each legal page: its source in legal/, its description, and where it is served.
LEGAL = {
    "privacy": "What reaches nock's makers from nock.dev and from nock: the usage report, shared summaries, reports you write, and your rights.",
    "terms": "The terms of nock.dev and api.nock.dev; the software itself is MIT licensed.",
}
REPOSITORY = "https://github.com/logika-labs/nock/blob/main/"


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


def build(readme: Path, output: Path) -> int:
    """Write the documentation page to `output`; the number of headings."""
    text = readme.read_text()
    # The README's title and tagline are the page's own.
    text = re.sub(r"\A# nock\n+.*?\n+", "", text, count=1, flags=re.S)
    converter = Converter(text)
    body = converter.convert()
    contents = "\n".join(
        f'<a class="level-{level}" href="#{anchor}">{text}</a>'
        for level, anchor, text in converter.headings
        if level <= 3
    )
    page = TEMPLATE.read_text().replace("{{ contents }}", contents).replace("{{ body }}", body)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page)
    return len(converter.headings)


def build_legal(site: Path) -> list[Path]:
    """Write each legal page to `site/NAME/index.html`; the pages written."""
    written = []
    for name, description in LEGAL.items():
        text = (HERE / "legal" / f"{name}.md").read_text()
        title = re.match(r"# (.+)\n", text)
        assert title, f"legal/{name}.md starts with its title"
        page = (
            PAGE.read_text()
            .replace("{{ title }}", html.escape(title.group(1).lower()))
            .replace("{{ description }}", html.escape(description))
            .replace("{{ body }}", Converter(text).convert())
        )
        output = site / name / "index.html"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(page)
        written.append(output)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, default=OUTPUT, help="where to write the page")
    arguments = parser.parse_args()
    headings = build(README, arguments.output)
    print(f"wrote {arguments.output}: {headings} headings")
    for page in build_legal(arguments.output.parent.parent):
        print(f"wrote {page}")


if __name__ == "__main__":
    main()
