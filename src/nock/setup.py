"""Installing nock into a project — vendored, so it becomes the project's own
code — and upgrading the vendored core with a three-way merge, so local edits
survive."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nock.decisions import MAP
from nock.errors import ConflictError, PreconditionError
from nock.git import Git, GitError
from nock.hooks import BUILT_IN_EVENTS, EDIT_TOOLS
from nock.project import NOCK_DIRECTORY, Project
from nock.templates import Library
from nock.tools import NATIVE_EVENTS, Event
from nock.utils import read_json, write_atomic, write_json

PACKAGE = Path(__file__).resolve().parent
VERSION = "0.2.0"
DEFAULT_SOURCE = "https://github.com/dan-gittik/nock"

SHIM = """\
#!/bin/sh
# nock, vendored: the code is in .nock/core and belongs to this project.
# It needs Python 3.12 or newer and nothing else; NOCK_PYTHON picks the interpreter.
here="$(cd "$(dirname "$0")" && pwd -P)"
PYTHONPATH="$here/core${PYTHONPATH:+:$PYTHONPATH}" exec "${NOCK_PYTHON:-python3}" -m nock "$@"
"""

CONFIG = """\
# nock's settings. Defaults live in .nock/core/nock/configuration.py;
# machine-specific overrides go in .nock/local/config.toml (not committed).

branch = "main"

# Checks `.nock/nock check` runs besides the @nock.check functions in
# .nock/tools/. Exit 0 passes, 1 fails (the code is wrong), anything else
# means the machine is.
# [checks.lint]
# command = "ruff check ."
# fix = "ruff check --fix ."
#
# [checks.test]
# command = "pytest -q"

[reflect]
# A round is due after this many sessions or days, whichever comes first.
sessions = 15
days = 7

[agent]
# The model of the agents nock dispatches (elaborate, consult); empty is Claude Code's default.
model = ""
"""

GITIGNORE = "local/\n"

PRIMER = """\
## nock

This project uses nock to stay coherent across sessions, which matters as
much as getting each task done: you start knowing nothing of earlier
sessions, and nock keeps what they decided, what the owner said about it, and
the tools agents built.

- **Consult while you work out how to do something,** unless the task is
  really straightforward and unambiguous:
  `.nock/nock consult '{"intent": …, "context": …}'`. A fresh agent searches
  the project and tells you the decisions and tools that bear on your work.
- **Record decisions as you make them:** `.nock/nock decide` (`--help` has
  the fields). A decision is a choice between ways that could each work, a
  deliberate simplification, your reading of something ambiguous, a todo
  you are leaving, or a question only the owner can settle when they are
  not there to ask; give the alternatives you weighed, for someone who knows
  what the system does but not how it is built. The owner reviews them
  later, so don't wait. When you do a todo, act on an answer or rework a
  rejected decision, edit it to say what you did.
- **Run noisy or long commands through `.nock/nock run -- COMMAND`,** and
  `.nock/nock check` before you finish. Exit codes: 1 fix the code, 42 fix
  the machine or the state, 50 and up retry or escalate.
"""

MAP_STUB = """\
# The map of decisions

When each of the project's decisions matters, and how they bear on each
other. Empty until the first reflection round writes it; until then,
`.nock/nock decisions list` lists the decisions, and an edit to a file a
decision governs shows it.
"""

IMPORT_LINE = "@.nock/context.md"
# Claude Code skills, from `briefs/NAME/` (a SKILL.md and what it reads).
SKILLS = ("nock-reflect", "nock-triage")
# Skills earlier versions installed, removed on install.
RETIRED_SKILLS = ("reflect", "consolidate")
HOOK_COMMAND = '"$CLAUDE_PROJECT_DIR"/.nock/nock hook {event}'
PERMISSION = "Bash(.nock/nock:*)"


def wired_events(root: Path) -> set[str]:
    """The Claude Code events this checkout's settings send to nock."""
    settings_path = root / ".claude" / "settings.json"
    if not settings_path.is_file():
        return set()
    try:
        hooks = read_json(settings_path).get("hooks", {})
    except PreconditionError:
        return set()
    return {
        event
        for event, entries in hooks.items()
        if any(
            ".nock/nock hook" in str(hook.get("command", ""))
            for entry in entries
            if isinstance(entry, dict)
            for hook in entry.get("hooks", [])
        )
    }


@dataclass
class Report:
    written: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        lines = []
        if self.written:
            lines.append("wrote: " + ", ".join(self.written))
        if self.kept:
            lines.append("kept (already there): " + ", ".join(self.kept))
        if self.conflicts:
            lines.append("CONFLICTS to resolve by hand: " + ", ".join(self.conflicts))
        return lines


def core_files(root: Path) -> dict[str, bytes]:
    """The core's files under `root`, by relative path, caches left out."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


class Installer:
    def __init__(self, target: Path) -> None:
        try:
            self.root = Git(target).main_checkout()
        except GitError as error:
            raise PreconditionError(
                f"{target} is not a git repository — `git init` it first"
            ) from error
        self.directory = self.root / NOCK_DIRECTORY
        self.report = Report()

    def install(self, source: str | None = None) -> Report:
        source = source or DEFAULT_SOURCE
        core = self.directory / "core" / "nock"
        if core.resolve() != PACKAGE:
            if core.exists():
                raise ConflictError(f"{core} exists — use `nock upgrade` to update a vendored core")
            self.copy_core(core)
            write_json(
                self.directory / "core" / "VERSION.json",
                {"version": VERSION, "source": source, "commit": self.source_commit()},
            )
        self.write("nock", SHIM, executable=True, replace=True)
        self.write(".gitignore", GITIGNORE, replace=False)
        self.write("config.toml", CONFIG, replace=False)
        self.write("context.md", PRIMER, replace=True)
        self.write("tools/.gitkeep", "", replace=False)
        self.import_context()
        self.wire_claude()
        self.install_skills()
        self.start_map()
        return self.report

    def install_skills(self) -> None:
        """The `/nock-reflect` and `/nock-triage` skills, kept in step with the core like the primer."""
        briefs = PACKAGE / "briefs"
        library = Library(briefs)
        for name in SKILLS:
            for source in sorted((briefs / name).glob("*.md")):
                relative = f".claude/skills/{name}/{source.name}"
                write_atomic(self.root / relative, library.render(f"{name}/{source.name}"))
                self.report.written.append(relative)
        for name in RETIRED_SKILLS:
            skill = self.root / ".claude" / "skills" / name / "SKILL.md"
            if skill.is_file() and skill.read_text().startswith(f"---\nname: {name}\n"):
                skill.unlink()
                if not any(skill.parent.iterdir()):
                    skill.parent.rmdir()
                self.report.written.append(f"removed .claude/skills/{name}")

    def start_map(self) -> None:
        """An empty map of decisions, so an agent told to read it finds it."""
        relative = f"{NOCK_DIRECTORY}/decisions/{MAP}"
        if (self.root / relative).exists():
            return
        write_atomic(self.root / relative, MAP_STUB)
        self.report.written.append(relative)

    def copy_core(self, core: Path) -> None:
        for relative, content in core_files(PACKAGE).items():
            path = core / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.report.written.append(f"{NOCK_DIRECTORY}/core/")

    def source_commit(self) -> str | None:
        """The upstream commit this core was copied from, when it came from a checkout."""
        git = Git(PACKAGE)
        if not git.succeeds("ls-files", "--error-unmatch", "__init__.py") or git.dirty("."):
            return None
        return git.head()

    def write(
        self, relative: str, text: str, executable: bool = False, replace: bool = False
    ) -> None:
        path = self.directory / relative
        if path.exists() and not replace:
            self.report.kept.append(f"{NOCK_DIRECTORY}/{relative}")
            return
        write_atomic(path, text)
        if executable:
            path.chmod(0o755)
        self.report.written.append(f"{NOCK_DIRECTORY}/{relative}")

    def import_context(self) -> None:
        """CLAUDE.md imports `.nock/context.md`, so every session reads the
        primer without nock ever editing CLAUDE.md again."""
        claude = self.root / "CLAUDE.md"
        text = claude.read_text() if claude.is_file() else ""
        if IMPORT_LINE in text.splitlines():
            return
        claude.write_text(text.rstrip("\n") + ("\n\n" if text.strip() else "") + IMPORT_LINE + "\n")
        self.report.written.append("CLAUDE.md")

    def wire_claude(self) -> None:
        settings_path = self.root / ".claude" / "settings.json"
        settings = read_json(settings_path) if settings_path.is_file() else {}
        hooks = settings.setdefault("hooks", {})
        project_events = {entry.event for entry in Project(self.root).registry.hooks}
        listened = {*BUILT_IN_EVENTS, *project_events}
        for event in sorted(NATIVE_EVENTS[event] for event in listened):
            command = HOOK_COMMAND.format(event=event)
            entry: dict[str, Any] = {"hooks": [{"type": "command", "command": command}]}
            # nock's own after-tool handler wants only edits; a project hook may want every tool.
            if event == NATIVE_EVENTS[Event.AFTER_TOOL] and Event.AFTER_TOOL not in project_events:
                entry["matcher"] = EDIT_TOOLS
            entries = hooks.setdefault(event, [])
            entries[:] = [
                existing
                for existing in entries
                if not any(
                    ".nock/nock hook" in str(hook.get("command", ""))
                    for hook in existing.get("hooks", [])
                )
            ]
            entries.append(entry)
        allowed = settings.setdefault("permissions", {}).setdefault("allow", [])
        if PERMISSION not in allowed:
            allowed.append(PERMISSION)
        write_json(settings_path, settings)
        self.report.written.append(".claude/settings.json")


class Upgrader:
    """Three-way merge of the vendored core: the version it was vendored from
    (base), the project's copy (ours), and upstream (theirs)."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.core = project.root / NOCK_DIRECTORY / "core" / "nock"
        self.version_file = project.root / NOCK_DIRECTORY / "core" / "VERSION.json"

    def upgrade(self, source: str | None = None, force: bool = False) -> Report:
        version = read_json(self.version_file) if self.version_file.is_file() else {}
        source = str(source or version.get("source") or DEFAULT_SOURCE)
        report = Report()
        with tempfile.TemporaryDirectory() as scratch:
            upstream = self.fetch(source, Path(scratch))
            theirs = core_files(upstream / "src" / "nock")
            base = self.base(upstream, version.get("commit"))
            if base is None and not force:
                raise PreconditionError(
                    "cannot find the version this core was vendored from upstream, so local edits "
                    "cannot be merged safely — `--force` replaces the core, losing them"
                )
            ours = core_files(self.core)
            names: set[str] = {*theirs, *ours, *(base or {})}
            for relative in sorted(names):
                merged = self.merge(
                    relative,
                    ours.get(relative),
                    (base or {}).get(relative),
                    theirs.get(relative),
                    force,
                )
                path = self.core / relative
                if merged is None:
                    if path.exists():
                        path.unlink()
                        report.written.append(relative)
                    continue
                content, conflicted = merged
                if ours.get(relative) != content:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                    report.written.append(relative)
                if conflicted:
                    report.conflicts.append(relative)
            commit = Git(upstream).head() if Git(upstream).succeeds("rev-parse", "HEAD") else None
            upstream_version = self.upstream_version(upstream)
        write_json(
            self.version_file, {"version": upstream_version, "source": source, "commit": commit}
        )
        return report

    def fetch(self, source: str, scratch: Path) -> Path:
        if Path(source).is_dir():
            return Path(source)
        result = subprocess.run(
            ["git", "clone", "--quiet", source, str(scratch / "upstream")],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise PreconditionError(f"cannot clone {source}: {result.stderr.strip()}")
        return scratch / "upstream"

    def base(self, upstream: Path, commit: str | None) -> dict[str, bytes] | None:
        if not commit:
            return None
        git = Git(upstream)
        if not git.succeeds("cat-file", "-e", f"{commit}^{{commit}}"):
            return None
        names = git("ls-tree", "-r", "--name-only", commit, "src/nock").splitlines()
        return {
            name.removeprefix("src/nock/"): subprocess.run(
                ["git", "show", f"{commit}:{name}"], cwd=upstream, capture_output=True, check=True
            ).stdout
            for name in names
        }

    def merge(
        self,
        relative: str,
        ours: bytes | None,
        base: bytes | None,
        theirs: bytes | None,
        force: bool,
    ) -> tuple[bytes, bool] | None:
        """The file's merged content and whether it conflicted, or None to delete it."""
        if force:
            return (theirs, False) if theirs is not None else None
        if ours == base:
            return (theirs, False) if theirs is not None else None
        if theirs in (base, ours):
            return (ours, False) if ours is not None else None
        if ours is None or theirs is None:
            return ((ours or theirs or b""), True)
        with tempfile.TemporaryDirectory() as scratch:
            paths = []
            for name, content in (("ours", ours), ("base", base or b""), ("theirs", theirs)):
                path = Path(scratch) / name
                path.write_bytes(content)
                paths.append(str(path))
            result = subprocess.run(
                [
                    "git",
                    "merge-file",
                    "-p",
                    "-L",
                    "project",
                    "-L",
                    "vendored",
                    "-L",
                    "upstream",
                    *paths,
                ],
                capture_output=True,
            )
        return result.stdout, result.returncode != 0

    def upstream_version(self, upstream: Path) -> str:
        pyproject = upstream / "pyproject.toml"
        if pyproject.is_file():
            for line in pyproject.read_text().splitlines():
                if line.startswith("version"):
                    return json.loads(line.split("=", 1)[1].strip())
        return "unknown"
