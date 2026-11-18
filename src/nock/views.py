"""The readable views: each topic folded into markdown in
`.nock/local/views/<topic>.md` — its decisions and proposals, its assets with
each version's file, its review's blocks, the chat and the owner's notes —
and `index.md` listing them in the owner's order, written after every change
to the store. Agents read these to see a topic at once; they write events
(`nock docs files`)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock.topics import Topics, entry_name, talk, target_of
from nock.utils import write_atomic

if TYPE_CHECKING:
    from nock.project import Project

VIEWS = "views"
INDEX = "index.md"


def one_line(text: str) -> str:
    return " ".join(str(text or "").split())


class Views:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.topics = Topics(project)
        self.directory: Path = project.local / VIEWS

    def write(self, names: set[str] | None = None) -> list[Path]:
        """Write the views of these topics (all, without names) and the index;
        a view of a topic no longer there is removed."""
        present = set(self.topics.names())
        written = []
        for name in sorted(present if names is None else names & present):
            path = self.directory / f"{name}.md"
            write_atomic(path, self.topic(name))
            written.append(path)
        if self.directory.is_dir():
            for path in self.directory.glob("*.md"):
                if path.name != INDEX and path.stem not in present:
                    path.unlink()
        write_atomic(self.directory / INDEX, self.index())
        return written

    def index(self) -> str:
        lines = ["# Topics", ""]
        for row in self.topics.rows():
            status = f" — {row['status']}" if row.get("status") else ""
            waits = []
            if row["for_owner"]:
                waits.append(f"{len(row['for_owner'])} for the owner")
            if row["for_agent"]:
                waits.append(f"for agents: {', '.join(row['for_agent'])}")
            lines.append(
                f"- [{row['name']}]({row['name']}.md) ({row['state']}{status}):"
                f" {row['decisions']} decisions, {row['proposals']} proposals,"
                f" {row['assets']} assets" + (f"; {'; '.join(waits)}" if waits else "")
            )
        return "\n".join(lines) + "\n"

    def topic(self, name: str) -> str:
        topics = self.topics
        topic = topics.topic(name)
        row = topics.row(name)
        status = f": {topic['status']}" if topic.get("status") else ""
        lines = [f"# {name}", "", f"{topic['state']}{status}", "", row["description"], ""]
        items = topics.items(name)
        for heading, wanted in (
            ("Decisions", ("decision",)),
            ("Proposals", ("open", "accepted")),
            ("Rejected proposals", ("rejected",)),
        ):
            chosen = [item for item in items if item["status"] in wanted]
            if not chosen:
                continue
            lines += [f"## {heading}", ""]
            for item in chosen:
                mark = "" if item["status"] == "decision" else f" ({item['status']})"
                lines.append(f"- [{item['ref']}]{mark} {item['title']}")
                lines.append(f"  {one_line(item['means'])}")
                if item["why"]:
                    lines.append(f"  Why: {one_line(item['why'])}")
                if item["takes"] and item["status"] != "decision":
                    lines.append(f"  Takes: {one_line(item['takes'])}")
            lines.append("")
        assets = topics.assets(name)
        if assets:
            lines += ["## Assets", ""]
            for asset in assets:
                lines.append(f"- {asset['name']}: {asset['title']}")
                for version in asset["versions"]:
                    where = topics.located(name, asset["name"], version)
                    file = entry_name(version["file"])
                    lines.append(f"  - v{version['version']} {file}: {where}")
            lines.append("")
        plan = row["progress"]
        if plan:
            lines += [
                f"## Plan: {plan['done']} of {len(plan['steps'])} steps, about {plan['left']} min left",
                "",
            ]
            for step in plan["steps"]:
                mark = "x" if step["done"] else ">" if step["started"] else " "
                actual = f", took {step['actual']}" if step["actual"] is not None else ""
                lines.append(
                    f"- [{mark}] {step['title']} (estimate {step['estimate']} min{actual})"
                )
            lines.append("")
        review = topics.current_review(name)
        if review:
            done = " (the owner is done with it)" if topics.reviewed(topic) else ""
            lines += [f"## Review, version {review['version']}{done}", "", review["summary"], ""]
            for block in review["blocks"]:
                lines.append(f"- {block['id']} {block['kind']}: {block_line(block)}")
            lines.append("")
        unsent = topics.unsent(topic)
        if unsent:
            lines += ["## The owner's notes, not sent yet", ""]
            for note in unsent:
                lines.append(f"- on {target_of(note, review)}: {one_line(note['text'])}")
            lines.append("")
        said = talk(topic["thread"])
        if said:
            lines += ["## Chat", ""]
            for entry in said:
                text = one_line(entry.get("text") or "")
                lines.append(f"> {entry['author']}, {entry['moment']}: {text}")
                for note in topics.carried(topic, entry):
                    lines.append(f">   note on {note['target']}: {one_line(note['text'])}")
                for file in topics.attached(entry):
                    lines.append(f">   attached: {file}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def block_line(block: dict[str, Any]) -> str:
    kind = block["kind"]
    if kind == "text":
        text = one_line(block.get("text") or "")
        return text if len(text) <= 160 else text[:159] + "…"
    if kind == "item":
        return block["item"]
    if kind == "html":
        return block["file"]
    if kind in ("table", "chart"):
        return one_line(block.get("title") or block.get("caption") or kind)
    versions = ""
    if kind == "diff":
        versions = f" v{block.get('from', '?')}→v{block.get('to', 'latest')}"
    elif kind == "excerpt":
        versions = f" lines {block['lines'][0]}–{block['lines'][1]}"
    return f"{block['asset']}{versions}"
