"""The readable views: each topic folded into markdown in
`.nock/local/views/<topic>.md`, and `index.md` listing them in the owner's
order, written after every change to the store. Agents read these to see a
topic at once; they write events (`nock docs files`)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock.topics import Topics, in_order, latest_files, talk
from nock.utils import write_atomic

if TYPE_CHECKING:
    from nock.project import Project

VIEWS = "views"
INDEX = "index.md"
# How much of a decision's answer the view shows.
GIST = 600


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
        rows = in_order([self.topics.row(name) for name in self.topics.names()])
        lines = ["# Topics", ""]
        for row in rows:
            status = f" — {row['status']}" if row.get("status") else ""
            lines.append(
                f"- [{row['name']}]({row['name']}.md) ({row['state']}{status}):"
                f" {row['open']} open, {row['accepted']} accepted, {row['rejected']} rejected"
            )
        return "\n".join(lines) + "\n"

    def topic(self, name: str) -> str:
        topic = self.topics.topic(name)
        status = f": {topic['status']}" if topic.get("status") else ""
        lines = [
            f"# {name}",
            "",
            f"{topic['state']}{status}",
            "",
            self.topics.current_description(topic),
            "",
        ]
        for item in self.topics.items(name):
            shown = self.topics.shown(item)
            lines += [f"## {item['title']} [{item['ref']}] — {item['verdict']}", ""]
            if item.get("description"):
                lines += [item["description"], ""]
            decision = shown["versions"][-1]["decision"] if shown["versions"] else None
            if decision:
                answer = decision["answer"]
                gist = answer if len(answer) <= GIST else answer[: GIST - 1] + "…"
                lines += [gist, ""]
            for asset in shown["assets"]:
                version = asset["versions"][-1]["version"] if asset["versions"] else 0
                lines.append(f"- asset {asset['name']} (version {version}): {asset['title']}")
                lines += [f"  - {entry['name']}: {entry['where']}" for entry in latest_files(asset)]
            if shown["assets"]:
                lines.append("")
            lines += self.thread(shown["thread"])
        lines += ["## Thread", ""] if talk(topic["thread"]) else []
        lines += self.thread(self.topics.thread_shown(topic["thread"], name))
        return "\n".join(lines).rstrip() + "\n"

    def thread(self, thread: list[dict[str, Any]]) -> list[str]:
        lines = []
        for entry in talk(thread):
            text = " ".join(str(entry.get("text") or "").split())
            lines.append(f"> {entry['author']}, {entry['moment']}: {text}")
            lines += [f">   attached: {file['where']}" for file in entry.get("attachments", [])]
        return [*lines, ""] if lines else []
