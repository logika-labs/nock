"""Reflection rounds as data: a protocol is a folder `rounds/<namespace>/<protocol>/`
— its manifest (`round.toml`: title, who it serves, when it is due, what its
lead reads and writes, its agents, what its end checks and commits), its
lead's brief (`lead.md`), its agents' briefs (`agents/NAME.md`) and, only for
material no command gives, `material.py`. nock ships some (`nock/rounds/`); a
project adds or overrides its own in `.nock/rounds/`. A round is one protocol
run once: `nock reflect NAMESPACE.PROTOCOL` starts it (or picks it up),
`nock reflect --submit JSON` checks and records it, in the store at
`.nock/shared/rounds/<namespace.protocol>/<date>/`."""

from __future__ import annotations

import difflib
import fnmatch
import importlib.util
import json
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from nock.checks import Checks, matches
from nock.configuration import with_table_settings
from nock.errors import Failed, NotFoundError, PreconditionError, UsageError
from nock.git import Git, GitError
from nock.reflect import RECORD_FILE, ROUND_FILE, Record, Rounds, schema
from nock.schema import validate
from nock.sessions import Sessions
from nock.topics import Topics
from nock.utils import now, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

SHIPPED = Path(__file__).resolve().parent / "rounds"
LOCAL = Path(".nock") / "rounds"
MANIFEST = "round.toml"
LEAD = "lead.md"
# The round that sets the others up, and runs first.
FIT = "nock.fit"
# Files no count of changed lines takes in, unless a round names them.
LOCKFILES = (
    "*.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "go.sum", "npm-shrinkwrap.json",
)  # fmt: skip


@dataclass(frozen=True)
class Manifest:
    namespace: str
    protocol: str
    folder: Path
    data: dict[str, Any]

    @property
    def name(self) -> str:
        return f"{self.namespace}.{self.protocol}"

    def section(self, key: str) -> dict[str, Any]:
        value = self.data.get(key)
        return value if isinstance(value, dict) else {}


def manifests(project: Project | None) -> dict[str, Manifest]:
    """Every protocol, shipped and the project's own (which overrides one of
    the same name), by name."""
    found: dict[str, Manifest] = {}
    places = [SHIPPED] + ([project.here / LOCAL] if project is not None else [])
    for place in places:
        for path in sorted(place.glob(f"*/*/{MANIFEST}")):
            try:
                data = tomllib.loads(path.read_text())
            except tomllib.TOMLDecodeError as error:
                raise PreconditionError(f"{path} is not valid TOML: {error}") from error
            manifest = Manifest(path.parent.parent.name, path.parent.name, path.parent, data)
            found[manifest.name] = manifest
    return found


def protocols(project: Project) -> list[Protocol]:
    return [Protocol(project, manifest) for manifest in manifests(project).values()]


def named(project: Project, name: str) -> list[Protocol]:
    """The protocols NAME names: one (`logika.rules`), or every adopted one of
    a namespace (`logika`)."""
    every = protocols(project)
    exact = [protocol for protocol in every if protocol.name == name]
    if exact:
        return exact
    grouped = [protocol for protocol in every if protocol.manifest.namespace == name]
    adopted = [
        protocol for protocol in grouped if protocol.adopted() and not protocol.unavailable()
    ]
    if adopted:
        return adopted
    if grouped:
        why = grouped[0].unavailable() or "none of them is adopted here"
        raise PreconditionError(f"no {name} round can run here: {why}")
    names = sorted({p.name for p in every} | {p.manifest.namespace for p in every})
    close = difflib.get_close_matches(name, names, n=1)
    hint = f"did you mean `reflect {close[0]}`? " if close else ""
    raise NotFoundError(f"no round {name!r} — {hint}there are: {', '.join(names)}")


def skill_of(namespace: str, protocol: str | None = None) -> str:
    """The skill that runs it: `/nock-reflect` for nock's namespace,
    `/<namespace>` for another, `/<namespace>-<protocol>` for one protocol."""
    if protocol is None:
        return "nock-reflect" if namespace == "nock" else namespace
    return f"{namespace}-{protocol}"


class Protocol:
    """One protocol, here: whether it can run and is adopted, when it is due,
    and its rounds — started, picked up, left open, submitted."""

    def __init__(self, project: Project, manifest: Manifest) -> None:
        self.project = project
        self.manifest = manifest
        self.name = manifest.name
        self.title = str(manifest.data.get("title") or self.name)
        self.rounds = Rounds(
            project,
            directory=project.root / ".nock" / "shared" / "rounds" / self.name,
            scratch=project.local / "reflections" / self.name,
        )
        self.module: ModuleType | None = None

    # --- where it stands ----------------------------------------------------------

    def unavailable(self) -> str:
        """Why it cannot run here (a file or a command it needs, or what its
        `material.py` says), or nothing."""
        special = self.hook("unavailable")
        if special is not None:
            return str(special(self) or "")
        requires = self.manifest.section("requires")
        for file in requires.get("files") or []:
            if not (self.project.here / file).exists():
                return f"it needs {file}, which this repository lacks"
        for command in requires.get("commands") or []:
            if shutil.which(command) is None:
                return f"it needs `{command}` on PATH"
        return ""

    def adopted(self) -> bool:
        """On: every round that can run here is, unless the project's config
        turns it off (`[rounds."NAME"] enabled = false`, which snoozing it
        "never" writes); one whose measure is `never` runs only by its name."""
        if self.manifest.section("due").get("measure") == "never":
            return False
        return bool(self.config().get("enabled", True)) and not self.unavailable()

    def config(self) -> dict[str, Any]:
        """The project's settings for this round: `.nock/config.toml`'s
        `[rounds."NAME"]` — enabled, paths, any, threshold, snoozes."""
        value = self.project.configuration.get("rounds") or {}
        found = value.get(self.name) if isinstance(value, dict) else None
        if not isinstance(found, dict):
            # `[rounds.audit.tests]` written unquoted nests the name's parts.
            found = value
            for part in self.name.split("."):
                found = found.get(part) if isinstance(found, dict) else None
        return found if isinstance(found, dict) else {}

    def setting(self, key: str) -> Any:
        """A due rule: the project's config, else the round's manifest default."""
        own = self.config()
        if key in own:
            return own[key]
        return self.manifest.section("due").get(key)

    @property
    def since(self) -> str | None:
        last = self.rounds.last()
        return last.get("finished") if last else None

    def baseline(self) -> dict[str, Any] | None:
        """What its measure counts from: its last run (the commit it started
        at, when it finished); never run, the fit round's last run, which set
        it up. None when neither has run."""
        last = self.rounds.last()
        if last is not None:
            return last
        if self.name == FIT:
            return None
        fit = next((p for p in protocols(self.project) if p.name == FIT), None)
        return fit.rounds.last() if fit is not None else None

    def measure(self) -> dict[str, Any]:
        """How much changed in what it looks at since its baseline, against
        its threshold: `value`, `threshold`, `unit`, and `any` — a change to a
        file that makes it due by itself (a lockfile, an API's schema)."""
        kind = str(self.setting("measure") or "never")
        threshold = self.setting("threshold")
        found: dict[str, Any] = {"measure": kind, "threshold": threshold, "value": None, "unit": ""}
        if kind == "never":
            return found
        base = self.baseline()
        if base is None:
            return found
        since = base.get("finished")
        if kind == "lines":
            commit = base.get("commit") or self.commit_at(since)
            paths = [str(path) for path in self.setting("paths") or []]
            found |= {"unit": "lines changed", "value": changed_lines(self.project, commit, paths)}
            anywhere = [str(path) for path in self.setting("any") or []]
            if anywhere:
                touched = changed_files(self.project, commit, anywhere)
                if touched:
                    found["any"] = touched[:5]
        elif kind == "sessions":
            sessions = Sessions(self.project)
            sessions.catch_up()
            found |= {"unit": "sessions", "value": len(sessions.since(since))}
        elif kind == "tools":
            rows = self.project.store.rows(
                "SELECT tool, exit_code FROM calls WHERE started > ? AND source != 'nock'",
                (since or "",),
            )
            failing = sorted(
                {
                    row["tool"]
                    for row in rows
                    if sum(
                        1 for other in rows if other["tool"] == row["tool"] and other["exit_code"]
                    )
                    >= 3
                }
            )
            found |= {"unit": "tool runs", "value": len(rows)}
            if failing:
                found["any"] = [f"{tool} failed 3 times" for tool in failing[:5]]
        elif kind == "topics":
            found |= {"unit": "task changes", "value": topic_changes(self.project, since)}
        elif kind == "python":
            function = self.hook("measure")
            if function is not None:
                value, unit = function(self, base)
                found |= {"value": value, "unit": unit}
        return found

    def commit_at(self, moment: str | None) -> str | None:
        if not moment:
            return None
        try:
            return Git(self.project.here)("rev-list", "-1", f"--before={moment}", "HEAD") or None
        except GitError:
            return None

    def due(self) -> str:
        """Why a round is due, or nothing: on, not snoozed, and its measure
        over its threshold since its last run (fit, never run, is due at
        once; the others stay quiet until fit has run)."""
        if not self.adopted():
            return ""
        if self.rounds.last() is None and self.name == FIT:
            return "it has never run here"
        if self.name != FIT and self.baseline() is None:
            return ""
        snoozed = self.config().get("snooze_until")
        if isinstance(snoozed, str) and snoozed > now()[:10]:
            return ""
        found = self.measure()
        value, threshold = found["value"], found["threshold"]
        if found.get("any"):
            return f"{', '.join(found['any'])} since the last run"
        if value is None or threshold is None:
            return ""
        floor = self.config().get("snooze_at")
        wanted = max(int(threshold), int(floor)) if isinstance(floor, int) else int(threshold)
        if value < wanted:
            return ""
        return f"{value:,} of {int(threshold):,} {found['unit']} in what {self.title} looks at"

    def changes(self, paths: list[str], since: str | None) -> list[str]:
        try:
            output = Git(self.project.here)(
                "log", "--format=%ad %s", "--date=short",
                *([f"--since={since}"] if since else []), "HEAD", "--", *paths,
            )  # fmt: skip
        except GitError:
            return []
        return output.splitlines()

    def skill(self) -> str:
        if self.manifest.namespace == "nock":
            return skill_of("nock")
        return skill_of(self.manifest.namespace, self.manifest.protocol)

    def standing(self) -> dict[str, Any]:
        last = self.rounds.last()
        measure = self.measure()
        return {
            "protocol": self.name,
            "title": self.title,
            "summary": self.manifest.data.get("summary") or "",
            "unavailable": self.unavailable() or None,
            "on": self.adopted(),
            "due": self.due() or None,
            "last": last.get("finished") if last else None,
            "measure": measure,
            "snooze_until": self.config().get("snooze_until"),
            "snooze_at": self.config().get("snooze_at"),
            "paths": self.setting("paths") or [],
            "task": task_of(self),
            "skill": f"/{self.skill()}",
        }

    # --- material -------------------------------------------------------------------

    def python(self) -> ModuleType | None:
        """Its `material.py`, loaded once, when it has one."""
        path = self.manifest.folder / "material.py"
        if self.module is None and path.is_file():
            specification = importlib.util.spec_from_file_location(
                f"nock_round_{self.name.replace('.', '_').replace('-', '_')}", path
            )
            assert specification is not None and specification.loader is not None
            module = importlib.util.module_from_spec(specification)
            sys.modules[specification.name] = module
            specification.loader.exec_module(module)
            self.module = module
        return self.module

    def hook(self, name: str) -> Any:
        module = self.python()
        return getattr(module, name, None) if module is not None else None

    def material(self, name: str) -> str:
        """One of its materials, by the source the manifest gives it."""
        source = self.manifest.section("material").get(name)
        if not isinstance(source, dict) or len(source) != 1:
            raise PreconditionError(f"{self.name}: material {name!r} names one source")
        kind, value = next(iter(source.items()))
        if kind == "python":
            function = self.hook(str(value))
            if function is None:
                raise PreconditionError(f"{self.name}: material.py has no {value}()")
            return str(function(self))
        if kind == "command":
            done = subprocess.run(
                str(value), shell=True, cwd=self.project.here, capture_output=True, text=True
            )
            return done.stdout + (
                f"\n(exit {done.returncode})\n{done.stderr}" if done.returncode else ""
            )
        if kind == "topic":
            view = self.project.local / "views" / f"{value}.md"
            return view.read_text() if view.is_file() else f"(no topic {value} yet)"
        if kind == "git":
            return "\n".join(self.changes([str(path) for path in value], self.since)) or "(none)"
        raise PreconditionError(f"{self.name}: material {name!r} has an unknown source {kind!r}")

    def reads(self) -> list[str]:
        names = list(self.manifest.section("lead").get("reads") or [])
        for agent in self.manifest.data.get("agents") or []:
            names += [name for name in agent.get("reads") or [] if name not in names]
        return names

    # --- a round ----------------------------------------------------------------------

    @property
    def files(self) -> list[str]:
        return list(self.manifest.section("lead").get("writes") or ["report.md"])

    def start(self) -> dict[str, Any]:
        """Start a round — or pick up the one started and not finished, its
        material left as it was written; another round the same day is `DATE-2`."""
        problem = self.unavailable()
        if problem:
            raise PreconditionError(f"{self.name} cannot run here: {problem}")
        name = self.rounds.current()
        session = self.project.current_session()
        if name is not None:
            kept = self.rounds.scratch / name / ROUND_FILE
            started = read_json(kept)
            if session and session not in started.get("sessions", []):
                write_json(kept, {**started, "sessions": [*started.get("sessions", []), session]})
            return {
                **self.started(name, started["material"]),
                "picked_up": f"the round {name}, started {started['started']} and not "
                "finished; its material stands as written then",
            }
        name = self.rounds.new_name()
        scratch = self.rounds.scratch / name
        scratch.mkdir(parents=True, exist_ok=True)
        material = {}
        for part in self.reads():
            (scratch / f"{part}.md").write_text(self.material(part))
            material[part] = str(scratch / f"{part}.md")
        begun = self.hook("begun")
        write_json(
            scratch / ROUND_FILE,
            {
                "round": name,
                "protocol": self.name,
                "since": self.since,
                "started": now(),
                "commit": head(self.project),
                "sessions": [session] if session else [],
                "material": material,
                **(begun(self) if begun else {}),
            },
        )
        (self.rounds.directory / name).mkdir(parents=True, exist_ok=True)
        ensure_task(self, name)
        return self.started(name, material)

    def started(self, name: str, material: dict[str, str]) -> dict[str, Any]:
        """What the lead does: its brief, its agents with theirs and their
        material, the files to write and the submit."""
        lead = self.manifest.folder / LEAD
        agents = []
        for agent in self.manifest.data.get("agents") or []:
            agents.append(
                {
                    "type": agent_type(self.manifest, str(agent["name"])),
                    "brief": str(self.manifest.folder / "agents" / f"{agent['name']}.md"),
                    "reads": [
                        material[part] for part in agent.get("reads") or [] if part in material
                    ],
                    **({"changes": agent["changes"]} if agent.get("changes") else {}),
                    **({"one per": agent["fan_out"]} if agent.get("fan_out") else {}),
                }
            )
        return {
            "protocol": self.name,
            "round": name,
            "since": self.since,
            "task": f"{task_of(self)}: the round's result goes before the owner there; record"
            " what needs them as proposals in it (`.nock/nock docs topics.items`)",
            "brief": lead.read_text().strip() if lead.is_file() else "",
            "material": material,
            "agents": agents,
            "write": [
                str((self.rounds.directory / name / file).relative_to(self.project.root))
                for file in self.files
            ],
            "submit": f'.nock/nock reflect --submit \'{{"protocol": "{self.name}", "summary": …,'
            ' "changes": [{"kind": …, "target": …, "why": …, "expect": …}]}\'',
        }

    def unwritten(self, name: str) -> list[str]:
        directory = self.rounds.directory / name
        return [
            file
            for file in self.files
            if not (directory / file).is_file() or not (directory / file).read_text().strip()
        ]

    def problems(self, finishing: bool) -> list[str]:
        """What its end finds: its checks (only the quick ones for a round left
        open), and what its `material.py` says of the round."""
        end = self.manifest.section("end")
        names = list(end.get("checks" if finishing else "quick") or [])
        found = Checks(self.project).run(names).problems() if names else []
        check = self.hook("problems")
        return found + (list(check(self)) if check else [])

    def submit(self, record: Record) -> dict[str, Any]:
        """Check the round and record it: its files written, its checks
        passing, the record kept beside them, committed."""
        name = self.rounds.current()
        if name is None:
            raise PreconditionError(
                f"no {self.name} round is under way — `.nock/nock reflect {self.name}` starts one"
            )
        kinds = self.manifest.section("end").get("kinds")
        if kinds:
            wrong = sorted({change["kind"] for change in record["changes"]} - set(kinds))
            if wrong:
                raise UsageError(
                    f"{self.name} records changes of kind {', '.join(kinds)}, not {', '.join(wrong)}"
                )
        directory = self.rounds.directory / name
        missing = self.unwritten(name)
        if missing:
            raise PreconditionError(f"write {' and '.join(missing)} in {directory} first")
        problems = self.problems(finishing=True)
        if problems:
            raise Failed(f"the {self.name} round does not pass its checks yet", problems)
        started = read_json(self.rounds.scratch / name / ROUND_FILE)
        kept = self.hook("kept")
        write_json(
            directory / RECORD_FILE,
            {
                **record,
                "round": name,
                "protocol": self.name,
                "since": started["since"],
                "started": started["started"],
                "commit": started.get("commit"),
                "finished": now(),
                **(kept(self, started) if kept else {}),
            },
        )
        commit(
            self.project,
            f"{self.name} round {name}: {record['summary']}",
            [str(path) for path in self.manifest.section("end").get("commit") or []],
            directory,
        )
        task = write_task(self, name, record, directory)
        return {
            "protocol": self.name,
            "round": name,
            "task": task,
            "wrote": [
                str((directory / file).relative_to(self.project.root)) for file in self.files
            ],
        }

    def left_open(self, session: str) -> str | None:
        """What a session that started this protocol's round, still under way,
        has left to do before it may end; nothing otherwise."""
        name = self.rounds.current()
        if name is None:
            return None
        started = read_json(self.rounds.scratch / name / ROUND_FILE)
        if session not in started.get("sessions", []):
            return None
        directory = self.rounds.directory / name
        owed = [
            f"write {file} in {directory.relative_to(self.project.root)}"
            for file in self.unwritten(name)
        ]
        if not owed:
            owed += [f"fix what its checks find: {problem}" for problem in self.problems(False)]
        owed.append(
            f'then `.nock/nock reflect --submit \'{{"protocol": "{self.name}", …}}\'` records it'
        )
        return (
            f"nock: the {self.name} round {name} is under way and not finished — "
            + "; ".join(owed)
            + ". Finish it, or tell the owner why it stays open."
        )


def head(project: Project) -> str | None:
    try:
        return Git(project.here)("rev-parse", "HEAD") or None
    except GitError:
        return None


def is_lockfile(path: str, named: list[str]) -> bool:
    """A lockfile no count takes in, unless one of the round's globs names it."""
    base = path.rsplit("/", 1)[-1]
    if not any(fnmatch.fnmatchcase(base, pattern) for pattern in LOCKFILES):
        return False
    return not any(base in glob or "lock" in glob for glob in named)


def numstat(project: Project, commit: str | None) -> list[tuple[int, str]]:
    """Each file changed since COMMIT (committed or not), with its lines
    added and removed; binary files count none."""
    if not commit:
        return []
    try:
        output = Git(project.here)("diff", "--numstat", commit, "--")
    except GitError:
        return []
    found = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        lines = (int(added) if added.isdigit() else 0) + (int(removed) if removed.isdigit() else 0)
        found.append((lines, path))
    return found


def changed_lines(project: Project, commit: str | None, paths: list[str]) -> int:
    """Lines changed (added and removed) in PATHS since COMMIT, lockfiles and
    nock's own files left out unless the paths name them."""
    total = 0
    for lines, path in numstat(project, commit):
        if path.startswith(".nock/") and not any(glob.startswith(".nock") for glob in paths):
            continue
        if is_lockfile(path, paths) or not matches(path, paths):
            continue
        total += lines
    return total


def changed_files(project: Project, commit: str | None, globs: list[str]) -> list[str]:
    """The files among GLOBS changed since COMMIT: any one makes a round due."""
    return [path for _, path in numstat(project, commit) if matches(path, globs)]


def topic_changes(project: Project, since: str | None) -> int:
    """How many events the tasks gained since a moment: the map round's measure."""
    root = project.root / ".nock" / "shared" / "topics"
    if not root.is_dir():
        return 0
    stamp = (since or "").replace("-", "").replace(":", "")[:15]
    count = 0
    for path in root.rglob("events/*.json"):
        if path.name[:15] > stamp:
            count += 1
    return count


def task_of(protocol: Protocol) -> str:
    """The task a round's result goes in: one per round, revived each run."""
    return f"round-{protocol.manifest.namespace}-{protocol.manifest.protocol}"


def ensure_task(protocol: Protocol, name: str) -> str:
    """The round's task, opened (or revived) and active as the round starts,
    so its lead can record its items there."""
    from nock.shared import Shared, by_for

    project = protocol.project
    shared = Shared(project)
    task = task_of(protocol)
    folder = shared.topic_folder(task)
    existing = shared.fold.topic(task)
    written: list[Path] = []
    status = {"kind": "state", "state": "active", "status": f"the {name} round is running"}
    if existing is None:
        written.append(
            shared.draft(
                folder,
                {
                    "kind": "created",
                    "description": f"What the {protocol.title} round finds and changes here.",
                },
            )
        )
        written.append(shared.draft(folder, status))
    elif existing["state"] in ("done", "abandoned"):
        written.append(
            shared.draft(folder, {**status, "revived": True, "note": f"the {name} round"})
        )
    elif existing["state"] != "active":
        written.append(shared.draft(folder, status))
    if written:
        settled = shared.settle(by_for(project), only=written)
        Topics(project).heard(settled)
    return task


def write_task(protocol: Protocol, name: str, record: Record, directory: Path) -> str | None:
    """A round's result as a task to review: its changes as decisions, and a
    review telling the round — its summary, its report, what its lead
    recorded there, the changes — then the task set to review."""
    from nock.shared import Shared, by_for

    project = protocol.project
    shared = Shared(project)
    task = ensure_task(protocol, name)
    folder = shared.topic_folder(task)
    written: list[Path] = []
    blocks: list[dict[str, Any]] = [{"kind": "text", "text": f"**{record['summary']}**"}]
    report = directory / "report.md"
    if report.is_file() and report.read_text().strip():
        blocks.append({"kind": "text", "text": report.read_text().strip()})
    started = protocol.rounds.scratch / name / ROUND_FILE
    since = read_json(started).get("started", "") if started.is_file() else ""
    for item in shared.fold.items(task):
        if item["created"]["moment"] >= since and item["status"] != "rejected":
            blocks.append({"kind": "item", "item": item["slug"]})
    recorded = {
        change["target"] for change in record["changes"] if change["kind"] in ("rounds", "review")
    }
    taken = set(shared.fold.slugs(task))
    for place, change in enumerate(record["changes"], start=1):
        if change["target"] in recorded and change["kind"] in ("rounds", "review"):
            continue
        slug = f"{name}-{place}"
        while slug in taken:
            slug += "-b"
        taken.add(slug)
        written.append(
            shared.draft(
                shared.item_folder(task, slug),
                {
                    "kind": "created",
                    "type": "decision",
                    "title": f"{change['kind']}: {change['target']}"[:200],
                    "means": f"{change['why']} Expect: {change['expect']}"[:1200],
                },
            )
        )
        blocks.append({"kind": "item", "item": slug})
    with project.lock("shared"):
        settled = shared.settle(by_for(project), only=written) if written else None
        review = shared.review_folder(task) / "versions" / "next" / "review.json"
        review.parent.mkdir(parents=True, exist_ok=True)
        review.write_text(
            json.dumps({"summary": record["summary"][:2000], "blocks": blocks}, indent=2)
        )
        state = shared.draft(
            folder, {"kind": "state", "state": "review", "status": f"the {name} round, to review"}
        )
        reviewed = shared.settle(by_for(project), only=[review, state])
    topics = Topics(project)
    if settled is not None:
        topics.heard(settled)
    topics.heard(reviewed)
    return None if reviewed.problems else task


def listing(project: Project) -> list[dict[str, Any]]:
    """Every round with its standing, for the studio's settings."""
    return [protocol.standing() for protocol in protocols(project)]


def hints(project: Project) -> list[dict[str, Any]]:
    """The rounds due now, for the studio's hints."""
    return [protocol.standing() for protocol in protocols(project) if protocol.due()]


def config_write(project: Project, name: str, values: dict[str, Any]) -> None:
    """Set a round's keys in `.nock/config.toml`'s `[rounds."NAME"]`, kept in git."""
    path = project.code_path("config.toml")
    text = path.read_text() if path.is_file() else ""
    path.write_text(with_table_settings(text, f'rounds."{name}"', values))
    project.__dict__.pop("configuration", None)
    said = ", ".join(f"{key} = {json.dumps(value)}" for key, value in values.items())
    with project.lock("shared"):
        git = Git(project.here)
        relative = str(path.relative_to(project.here))
        if git("status", "--porcelain", "--", relative, check=False).strip():
            git.changing(
                "commit", "--quiet", "--no-verify", "--only", "-m",
                f"nock: round {name}: {said}", "--", relative,
            )  # fmt: skip


def one(project: Project, name: str) -> Protocol:
    found = [protocol for protocol in protocols(project) if protocol.name == name]
    if not found:
        raise NotFoundError(f"no round {name!r}")
    return found[0]


def snooze(project: Project, name: str, how: dict[str, Any]) -> dict[str, Any]:
    """Remind me in DAYS days, after twice the changes, or never (off)."""
    protocol = one(project, name)
    if how.get("never"):
        config_write(project, name, {"enabled": False})
    elif how.get("twice"):
        value = protocol.measure()["value"] or 0
        threshold = int(protocol.setting("threshold") or 0)
        config_write(project, name, {"snooze_at": int(value) + threshold})
    else:
        days = how.get("days")
        if not isinstance(days, int) or days < 1:
            raise UsageError("snooze for `days` (1 or more), `twice` or `never`")
        until = (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%d")
        config_write(project, name, {"snooze_until": until})
    return one(project, name).standing()


def configure(project: Project, name: str, values: dict[str, Any]) -> dict[str, Any]:
    """The owner's settings for a round: on or off, its threshold, its paths."""
    one(project, name)
    kept: dict[str, Any] = {}
    if isinstance(values.get("enabled"), bool):
        kept["enabled"] = values["enabled"]
    if isinstance(values.get("threshold"), int) and values["threshold"] > 0:
        kept["threshold"] = values["threshold"]
    if isinstance(values.get("paths"), list) and all(isinstance(p, str) for p in values["paths"]):
        kept["paths"] = values["paths"]
    if not kept:
        raise UsageError("set `enabled`, `threshold` or `paths`")
    config_write(project, name, kept)
    return one(project, name).standing()


def agent_type(manifest: Manifest, agent: str) -> str:
    """Its subagent type: `<namespace>-<protocol>` when it is its protocol's
    one agent, else `<namespace>-<protocol>-<agent>`."""
    agents = manifest.data.get("agents") or []
    base = f"{manifest.namespace}-{manifest.protocol}"
    return base if len(agents) == 1 else f"{base}-{agent}"


def submit(project: Project, record: Record) -> dict[str, Any]:
    """`nock reflect --submit`: the record checked, given to its protocol."""
    validate(record, schema())
    found = [protocol for protocol in protocols(project) if protocol.name == record["protocol"]]
    if not found:
        raise NotFoundError(f"no protocol {record['protocol']!r}")
    return found[0].submit(record)


def commit(project: Project, message: str, paths: list[str], record: Path) -> None:
    """Commit a round: the paths its manifest names in the working tree, and
    its record in the store, in the main checkout; nothing else."""
    places: list[tuple[Path, list[str]]] = []
    here = [
        path
        for path in paths
        if (project.here / path).exists() or Git(project.here)("ls-files", "--", path)
    ]
    store = str(record.relative_to(project.root))
    if project.root == project.here:
        places.append((project.root, [*here, store]))
    else:
        places += [(project.here, here), (project.root, [store])]
    # The store's lock: its record is committed in the main checkout, as every store commit is.
    with project.lock("shared"):
        for root, wanted in places:
            if not wanted:
                continue
            git = Git(root)
            git.changing("add", "--all", "--", *wanted)
            if git("diff", "--cached", "--name-only", "--", *wanted):
                git.changing(
                    "commit", "--quiet", "--no-verify", "--only", "-m", message, "--", *wanted
                )
