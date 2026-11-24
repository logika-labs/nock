"""Reflection rounds as data. A round is a group (audit, fuzz, logika, nock);
a subround is one part of it (`audit.security`), a folder `rounds/<round>/<subround>/`
— its manifest (`round.toml`: title, who it serves, when it is due, what its
lead reads and writes, its agents, what its end checks and commits), its
lead's brief (`lead.md`), its agents' briefs (`agents/NAME.md`) and, only for
material no command gives, `material.py`. nock ships some (`nock/rounds/`); a
project adds or overrides its own in `.nock/rounds/`. `nock reflect ROUND`
gives the plan, one agent per enabled subround; `nock reflect
ROUND.SUBROUND` starts a run of one (or picks it up), and `nock reflect
--submit JSON` checks and records it: its record committed at
`.nock/shared/rounds/<round.subround>/<date>/`, its material and the lead's
files (its report) on this machine, in
`.nock/local/reflections/<round.subround>/<date>/`. The lead reports the
run's findings to the session that ran it, as its final message."""

from __future__ import annotations

import difflib
import fnmatch
import importlib.util
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from nock.checks import Checks, matches
from nock.errors import Failed, NotFoundError, PreconditionError, UsageError
from nock.git import Git, GitError
from nock.reflect import RECORD_FILE, RUN_FILE, Record, Runs, schema
from nock.schema import validate
from nock.sessions import Sessions
from nock.utils import now, read_json, write_json

if TYPE_CHECKING:
    from nock.project import Project

SHIPPED = Path(__file__).resolve().parent / "rounds"
LOCAL = Path(".nock") / "rounds"
MANIFEST = "round.toml"
LEAD = "lead.md"
# The subround that sets the others up, and runs first.
FIT = "nock.fit"
# Files no count of changed lines takes in, unless a subround names them.
LOCKFILES = (
    "*.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "go.sum", "npm-shrinkwrap.json",
)  # fmt: skip


@dataclass(frozen=True)
class Manifest:
    round: str
    subround: str
    folder: Path
    data: dict[str, Any]

    @property
    def name(self) -> str:
        return f"{self.round}.{self.subround}"

    def section(self, key: str) -> dict[str, Any]:
        value = self.data.get(key)
        return value if isinstance(value, dict) else {}


def manifests(project: Project | None) -> dict[str, Manifest]:
    """Every subround, shipped and the project's own (which overrides one of
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


def subrounds(project: Project) -> list[Subround]:
    return [Subround(project, manifest) for manifest in manifests(project).values()]


def named(project: Project, name: str) -> list[Subround]:
    """The subrounds NAME names: one (`logika.instrument`), or every adopted
    one of a round (`logika`)."""
    every = subrounds(project)
    exact = [subround for subround in every if subround.name == name]
    if exact:
        return exact
    grouped = [subround for subround in every if subround.manifest.round == name]
    adopted = [
        subround for subround in grouped if subround.adopted() and not subround.unavailable()
    ]
    if adopted:
        return adopted
    if grouped:
        why = grouped[0].unavailable() or "none of them is adopted here"
        raise PreconditionError(f"no {name} round can run here: {why}")
    names = sorted({p.name for p in every} | {p.manifest.round for p in every})
    close = difflib.get_close_matches(name, names, n=1)
    hint = f"did you mean `reflect {close[0]}`? " if close else ""
    raise NotFoundError(f"no round or subround {name!r} — {hint}there are: {', '.join(names)}")


def plan(project: Project, name: str) -> dict[str, Any]:
    """What `nock reflect ROUND` prints: one agent per enabled subround, each
    starting its own and leading it, so the session sees each one's report."""
    every = named(project, name)
    return {
        "round": name,
        "do": f"dispatch {len(every)} general-purpose subagents in one message, in the"
        " background, one per subround below, each with its prompt; relay each one's report"
        " to the owner as it ends",
        "subrounds": [
            {
                "subround": subround.name,
                "title": subround.title,
                "due": subround.due() or None,
                "prompt": f"Run `.nock/nock reflect {subround.name}` and do what it says: you"
                " lead this subround, and your final message reports it.",
            }
            for subround in every
        ],
    }


def skill_of(group: str, subround: str | None = None) -> str:
    """The skill that runs it: `/nock-reflect` for nock's round, `/<round>`
    for another, `/<round>-<subround>` for one subround."""
    if subround is None:
        return "nock-reflect" if group == "nock" else group
    return f"{group}-{subround}"


class Subround:
    """One subround, here: whether it can run and is adopted, when it is due,
    and its runs — started, picked up, left open, submitted."""

    def __init__(self, project: Project, manifest: Manifest) -> None:
        self.project = project
        self.manifest = manifest
        self.name = manifest.name
        self.title = str(manifest.data.get("title") or self.name)
        self.runs = Runs(
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
        """On: every subround that can run here is, unless the project's config
        turns it off (`[rounds."NAME"] enabled = false`, which snoozing it
        "never" writes); one whose measure is `never` runs only by its name."""
        if self.manifest.section("due").get("measure") == "never":
            return False
        return bool(self.config().get("enabled", True)) and not self.unavailable()

    def config(self) -> dict[str, Any]:
        """The project's settings for this subround: `.nock/config.toml`'s
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
        """A due rule: the project's config, else its manifest's default."""
        own = self.config()
        if key in own:
            return own[key]
        return self.manifest.section("due").get(key)

    @property
    def since(self) -> str | None:
        last = self.runs.last()
        return last.get("finished") if last else None

    def baseline(self) -> dict[str, Any] | None:
        """What its measure counts from: its last run (the commit it started
        at, when it finished); never run, the fit subround's last run, which set
        it up. None when neither has run."""
        last = self.runs.last()
        if last is not None:
            return last
        if self.name == FIT:
            return None
        fit = next((p for p in subrounds(self.project) if p.name == FIT), None)
        return fit.runs.last() if fit is not None else None

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
        """Why a subround is due, or nothing: on, not snoozed, and its measure
        over its threshold since its last run (fit, never run, is due at
        once; the others stay quiet until fit has run)."""
        if not self.adopted():
            return ""
        if self.runs.last() is None and self.name == FIT:
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
        if self.manifest.round == "nock":
            return skill_of("nock")
        return skill_of(self.manifest.round, self.manifest.subround)

    def standing(self) -> dict[str, Any]:
        last = self.runs.last()
        measure = self.measure()
        return {
            "subround": self.name,
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
        if kind == "records":
            return self.earlier(int(value))
        if kind == "git":
            return "\n".join(self.changes([str(path) for path in value], self.since)) or "(none)"
        raise PreconditionError(f"{self.name}: material {name!r} has an unknown source {kind!r}")

    def earlier(self, count: int) -> str:
        """Its last COUNT runs' records: what each found and changed, so a
        run does not report again what an earlier one did."""
        records = self.runs.all()[-count:]
        if not records:
            return "No earlier run.\n"
        lines = []
        for record in records:
            lines += ["", f"# {record['run']}: {record.get('summary', '')}", ""]
            lines += [
                f"- {change.get('kind')}: {change.get('target')} — {change.get('why')}"
                for change in record.get("changes") or []
            ] or ["Nothing recorded."]
        return "\n".join(lines).strip() + "\n"

    def reads(self) -> list[str]:
        names = list(self.manifest.section("lead").get("reads") or [])
        for agent in self.manifest.data.get("agents") or []:
            names += [name for name in agent.get("reads") or [] if name not in names]
        return names

    # --- a run ------------------------------------------------------------------------

    @property
    def files(self) -> list[str]:
        return list(self.manifest.section("lead").get("writes") or ["report.md"])

    def start(self) -> dict[str, Any]:
        """Start a run — or pick up the one started and not finished, its
        material left as it was written; another run the same day is `DATE-2`."""
        problem = self.unavailable()
        if problem:
            raise PreconditionError(f"{self.name} cannot run here: {problem}")
        name = self.runs.current()
        session = self.project.current_session()
        if name is not None:
            kept = self.runs.scratch / name / RUN_FILE
            started = read_json(kept)
            if session and session not in started.get("sessions", []):
                write_json(kept, {**started, "sessions": [*started.get("sessions", []), session]})
            return {
                **self.started(name, started["material"]),
                "picked_up": f"the run {name}, started {started['started']} and not "
                "finished; its material stands as written then",
            }
        name = self.runs.new_name()
        scratch = self.runs.scratch / name
        scratch.mkdir(parents=True, exist_ok=True)
        material = {}
        for part in self.reads():
            (scratch / f"{part}.md").write_text(self.material(part))
            material[part] = str(scratch / f"{part}.md")
        begun = self.hook("begun")
        write_json(
            scratch / RUN_FILE,
            {
                "run": name,
                "subround": self.name,
                "since": self.since,
                "started": now(),
                "commit": head(self.project),
                "sessions": [session] if session else [],
                "material": material,
                **(begun(self) if begun else {}),
            },
        )
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
            "subround": self.name,
            "run": name,
            "since": self.since,
            "report": "your final message reports the subround to the session that ran it: what it"
            " found and changed, what needs the owner's word, and where the report file is",
            "brief": lead.read_text().strip() if lead.is_file() else "",
            "material": material,
            "agents": agents,
            "write": [str(self.runs.scratch / name / file) for file in self.files],
            "submit": f'.nock/nock reflect --submit \'{{"subround": "{self.name}", "summary": …,'
            ' "changes": [{"kind": …, "target": …, "why": …, "expect": …}]}\'',
        }

    def unwritten(self, name: str) -> list[str]:
        directory = self.runs.scratch / name
        return [
            file
            for file in self.files
            if not (directory / file).is_file() or not (directory / file).read_text().strip()
        ]

    def problems(self, finishing: bool) -> list[str]:
        """What its end finds: its checks (only the quick ones for a run left
        open), and what its `material.py` says of the run."""
        end = self.manifest.section("end")
        names = list(end.get("checks" if finishing else "quick") or [])
        found = Checks(self.project).run(names).problems() if names else []
        check = self.hook("problems")
        return found + (list(check(self)) if check else [])

    def submit(self, record: Record) -> dict[str, Any]:
        """Check the run and record it: its files written, its checks
        passing, the record kept beside them, committed."""
        name = self.runs.current()
        if name is None:
            raise PreconditionError(
                f"no {self.name} run is under way — `.nock/nock reflect {self.name}` starts one"
            )
        kinds = self.manifest.section("end").get("kinds")
        if kinds:
            wrong = sorted({change["kind"] for change in record["changes"]} - set(kinds))
            if wrong:
                raise UsageError(
                    f"{self.name} records changes of kind {', '.join(kinds)}, not {', '.join(wrong)}"
                )
        scratch = self.runs.scratch / name
        missing = self.unwritten(name)
        if missing:
            raise PreconditionError(f"write {' and '.join(missing)} in {scratch} first")
        problems = self.problems(finishing=True)
        if problems:
            raise Failed(f"the {self.name} run does not pass its checks yet", problems)
        started = read_json(scratch / RUN_FILE)
        kept = self.hook("kept")
        directory = self.runs.directory / name
        write_json(
            directory / RECORD_FILE,
            {
                **record,
                "run": name,
                "subround": self.name,
                "since": started["since"],
                "started": started["started"],
                "commit": started.get("commit"),
                "finished": now(),
                **(kept(self, started) if kept else {}),
            },
        )
        commit(
            self.project,
            f"{self.name} run {name}: {record['summary']}",
            [str(path) for path in self.manifest.section("end").get("commit") or []],
            directory / RECORD_FILE,
        )
        return {
            "subround": self.name,
            "run": name,
            "record": str(directory / RECORD_FILE),
            "wrote": [str(scratch / file) for file in self.files],
            "report": "now report the subround to the session that ran it, in your final message",
        }

    def left_open(self, session: str) -> str | None:
        """What a session that started this subround's run, still under way,
        has left to do before it may end; nothing otherwise."""
        name = self.runs.current()
        if name is None:
            return None
        started = read_json(self.runs.scratch / name / RUN_FILE)
        if session not in started.get("sessions", []):
            return None
        owed = [f"write {file} in {self.runs.scratch / name}" for file in self.unwritten(name)]
        if not owed:
            owed += [f"fix what its checks find: {problem}" for problem in self.problems(False)]
        owed.append(
            f'then `.nock/nock reflect --submit \'{{"subround": "{self.name}", …}}\'` records it'
        )
        return (
            f"nock: the {self.name} run {name} is under way and not finished — "
            + "; ".join(owed)
            + ". Finish it, or tell the owner why it stays open."
        )


def head(project: Project) -> str | None:
    try:
        return Git(project.here)("rev-parse", "HEAD") or None
    except GitError:
        return None


def is_lockfile(path: str, named: list[str]) -> bool:
    """A lockfile no count takes in, unless one of the subround's globs names it."""
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
    """The files among GLOBS changed since COMMIT: any one makes a subround due."""
    return [path for _, path in numstat(project, commit) if matches(path, globs)]


def agent_type(manifest: Manifest, agent: str) -> str:
    """Its subagent type: `<round>-<subround>` when it is its subround's
    one agent, else `<round>-<subround>-<agent>`."""
    agents = manifest.data.get("agents") or []
    base = f"{manifest.round}-{manifest.subround}"
    return base if len(agents) == 1 else f"{base}-{agent}"


def submit(project: Project, record: Record) -> dict[str, Any]:
    """`nock reflect --submit`: the record checked, given to its subround."""
    validate(record, schema())
    found = [subround for subround in subrounds(project) if subround.name == record["subround"]]
    if not found:
        raise NotFoundError(f"no subround {record['subround']!r}")
    return found[0].submit(record)


def commit(project: Project, message: str, paths: list[str], record: Path) -> None:
    """Commit a run: the paths its manifest names in the working tree, and
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
    # The `shared` lock: its record is committed in the main checkout, as everything there is.
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
