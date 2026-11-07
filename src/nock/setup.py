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

from nock.configuration import Confirm
from nock.decisions import MAP
from nock.errors import ConflictError, NotFoundError, PreconditionError
from nock.git import Git, GitError
from nock.hooks import BUILT_IN_EVENTS, EDIT_TOOLS
from nock.kinds import KINDS
from nock.primer import PRIMER, refresh
from nock.project import NOCK_DIRECTORY, Project
from nock.releases import PYPI, VERSION, Releases
from nock.templates import Library
from nock.tools import NATIVE_EVENTS, Event
from nock.utils import read_json, write_atomic, write_json

PACKAGE = Path(__file__).resolve().parent
# Where upgrades come from unless a project says otherwise: PyPI.
DEFAULT_SOURCE = PYPI

SHIM = """\
#!/bin/sh
# nock, vendored: the code is in .nock/core and belongs to this project.
# It needs Python 3.12 or newer and nothing else; NOCK_PYTHON picks the interpreter.
# NOCK_SOURCE runs nock from elsewhere, such as a checkout's src/.
here="$(cd "$(dirname "$0")" && pwd -P)"
PYTHONPATH="${NOCK_SOURCE:-$here/core}${PYTHONPATH:+:$PYTHONPATH}" exec "${NOCK_PYTHON:-python3}" -m nock "$@"
"""

CONFIG = """\
# nock's settings. Defaults live in .nock/core/nock/configuration.py;
# machine-specific overrides go in .nock/local/config.toml (not committed).

branch = "main"

# Whether nock speaks up unasked: the primer's advice, the toolbox and an
# occasional word on where things stand at a session's start, the owner's
# reviews, the decisions behind an edited file. false: silent unless asked.
reminders = true

# Whether nock shares a usage report with its makers, weekly: counts and
# categories, and a random id for the project, never code, paths, names or
# text. Unset until the owner answers nock's question, and nothing is sent
# unless it is true; false sends nothing at all. `.nock/nock usage` shows
# exactly what would be sent.
# share = false

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

# [decisions]
# The project's fixed tags for decisions: `decide` and `edit` refuse any other
# (but `important`). Unset, agents add their own.
# tags = ["core", "web", "deploy"]

[consult]
# Whether agents are asked to consult nock's consultant before changing code.
enabled = true

[permissions]
# How Claude Code treats a command only the owner may set off (confirm=True):
# "ask" has the owner approve each call, even in bypass mode; "allow" lets the
# agent run it, when the owner's request calls for it. `nock init` rewrites
# the rules after a change.
confirm = "ask"
"""

GITIGNORE = "local/\n"

MAP_STUB = """\
# The map of decisions

When each of the project's decisions matters, and how they bear on each
other. Empty until the first reflection round writes it; until then,
`.nock/nock decisions list` lists the decisions, and an edit to a file a
decision governs shows it.
"""

IMPORT_LINE = "@.nock/context.md"
# Claude Code skills, from `briefs/NAME/`, besides each kind of round's where it is
# wanted. Each SKILL.md and subagent (`agents/`) is its trigger and one line pointing
# at its brief in `nock docs`, so the text always matches the vendored core and an
# upgrade never rewrites a skill.
SKILLS = ("nock-triage",)
# Skills earlier versions installed, removed on install.
RETIRED_SKILLS = ("reflect", "consolidate")
# The briefs earlier versions installed beside a skill, now `nock docs` terms.
RETIRED_SKILL_FILES = {
    "nock-reflect": ("process.md", "knowledge.md", "nock.md"),
    "nock-reflect-logika": ("rules.md", "analytics.md"),
}
HOOK_COMMAND = '"$CLAUDE_PROJECT_DIR"/.nock/nock hook {event}'
# The rules nock writes into `.claude/settings.json`, and no others: one per
# command, so the file says exactly what an agent runs unasked.
# - `allow`: the bare `.nock/nock` (it lists the tools), and every command but
#   those below — each reads, records in `.nock/`, or runs the project's own
#   committed toolbox and checks.
# - `ask`: each `confirm=True` command, nock's own (`init` rewrites these
#   rules, `upgrade` fetches and merges code, `share` sends a summary out) and
#   the project's. Claude Code puts `ask` before `allow`, and asks even in
#   bypass mode, so `permissions.confirm = "allow"` puts them under `allow`.
# - no rule for `run`, which runs any command: Claude Code treats it as it
#   would the command itself.
PERMISSION = "Bash(.nock/nock {path}:*)"
LISTING = ("Bash(.nock/nock)", "Bash(.nock/nock --help)")
UNLISTED = ("run",)
# Rules earlier versions wrote: the blanket allow let `run` take any command unasked.
RETIRED_PERMISSIONS = ("Bash(.nock/nock:*)",)


def permission_rules(root: Path, kind: str) -> set[str]:
    """This checkout's Claude Code rules of a kind (`allow`, `ask`)."""
    settings_path = root / ".claude" / "settings.json"
    try:
        settings = read_json(settings_path) if settings_path.is_file() else {}
    except PreconditionError:
        return set()
    return {str(rule) for rule in settings.get("permissions", {}).get(kind, [])}


def wanted_permissions(project: Project) -> tuple[list[str], list[str]]:
    """The allow and ask rules nock wants for this toolbox."""
    tools = project.registry.tools
    asking = project.configuration.confirm() is Confirm.ASK
    allowed = [*LISTING]
    allowed += [
        PERMISSION.format(path=tool.command.path)
        for tool in tools
        if not (tool.confirm and asking) and tool.command.path not in UNLISTED
    ]
    asked = [PERMISSION.format(path=tool.command.path) for tool in tools if tool.confirm and asking]
    return allowed, asked


def ours(rule: object) -> bool:
    return str(rule) == "Bash(.nock/nock)" or str(rule).startswith("Bash(.nock/nock ")


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
    """Installs into the working tree it is run in — a worktree's install is
    that branch's change, never the main checkout's."""

    def __init__(self, target: Path) -> None:
        try:
            self.root = Git(target).toplevel()
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
        if refresh(self.directory):
            self.report.written.append(f"{NOCK_DIRECTORY}/{PRIMER}")
        self.write("tools/.gitkeep", "", replace=False)
        self.import_context()
        self.wire_claude()
        self.install_skills()
        self.start_map()
        return self.report

    def install_skills(self) -> None:
        """`/nock-triage` and each kind of round's skill where it is wanted
        (`/nock-reflect`; `/nock-reflect-logika` in a Logika project), with
        the subagents its parts run as, kept in step with the core like the
        primer."""
        briefs = PACKAGE / "briefs"
        library = Library(briefs)
        rounds = tuple(kind.skill for kind in KINDS.values() if kind.wanted(self.root))
        for name in (*rounds, *SKILLS):
            for source in sorted((briefs / name).glob("*.md")):
                relative = f".claude/skills/{name}/{source.name}"
                write_atomic(self.root / relative, library.render(f"{name}/{source.name}"))
                self.report.written.append(relative)
            # The round's parts as Claude Code subagents, each with only the tools its part needs.
            for source in sorted((briefs / name / "agents").glob("*.md")):
                relative = f".claude/agents/{source.name}"
                write_atomic(self.root / relative, library.render(f"{name}/agents/{source.name}"))
                self.report.written.append(relative)
        for name, files in RETIRED_SKILL_FILES.items():
            for file in files:
                path = self.root / ".claude" / "skills" / name / file
                if path.is_file():
                    path.unlink()
                    self.report.written.append(f"removed .claude/skills/{name}/{file}")
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
        permissions = settings.setdefault("permissions", {})
        allow, ask = wanted_permissions(Project(self.root))
        for kind, wanted in (("allow", allow), ("ask", ask)):
            kept = [
                rule
                for rule in permissions.get(kind, [])
                if not ours(rule) and rule not in RETIRED_PERMISSIONS
            ]
            if kept + wanted:
                permissions[kind] = kept + wanted
            else:
                permissions.pop(kind, None)
        write_json(settings_path, settings)
        self.report.written.append(".claude/settings.json")


class Upgrader:
    """Three-way merge of the vendored core: the version it was vendored from
    (base), the project's copy (ours), and upstream (theirs)."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.core = project.code_path("core", "nock")
        self.version_file = project.code_path("core", "VERSION.json")

    def upgrade(
        self, source: str | None = None, force: bool = False, only_clean: bool = False
    ) -> Report:
        """The upgrade, merged into the core; with `only_clean`, a ConflictError
        naming the files that would conflict, and nothing changed."""
        version = read_json(self.version_file) if self.version_file.is_file() else {}
        source = str(source or version.get("source") or DEFAULT_SOURCE)
        if source == PYPI:
            return self.from_pypi(version, force, only_clean)
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
            self.merge_all(report, theirs, base, force, only_clean)
            commit = Git(upstream).head() if Git(upstream).succeeds("rev-parse", "HEAD") else None
            upstream_version = self.upstream_version(upstream)
        write_json(
            self.version_file, {"version": upstream_version, "source": source, "commit": commit}
        )
        return report

    def from_pypi(self, version: dict[str, Any], force: bool, only_clean: bool) -> Report:
        """The latest release on PyPI merged in, the vendored release's own
        files the base."""
        releases = Releases(str(self.project.configuration.get("upgrade.index")))
        latest = releases.latest()
        report = Report()
        theirs = releases.files(latest)
        try:
            base = releases.files(str(version["version"])) if version.get("version") else None
        except NotFoundError:
            base = None
        if base is None and not force:
            raise PreconditionError(
                f"the vendored version ({version.get('version')}) is not on PyPI, so local edits "
                "cannot be merged safely — `--force` replaces the core, losing them"
            )
        self.merge_all(
            report,
            {name: content for name, content in theirs.items() if "__pycache__" not in name},
            base,
            force,
            only_clean,
        )
        write_json(self.version_file, {"version": latest, "source": PYPI, "commit": None})
        return report

    def merge_all(
        self,
        report: Report,
        theirs: dict[str, bytes],
        base: dict[str, bytes] | None,
        force: bool,
        only_clean: bool = False,
    ) -> None:
        ours = core_files(self.core)
        names: set[str] = {*theirs, *ours, *(base or {})}
        plan = {
            relative: self.merge(
                relative,
                ours.get(relative),
                (base or {}).get(relative),
                theirs.get(relative),
                force,
            )
            for relative in sorted(names)
        }
        conflicted = [relative for relative, merged in plan.items() if merged and merged[1]]
        if only_clean and conflicted:
            raise ConflictError(
                "the upgrade would conflict with local edits to the core, so nothing changed — "
                "`.nock/nock upgrade` merges it, leaving the conflicts to resolve",
                conflicted,
            )
        for relative, merged in plan.items():
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
