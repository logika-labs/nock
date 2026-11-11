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
import importlib.util
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from nock.checks import Checks
from nock.errors import Failed, NotFoundError, PreconditionError, UsageError
from nock.git import Git, GitError
from nock.reflect import RECORD_FILE, ROUND_FILE, Record, Rounds, schema
from nock.schema import validate
from nock.sessions import Sessions
from nock.topics import Topics
from nock.utils import now, parse_moment, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

SHIPPED = Path(__file__).resolve().parent / "rounds"
LOCAL = Path(".nock") / "rounds"
MANIFEST = "round.toml"
LEAD = "lead.md"
# The topic nock.fit records its recommendations in.
RECOMMENDATIONS = "rounds"


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
        """Always; where its files are (`when-files`); or once the owner
        accepted nock.fit's recommendation of it."""
        how = str(self.manifest.data.get("adopted") or "recommended")
        if how == "always":
            return True
        if how == "when-files":
            files = self.manifest.section("requires").get("files") or []
            return all((self.project.here / file).exists() for file in files)
        topics = Topics(self.project)
        if RECOMMENDATIONS not in topics.names():
            return False
        return any(
            item["verdict"] == "accepted" and self.name in item["title"]
            for item in topics.items(RECOMMENDATIONS)
        )

    def setting(self, key: str) -> Any:
        """A due rule, as its manifest has it: a project changes it by a
        protocol of its own in `.nock/rounds/`."""
        return self.manifest.section("due").get(key)

    @property
    def since(self) -> str | None:
        last = self.rounds.last()
        return last.get("finished") if last else None

    def due(self) -> str:
        """Why a round is due, or nothing: never run (`first`); with `changed`
        files, `days` since the last and those files changed since; else enough
        `sessions` or `days` since the last, given a session to look at."""
        if self.unavailable():
            return ""
        special = self.hook("due")
        if special is not None:
            return str(special(self) or "")
        last = self.rounds.last()
        if last is None and self.setting("first"):
            return "it has never run here"
        since = self.since
        changed = self.setting("changed") or []
        days_needed = self.setting("days")
        if changed:
            if last is None or days_needed is None:
                return ""
            days = days_since(since)
            commits = self.changes(changed, since)
            if days < float(days_needed) or not commits:
                return ""
            return (
                f"{len(commits)} commits changed {', '.join(changed)} in the {days:.0f} days"
                " since the last"
            )
        sessions = Sessions(self.project)
        sessions.catch_up()
        window = sessions.since(since)
        if not window:
            return ""
        sessions_needed = self.setting("sessions")
        if sessions_needed is not None and len(window) >= int(sessions_needed):
            return f"{len(window)} sessions since the last"
        days = days_since(since or window[0]["started"])
        if days_needed is not None and days >= float(days_needed):
            return f"{len(window)} sessions over {days:.0f} days"
        return ""

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
        return {
            "protocol": self.name,
            "title": self.title,
            "summary": self.manifest.data.get("summary") or "",
            "unavailable": self.unavailable() or None,
            "adopted": self.adopted(),
            "due": self.due() or None,
            "last": last.get("finished") if last else None,
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
                "sessions": [session] if session else [],
                "material": material,
                **(begun(self) if begun else {}),
            },
        )
        (self.rounds.directory / name).mkdir(parents=True, exist_ok=True)
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
        return {
            "protocol": self.name,
            "round": name,
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


def days_since(moment: str | None) -> float:
    start = parse_moment(moment)
    return (datetime.now(UTC) - start).total_seconds() / 86400 if start else 0


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
    for root, wanted in places:
        if not wanted:
            continue
        git = Git(root)
        git("add", "--all", "--", *wanted)
        if git("diff", "--cached", "--name-only", "--", *wanted):
            git("commit", "--quiet", "--no-verify", "--only", "-m", message, "--", *wanted)
