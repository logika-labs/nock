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

from nock import harnesses, rounds
from nock.configuration import Confirm
from nock.errors import ConflictError, NotFoundError, PreconditionError
from nock.git import Git, GitError
from nock.harnesses import NATIVE_EVENTS, Event, Harness
from nock.hooks import EDIT_TOOLS, NOCK_COMMANDS
from nock.migration import migrate_in
from nock.primer import AGENTS, MARK_START, PRIMER, refresh, with_section
from nock.project import NOCK_DIRECTORY, Project
from nock.releases import PYPI, VERSION, Releases
from nock.shared import MAP, SETTINGS
from nock.templates import Library
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

# Checks `.nock/nock check` runs besides the @nock.check functions in
# .nock/tools/. Exit 0 passes, 1 fails (the code is wrong), anything else
# means the machine is.
# [checks.lint]
# command = "ruff check ."
# fix = "ruff check --fix ."
#
# [checks.test]
# command = "pytest -q"

[agent]
# The model of the agents nock dispatches (consult, the studio's Ask); empty is Claude Code's default.
model = ""

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

GITIGNORE = "local/\n__pycache__/\n"

SETTINGS_STUB = """\
# The team's settings: whatever the people working on this project share,
# committed with the topics. `.nock/nock config` lists and sets them; the code's
# settings are in .nock/config.toml, one machine's in .nock/local/config.toml.

# Whether nock speaks up unasked: the primer's advice, the toolbox and an
# occasional word on where things stand at a session's start, the owner's
# word in the topics, the decisions about an edited file. false: silent unless asked.
reminders = true

# Whether nock shares a usage report with its makers, weekly: counts and
# categories, and a random id for the project, never code, paths, names or
# text. Unset until the owner answers nock's question, and nothing is sent
# unless it is true; false sends nothing at all. `.nock/nock config share` shows
# exactly what would be sent.
# share = false
"""

MAP_STUB = """\
# The map of topics

When each topic and its items matter, and how they bear on each other,
citing each item by its ref in brackets. Empty until the first reflection round
writes it; until then, `.nock/local/views/index.md` lists the topics.
"""

IMPORT_LINE = "@.nock/context.md"
# Claude Code skills, from `briefs/NAME/`, besides the rounds' (`install_rounds`).
# Each SKILL.md is its trigger and one line pointing at its brief in `nock docs`,
# so the text always matches the vendored core and an upgrade never rewrites a skill.
SKILLS = ("nock-triage", "nock-work")
# Skills any harness can follow, written to `.agents/skills/` too, where Codex reads them.
PORTABLE_SKILLS = ("nock-work",)
RETIRED_ROUND_FILES = (
    ".claude/skills/nock-reflect-logika/SKILL.md",
    ".claude/agents/nock-reflect-toolbox.md",
    ".claude/agents/nock-reflect-map.md",
    ".claude/agents/nock-reflect-nock.md",
    ".claude/agents/nock-logika-rules.md",
    ".claude/agents/nock-logika-analytics.md",
)
HOOK_COMMAND = '"$CLAUDE_PROJECT_DIR"/.nock/nock hook {event}'
# Codex and Cursor give a hook no project directory, and may run it in a subdirectory.
OTHER_HOOK_COMMAND = '"$(git rev-parse --show-toplevel)"/.nock/nock hook {event} {harness}'
# Seconds a Codex or Cursor hook may take: a session start may upgrade nock (`UPGRADE_DEADLINE`).
HOOK_TIMEOUT = 300
HOOKS_WHAT = {
    Harness.CLAUDE_CODE: "Claude Code hooks, and a permission rule per nock command",
    Harness.CODEX: "Codex hooks: the toolbox at a session's start, the owner's word at a prompt,"
    " what a stop leaves open",
    Harness.CURSOR: "Cursor hooks: the toolbox at a session's start, what a stop leaves open",
}
PRIMER_WHAT = "the primer: what nock is for here, as the settings have it"
NEXT = (
    "Next: commit what nock changed; each agent session from the next on starts with"
    " nock's toolbox (`.nock/nock` lists it)."
)
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
    notes: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        lines = list(self.notes)
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


@dataclass
class Change:
    """What `nock init` did to one file: its path, what it holds, and whether
    it was `created`, `updated` or `removed`."""

    path: str
    what: str
    outcome: str


class Installer:
    """Installs into the working tree it is run in — a worktree's install is
    that branch's change, never the main checkout's — for each agent harness
    the repository uses (`harnesses.found`)."""

    def __init__(self, target: Path) -> None:
        try:
            self.root = Git(target).toplevel()
        except GitError as error:
            raise PreconditionError(
                f"{target} is not a git repository — `git init` it first"
            ) from error
        self.directory = self.root / NOCK_DIRECTORY
        self.harnesses = harnesses.found(self.root)
        self.changes: list[Change] = []
        self.notes: list[str] = []

    def install(self, source: str | None = None) -> list[str]:
        """What it found, exactly what it changed, and the next step."""
        source = source or DEFAULT_SOURCE
        core = self.directory / "core" / "nock"
        if not core.exists():
            self.copy_core(core)
            write_json(
                self.directory / "core" / "VERSION.json",
                {"version": VERSION, "source": source, "commit": self.source_commit()},
            )
        elif core.resolve() != PACKAGE:
            # Run from elsewhere (NOCK_SOURCE): re-wire with this nock, but the
            # vendored core is the project's, changed only by a merge.
            self.notes.append(
                f"kept the vendored core ({NOCK_DIRECTORY}/core/) — this nock runs from {PACKAGE}; "
                "`nock upgrade` updates the core"
            )
        nock = NOCK_DIRECTORY
        self.put(f"{nock}/nock", SHIM, "runs the vendored core", executable=True)
        self.start(
            f"{nock}/.gitignore",
            GITIGNORE,
            "keeps .nock/local/ (this machine's) and the core's bytecode out of git",
        )
        self.start(f"{nock}/config.toml", CONFIG, "nock's settings, committed")
        self.start(f"{nock}/tools/.gitkeep", "", "where the project's own tools go")
        primed = (self.directory / PRIMER).exists()
        for path in refresh(self.directory):
            relative = str(path.relative_to(self.root))
            outcome = "created" if path.name == PRIMER and not primed else "updated"
            self.changes.append(Change(relative, PRIMER_WHAT, outcome))
        if {Harness.CODEX, Harness.CURSOR} & set(self.harnesses):
            self.write_section()
        self.import_context()
        for harness in self.harnesses:
            self.wire(harness)
        self.install_skills()
        self.start_map()
        self.migrate()
        return self.lines()

    def lines(self) -> list[str]:
        titles = ", ".join(harness.label for harness in self.harnesses)
        lines = [f"Found agent harnesses: {titles}.", *self.notes]
        if not self.changes:
            return [*lines, "", "Nothing changed: nock is set up and wired already."]
        width = max(len(change.path) for change in self.changes)
        created = any(change.outcome == "created" for change in self.changes)
        lines += ["", "Added:" if created else "Changed:"]
        lines += [
            f"  {change.path:{width}}  {change.what}"
            + ("" if change.outcome == "created" else f" ({change.outcome})")
            for change in self.changes
        ]
        if Harness.CODEX in self.harnesses:
            lines += ["", "Codex runs a project's hooks once you trust them: `/hooks` in Codex."]
        return [*lines, "", NEXT]

    def put(self, relative: str, text: str, what: str, executable: bool = False) -> None:
        """`text` at `relative` (to the repository) unless it is there already."""
        path = self.root / relative
        if path.is_file() and path.read_text() == text:
            return
        outcome = "updated" if path.exists() else "created"
        write_atomic(path, text)
        if executable:
            path.chmod(0o755)
        self.changes.append(Change(relative, what, outcome))

    def start(self, relative: str, text: str, what: str) -> None:
        """`text` at `relative` only where there is nothing yet: the project's to change."""
        if not (self.root / relative).exists():
            self.put(relative, text, what)

    def remove(self, relative: str, what: str) -> None:
        path = self.root / relative
        path.unlink()
        directory = path.parent
        while directory != self.root and not any(directory.iterdir()):
            directory.rmdir()
            directory = directory.parent
        self.changes.append(Change(relative, what, "removed"))

    def install_skills(self) -> None:
        """`/nock-triage`, `/nock-work` and the rounds' skills from the
        registry (`rounds`): `/nock-reflect` for nock's, `/<namespace>` for
        another namespace with two or more adopted protocols and
        `/<namespace>-<protocol>` for each adopted one outside nock, each
        saying only which `reflect` to run, with each protocol's agents as
        Claude Code subagents; `/nock-work`, which any harness can follow,
        also in the skills directory of each other harness found that reads
        none written already (Codex's), and taken out of a directory no
        harness found reads. Kept in step with the core like the primer."""
        briefs = PACKAGE / "briefs"
        library = Library(briefs)
        portable = [
            harness
            for harness in harnesses.skill_installs(self.harnesses)
            if harness is not Harness.CLAUDE_CODE
        ]
        for name in SKILLS:
            for source in sorted((briefs / name).glob("*.md")):
                text = library.render(f"{name}/{source.name}")
                self.put(
                    f".claude/skills/{name}/{source.name}",
                    text,
                    f"the /{name} skill, for Claude Code",
                )
                if name not in PORTABLE_SKILLS:
                    continue
                for harness in Harness:
                    relative = f"{harness.skills_directory}/{name}/{source.name}"
                    if harness in portable:
                        self.put(relative, text, f"the /{name} skill, for {harness.label}")
                    elif harness is not Harness.CLAUDE_CODE and self.ours(relative, text):
                        self.remove(relative, f"the /{name} skill: no harness found reads it here")
        self.install_rounds()

    def install_rounds(self) -> None:
        project = Project(self.root)
        wanted = [
            protocol
            for protocol in rounds.protocols(project)
            if protocol.adopted() and not protocol.unavailable()
        ]
        namespaces: dict[str, list[rounds.Protocol]] = {}
        for protocol in wanted:
            namespaces.setdefault(protocol.manifest.namespace, []).append(protocol)
        skills: dict[str, tuple[str, str]] = {}
        for namespace, members in namespaces.items():
            titles = ", ".join(protocol.title.lower() for protocol in members)
            if namespace == "nock" or len(members) > 1:
                skills[rounds.skill_of(namespace)] = (
                    namespace,
                    f"Run the {namespace} rounds at once: {titles}. Use when nock says a round"
                    " is due, or when asked to reflect.",
                )
            if namespace == "nock":
                continue
            for protocol in members:
                skills[rounds.skill_of(namespace, protocol.manifest.protocol)] = (
                    protocol.name,
                    f"Run the {protocol.name} round: {protocol.manifest.data['summary']}"
                    " Use when the owner asks, or agrees when nock says it is due.",
                )
        for skill, (target, description) in skills.items():
            self.put(
                f".claude/skills/{skill}/SKILL.md",
                f"---\nname: {skill}\ndescription: {description}\n---\n\n"
                f"Run `.nock/nock reflect {target}` and do what it says.\n",
                f"the /{skill} skill, for Claude Code",
            )
        for protocol in wanted:
            for agent in protocol.manifest.data.get("agents", []):
                kind = rounds.agent_type(protocol.manifest, agent["name"])
                source = protocol.manifest.folder / "agents" / f"{agent['name']}.md"
                text = source.read_text().replace("---\n", f"---\nname: {kind}\n", 1)
                self.put(f".claude/agents/{kind}.md", text, f"the {kind} subagent, for Claude Code")
        for relative in RETIRED_ROUND_FILES:
            if (self.root / relative).is_file():
                self.remove(relative, "an earlier nock's round skill or subagent")

    def ours(self, relative: str, text: str) -> bool:
        path = self.root / relative
        return path.is_file() and path.read_text() == text

    def start_map(self) -> None:
        """An empty map of topics, so an agent told to read it finds it (an
        earlier nock's map of decisions moves here when the project migrates)."""
        if (self.root / NOCK_DIRECTORY / "decisions" / MAP).exists():
            return
        self.start(
            f"{NOCK_DIRECTORY}/shared/{MAP}", MAP_STUB, "the map of topics, empty until a round"
        )
        self.start(f"{NOCK_DIRECTORY}/shared/{SETTINGS}", SETTINGS_STUB, "the team's settings")

    def migrate(self) -> None:
        migrated = migrate_in(self.root)
        if migrated and migrated["migrated"]:
            self.notes.append(
                f"migrated {migrated['decisions']} decision(s) and {migrated['review_items']}"
                f" review item(s) into {len(migrated['topics'])} topic(s) in"
                f" {NOCK_DIRECTORY}/topics/"
            )
        if migrated and migrated.get("split"):
            split = migrated["split"]
            self.notes.append(
                f"split {split['items']} item(s) holding several files into {split['into']},"
                f" one asset each, in {NOCK_DIRECTORY}/topics/"
            )

    def copy_core(self, core: Path) -> None:
        for relative, content in core_files(PACKAGE).items():
            path = core / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.changes.append(
            Change(f"{NOCK_DIRECTORY}/core/", "nock's code, vendored: the project's own", "created")
        )

    def source_commit(self) -> str | None:
        """The upstream commit this core was copied from, when it came from a checkout."""
        git = Git(PACKAGE)
        if not git.succeeds("ls-files", "--error-unmatch", "__init__.py") or git.dirty("."):
            return None
        return git.head()

    def import_context(self) -> None:
        """CLAUDE.md imports `.nock/context.md`, so every session reads the
        primer without nock ever editing CLAUDE.md again — unless it imports
        AGENTS.md and AGENTS.md holds the primer, which it would read twice."""
        claude = self.root / "CLAUDE.md"
        text = claude.read_text() if claude.is_file() else ""
        agents = self.root / AGENTS
        lines = text.splitlines()
        if (
            any(word in ("@AGENTS.md", "@./AGENTS.md") for word in text.split())
            and agents.is_file()
            and MARK_START in agents.read_text()
        ):
            if IMPORT_LINE in lines:
                kept = "\n".join(line for line in lines if line != IMPORT_LINE).rstrip("\n")
                self.put("CLAUDE.md", kept + "\n", "imports AGENTS.md, which holds the primer")
            return
        if IMPORT_LINE in lines:
            return
        self.put(
            "CLAUDE.md",
            text.rstrip("\n") + ("\n\n" if text.strip() else "") + IMPORT_LINE + "\n",
            "imports .nock/context.md, so Claude Code reads the primer",
        )

    def write_section(self) -> None:
        """The primer in AGENTS.md, between nock's markers: Codex and Cursor
        read AGENTS.md and follow no import. `refresh` keeps it current."""
        agents = self.root / AGENTS
        text = agents.read_text() if agents.is_file() else ""
        primer_text = (self.directory / PRIMER).read_text()
        self.put(
            AGENTS,
            with_section(text, primer_text),
            "the primer, between nock's markers, for Codex and Cursor",
        )

    def wire(self, harness: Harness) -> None:
        """The harness's hooks file with nock's hooks in it, everything else
        kept as it was; Claude Code's with nock's permission rules too."""
        relative = harness.hooks_file
        path = self.root / relative
        settings = read_json(path) if path.is_file() else {}
        if not isinstance(settings, dict):
            raise PreconditionError(f"{relative} is not a JSON object — fix it, then `nock init`")
        if harness is Harness.CURSOR and "version" not in settings:
            settings = {"version": 1, **settings}
        hooks = settings.setdefault("hooks", {})
        project_events = (
            {entry.event for entry in Project(self.root).registry.hooks}
            if harness is not Harness.CURSOR
            else set()
        )
        listened = {*harness.own_events, *project_events} & harness.events.keys()
        for entries in hooks.values():
            if isinstance(entries, list):
                entries[:] = [entry for entry in entries if not hooked(entry)]
        for event in sorted(listened, key=lambda event: harness.events[event]):
            hooks.setdefault(harness.events[event], []).append(
                hook_entry(harness, event, project_events)
            )
        for native in [native for native, entries in hooks.items() if entries == []]:
            del hooks[native]
        what = HOOKS_WHAT[harness]
        if harness is Harness.CLAUDE_CODE:
            self.permit(settings)
        text = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
        if path.is_file() and read_json(path) == settings:
            return
        self.put(relative, text, what)

    def permit(self, settings: dict[str, Any]) -> None:
        permissions = settings.setdefault("permissions", {})
        allow, ask = wanted_permissions(Project(self.root))
        for kind, wanted in (("allow", allow), ("ask", ask)):
            kept = [rule for rule in permissions.get(kind, []) if not ours(rule)]
            if kept + wanted:
                permissions[kind] = kept + wanted
            else:
                permissions.pop(kind, None)


def hooked(entry: object) -> bool:
    """Whether a hooks file's entry runs nock's hook: Claude Code's and
    Codex's group commands under `hooks`, Cursor's holds one `command`."""
    if not isinstance(entry, dict):
        return False
    commands = [hook.get("command") for hook in entry.get("hooks", []) if isinstance(hook, dict)]
    return any(".nock/nock hook" in str(command) for command in [*commands, entry.get("command")])


def hook_entry(harness: Harness, event: Event, project_events: set[Event]) -> dict[str, Any]:
    if harness is Harness.CLAUDE_CODE:
        command = HOOK_COMMAND.format(event=NATIVE_EVENTS[event])
    else:
        command = OTHER_HOOK_COMMAND.format(event=NATIVE_EVENTS[event], harness=harness.value)
    if harness is Harness.CURSOR:
        return {"command": command, "timeout": HOOK_TIMEOUT}
    hook: dict[str, Any] = {"type": "command", "command": command}
    if harness is not Harness.CLAUDE_CODE:
        hook["timeout"] = HOOK_TIMEOUT
    entry: dict[str, Any] = {"hooks": [hook]}
    # nock's own after-tool handler wants edits and shell commands (either may write
    # in .nock/shared/), its before-tool one only its own commands; a project hook
    # may want every tool.
    if harness is Harness.CLAUDE_CODE:
        if event is Event.AFTER_TOOL and Event.AFTER_TOOL not in project_events:
            entry["matcher"] = f"{EDIT_TOOLS}|Bash"
        if event is Event.BEFORE_TOOL and Event.BEFORE_TOOL not in project_events:
            entry["matcher"] = "Bash"
            hook["if"] = NOCK_COMMANDS
    return entry


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
