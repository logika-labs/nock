"""The story eval: does nock help agents through a month of real work? A
model writes the month (`story`), an agent builds it as a world — the
company's repository with a tag per week, and per report a message, what the
owner knows, a setup, a reference resolution and a verifier (`build`,
`validate`) — and each arm then works through it (`run`): weeks 1–3 to learn,
with a reflection after each, and the last week, frozen, several times over.
A scripted owner answers what the agents ask. `report` compares the arms.

    uv run python evals/story/run.py story OUT [--model claude-fable-5-1]
    uv run python evals/story/run.py build OUT [--model claude-opus-5-5] [--rounds 3]
    uv run python evals/story/run.py validate OUT/world
    uv run python evals/story/run.py run OUT [--arms bare,skills,nock] [--repeats 3] [--model …]
    uv run python evals/story/run.py report OUT

Arms: `bare` keeps nothing between sessions; `skills` keeps `CLAUDE.md` and
`.claude/`, which a reflection session rewrites each week; `nock` has nock
installed and keeps `.nock/` (toolbox, topics, map) and its skills,
running `/nock-reflect` each week. The owner judges the nock arm's
decisions now and then, as a real owner would.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
NOCK = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))

from permissions import ANSWERING, ENGINEER  # noqa: E402

CARRIED = {
    "bare": [],
    "skills": ["CLAUDE.md", ".claude"],
    "nock": ["CLAUDE.md", ".claude", ".nock"],
}
PARENT_SESSION_VARIABLES = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID")
INSTRUCTIONS = """

---
You are an engineer at this company, and this just landed on you. Work on it
in this repository until it is resolved. If it asks for numbers or a list,
write the answer to `ANSWER.md` at the repository root."""
OWNER = """You are the owner of a small software company. One of your engineers is
working on this report:

{message}

What you know, in your own words — answer only from this; you know the
business, not the code, and you never guess at causes:

{owner}

The engineer's last message:

{final}

If the message asks you something or waits on you — a question, a request
for your OK, "say yes and I'll do it" — answer as the owner would, in a few
sentences, as a chat reply. If it does not, reply with exactly NOTHING."""
REVIEW = """You are the owner of a small software company. Your engineers submit the
decisions they make as they work, and you review them when you get round to
it. You know the business, not the code: judge what each decision means for
the business, from what you know about the report it came from; leave
alone what you cannot judge.

{decisions}

Reply with JSON only: a list of
{{"ref": REF, "verdict": "accepted" or "rejected" or null, "comment": "…" or null}}
for each decision — null to leave it open. Reject a decision when it goes
against what you know, and say why in the comment; accept it when it fits,
with a comment when there is something the engineers should know."""
# How often the owner gets round to reviewing, after a session (seeded, so runs repeat).
REVIEW_CHANCE = 0.5
OWNER_MODEL = "claude-sonnet-5-5"


def environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in PARENT_SESSION_VARIABLES}


def git(directory: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=directory, check=True, capture_output=True, text=True
    ).stdout.strip()


def claude(
    prompt: str,
    directory: Path,
    model: str,
    session: str,
    resume: bool = False,
    permissions: list[str] = ENGINEER,
) -> dict[str, Any]:
    """One headless turn; its result record (cost, turns, usage, the final message)."""
    command = ["claude", "-p", "--output-format", "json", *permissions]
    command += ["--model", model] if model else []
    command += ["--resume", session] if resume else ["--session-id", session]
    started = time.monotonic()
    result = subprocess.run(
        [*command, "--", prompt], cwd=directory, capture_output=True, text=True, env=environment()
    )
    try:
        record = json.loads(result.stdout)
    except json.JSONDecodeError:
        record = {"result": (result.stdout + result.stderr)[-2000:], "is_error": True}
    record["seconds"] = round(time.monotonic() - started, 1)
    return record


def run_script(script: Path, checkout: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), str(checkout)], capture_output=True, text=True, timeout=1800
    )


# --- the world ------------------------------------------------------------------------


class World:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.repo = directory / "repo"
        self.reports: list[dict[str, Any]] = json.loads((directory / "world.json").read_text())[
            "reports"
        ]

    @property
    def weeks(self) -> list[int]:
        return sorted({report["week"] for report in self.reports})

    def of_week(self, week: int) -> list[dict[str, Any]]:
        return [report for report in self.reports if report["week"] == week]

    def file(self, report: dict[str, Any], name: str) -> Path:
        return self.directory / "reports" / report["id"] / name

    def problems(self) -> list[str]:
        """Every report's verifier fails on its setup and passes on its resolution,
        on a checkout like an arm's: the week's history only."""
        problems = []
        tags = git(self.repo, "tag").split()
        for week in self.weeks:
            if f"week-{week}" not in tags:
                problems.append(f"no tag week-{week}")
        for report in self.reports:
            missing = [
                name
                for name in ("message.md", "owner.md", "setup.py", "resolve.py", "verify.py")
                if not self.file(report, name).is_file()
            ]
            if missing:
                problems.append(f"{report['id']}: missing {', '.join(missing)}")
                continue
            with tempfile.TemporaryDirectory() as scratch:
                checkout = Path(scratch) / "repo"
                git(Path(scratch), "init", "-q", "-b", "main", str(checkout))
                git(checkout, "fetch", "-q", "--no-tags", str(self.repo), f"refs/tags/week-{report['week']}")  # fmt: skip
                git(checkout, "checkout", "-q", "-B", "main", "FETCH_HEAD^{commit}")
                for step, expected in (("setup.py", None), ("verify.py", False), ("resolve.py", None), ("verify.py", True)):  # fmt: skip
                    result = run_script(self.file(report, step), checkout)
                    if expected is None and result.returncode != 0:
                        problems.append(f"{report['id']}: {step} failed: {result.stderr[-600:]}")
                        break
                    if expected is not None and (result.returncode == 0) != expected:
                        state = "after setup" if expected is False else "after resolve"
                        problems.append(
                            f"{report['id']}: verify.py {'passes' if not expected else 'fails'} {state}: {(result.stdout + result.stderr)[-600:]}"
                        )
                        break
        return problems


def story(out: Path, model: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    # The writer sees the brief and nothing else: no word of what the story is for.
    shutil.copy2(HERE / "brief.md", out / "brief.md")
    prompt = "Read brief.md, in the current directory, in full. Then write STORY.md beside it, as it asks. Work only in the current directory."
    record = claude(prompt, out, model, str(uuid.uuid4()))
    print(f"story: ${record.get('total_cost_usd', 0):.2f}, {record['seconds']}s", flush=True)


def build(out: Path, model: str, rounds: int) -> None:
    if not (out / "STORY.md").is_file():
        raise SystemExit(f"{out}/STORY.md is missing — run `story` first")
    brief = (HERE / "build.md").read_text().replace("{{ harness }}", str(Path(__file__).resolve()))
    session = str(uuid.uuid4())
    record = claude(brief, out, model, session)
    for attempt in range(rounds):
        problems = (
            World(out / "world").problems()
            if (out / "world" / "world.json").is_file()
            else ["world/world.json is missing"]
        )
        print(f"build round {attempt + 1}: ${record.get('total_cost_usd', 0):.2f}, {len(problems)} problem(s)", flush=True)  # fmt: skip
        if not problems:
            return
        prompt = "`validate` still reports these problems; fix them:\n\n" + "\n".join(problems)
        record = claude(prompt, out, model, session, resume=True)
    raise SystemExit("the world does not validate yet")


# --- an arm ---------------------------------------------------------------------------


class Arm:
    """One arm's repository: a clone of the world, the files it keeps between
    sessions (`carried/`), and its outcomes."""

    def __init__(self, out: Path, world: World, name: str, model: str, label: str = "") -> None:
        self.out, self.world, self.name, self.model = out, world, name, model
        self.directory = out / "arms" / (label or name)
        self.carried = self.directory / "carried"
        # Which report each session worked on, so the owner knows what a decision was about.
        self.sessions: dict[str, dict[str, Any]] = {}
        self.chance = random.Random(name)

    @property
    def repo(self) -> Path:
        """The arm's repository, away from the world and the other arms: in
        `OUT/arms/<arm>/repo` the answers would be two directories up."""
        return (self.directory / "repo").resolve()

    def create(self, carried_from: Path | None = None) -> None:
        if (self.directory / "repo").exists():
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        repo = Path(tempfile.mkdtemp(prefix="kerb-")) / "kerb"
        git(repo.parent, "init", "-q", "-b", "main", str(repo))
        (self.directory / "repo").symlink_to(repo)
        git(self.repo, "config", "user.name", "Engineer")
        git(self.repo, "config", "user.email", "engineer@example.com")
        if carried_from is not None:
            shutil.copytree(carried_from, self.carried)
            if (carried_from.parent / "work").is_dir():
                shutil.copytree(carried_from.parent / "work", self.directory / "work")
            return
        self.carried.mkdir()
        if self.name == "nock":
            self.checkout(self.world.weeks[0])
            subprocess.run(
                [sys.executable, "-m", "nock", "init"],
                cwd=self.repo,
                check=True,
                capture_output=True,
                env={**environment(), "PYTHONPATH": str(NOCK / "src")},
            )
            self.keep()

    def checkout(self, week: int) -> None:
        """The week's state, the arm's kept files on top, committed as the team's
        tooling. Only the week's history is fetched, without tags or a remote:
        later weeks hold the team's fixes."""
        if subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD"], cwd=self.repo, capture_output=True).returncode == 0:  # fmt: skip
            git(self.repo, "reset", "-q", "--hard")
            git(self.repo, "clean", "-qfdx", "-e", ".nock/local")
        git(self.repo, "fetch", "-q", "--no-tags", str(self.world.repo), f"refs/tags/week-{week}")
        git(self.repo, "checkout", "-q", "-B", "main", "FETCH_HEAD^{commit}")
        (self.repo / ".git" / "FETCH_HEAD").unlink()
        # Branches a session made go with it; what it did carries as `work/`.
        for branch in git(
            self.repo, "for-each-ref", "--format=%(refname:short)", "refs/heads"
        ).split():
            if branch != "main":
                git(self.repo, "branch", "-q", "-D", branch)
        if any(self.carried.iterdir()):
            shutil.copytree(self.carried, self.repo, dirs_exist_ok=True)
            git(self.repo, "add", "-A")
            git(self.repo, "commit", "-qm", "Team tooling", "--no-verify")

    # What happened in a session — the setup's commits (the trouble) and the
    # engineer's changes (the fix) — carries through the rest of the story, as
    # commits replayed on each later checkout. A later week's tag holds the
    # team's own work too; where the two clash, the team's wins.
    WORK_EXCLUDES = (
        ":(exclude).nock",
        ":(exclude).claude",
        ":(exclude)CLAUDE.md",
        ":(exclude)ANSWER.md",
    )

    def apply_work(self, week: int) -> int:
        """Replay the earlier sessions, this week's and before, each as the
        commits it left; a commit that no longer applies is left out. How many
        sessions came through, whole or in part."""
        applied = 0
        patches = [
            patch
            for earlier in self.world.weeks
            if earlier <= week
            for patch in sorted((self.directory / "work" / f"week-{earlier}").glob("*.mbox"))
        ]
        for patch in patches:
            before = git(self.repo, "rev-parse", "HEAD")
            replayed = subprocess.run(
                ["git", "am", "-q", "--3way", "--committer-date-is-author-date", str(patch)],
                cwd=self.repo, capture_output=True,
            )  # fmt: skip
            # A commit that clashes is skipped, the session's others kept.
            while replayed.returncode != 0 and (self.repo / ".git" / "rebase-apply").is_dir():
                replayed = subprocess.run(["git", "am", "-q", "--skip"], cwd=self.repo, capture_output=True)  # fmt: skip
            if git(self.repo, "rev-parse", "HEAD") != before:
                applied += 1
        return applied

    def save_work(self, week: int, start: str) -> bool:
        """Keep what the session left since `start` — the setup's commits, then
        the engineer's changes as one commit — for the rest of the story."""
        git(self.repo, "add", "-A", "--", ".", *self.WORK_EXCLUDES)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=self.repo).returncode != 0:
            git(self.repo, "commit", "-qm", "Fixes", "--no-verify")
        git(self.repo, "reset", "-q")
        patch = subprocess.run(
            ["git", "format-patch", "--stdout", "--binary", f"{start}..HEAD", "--", ".", *self.WORK_EXCLUDES],
            cwd=self.repo, capture_output=True, check=True,
        ).stdout  # fmt: skip
        if not patch.strip():
            return False
        directory = self.directory / "work" / f"week-{week}"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{len(list(directory.glob('*.mbox'))) + 1:02d}.mbox").write_bytes(patch)
        return True

    def keep(self) -> None:
        """Copy what the arm keeps out of the repository, telemetry left in place."""
        shutil.rmtree(self.carried, ignore_errors=True)
        self.carried.mkdir()
        for name in CARRIED[self.name]:
            source = self.repo / name
            if source.is_dir():
                shutil.copytree(source, self.carried / name, ignore=shutil.ignore_patterns("local"))
            elif source.is_file():
                shutil.copy2(source, self.carried / name)

    def session(self, report: dict[str, Any], repeat: int, learning: bool) -> dict[str, Any]:
        self.checkout(report["week"])
        carried = self.apply_work(report["week"])
        start = git(self.repo, "rev-parse", "HEAD")
        setup = run_script(self.world.file(report, "setup.py"), self.repo)
        if setup.returncode != 0 and carried:
            # This report's trouble does not happen on top of the earlier work: start it clean.
            self.checkout(report["week"])
            carried = 0
            start = git(self.repo, "rev-parse", "HEAD")
            setup = run_script(self.world.file(report, "setup.py"), self.repo)
        if setup.returncode != 0:
            raise SystemExit(f"{report['id']}: setup.py failed: {setup.stderr[-600:]}")
        identity = str(uuid.uuid4())
        message = self.world.file(report, "message.md").read_text()
        records = [claude(message + INSTRUCTIONS, self.repo, self.model, identity)]
        reply = self.owner(report, records[-1])
        if reply:
            records.append(claude(reply, self.repo, self.model, identity, resume=True))
        verdict = run_script(self.world.file(report, "verify.py"), self.repo)
        checks = [json.loads(line) for line in verdict.stdout.splitlines() if line.startswith("{")]
        recorded = self.decisions(identity)
        changed = self.save_work(report["week"], start)
        self.sessions[identity] = report
        reviewed = self.review() if learning and self.chance.random() < REVIEW_CHANCE else 0
        if learning:
            self.keep()
        usage = [record.get("usage") or {} for record in records]
        return {
            "arm": self.name, "week": report["week"], "repeat": repeat, "report": report["id"],
            "family": report.get("family"), "session": identity,
            "passed": verdict.returncode == 0,
            "checks": sum(1 for check in checks if check.get("ok")), "of": len(checks),
            "failed": [check.get("check") for check in checks if not check.get("ok")],
            "work_carried": carried, "work_kept": changed,
            "cost": sum(float(record.get("total_cost_usd") or 0) for record in records),
            "turns": sum(int(record.get("num_turns") or 0) for record in records),
            "seconds": sum(record["seconds"] for record in records),
            "input_tokens": sum(int(item.get("input_tokens") or 0) for item in usage),
            "output_tokens": sum(int(item.get("output_tokens") or 0) for item in usage),
            "decisions": len(recorded), "reviewed": reviewed, "owner_replied": bool(reply),
            "final": str(records[-1].get("result") or "")[-600:],
        }  # fmt: skip

    def decisions(self, identity: str | None = None) -> list[dict[str, Any]]:
        """The arm's decision items — those a session submitted, when it is named —
        each with its topic's ref and the latest version's decision."""
        found = []
        for path in sorted((self.repo / ".nock" / "topics").glob("*/*/item.json")):
            item = json.loads(path.read_text())
            latest = path.parent / str(item["versions"][-1]["version"]) / "decision.json"
            if not latest.is_file():
                continue
            item["ref"] = f"{path.parent.parent.name}/{item['slug']}"
            item["decision"] = json.loads(latest.read_text())
            found.append(item)
        if identity is None:
            return found
        return [item for item in found if item["created"].get("session") == identity]

    def owner(self, report: dict[str, Any], record: dict[str, Any]) -> str:
        """The scripted owner's reply, when the session's last message waits on them."""
        final = str(record.get("result") or "")
        prompt = OWNER.format(
            message=self.world.file(report, "message.md").read_text(),
            owner=self.world.file(report, "owner.md").read_text(),
            final=final[-3000:],
        )
        with tempfile.TemporaryDirectory() as scratch:
            answer = claude(
                prompt, Path(scratch), OWNER_MODEL, str(uuid.uuid4()), permissions=ANSWERING
            )
        reply = str(answer.get("result") or "").strip()
        return "" if reply.upper().startswith("NOTHING") else reply

    def review(self) -> int:
        """The owner gets round to the decisions waiting on them: each judged
        from what they know of the report it came from. How many they judged."""
        waiting = [item for item in self.decisions() if item["verdict"] == "open"]
        if not waiting:
            return 0
        blocks = []
        for decision in waiting:
            report = self.sessions.get(decision["created"].get("session") or "")
            known = (
                self.world.file(report, "owner.md").read_text()
                if report
                else "(a decision from a reflection round, not a report — judge it on its face)"
            )
            shown = {"ref": decision["ref"], "title": decision["title"], **decision["decision"]}
            blocks.append(
                f"## Decision {decision['ref']}\n\nWhat you know about its report:\n\n{known}\n\n```json\n{json.dumps(shown, indent=2)}\n```"
            )
        with tempfile.TemporaryDirectory() as scratch:
            answer = claude(
                REVIEW.format(decisions="\n\n".join(blocks)),
                Path(scratch),
                OWNER_MODEL,
                str(uuid.uuid4()),
                permissions=ANSWERING,
            )
        text = str(answer.get("result") or "").strip().removeprefix("```json").removesuffix("```")
        try:
            verdicts = json.loads(text)
        except json.JSONDecodeError:
            return 0
        reviewed = 0
        for verdict in verdicts if isinstance(verdicts, list) else []:
            if verdict.get("verdict") not in ("accepted", "rejected"):
                continue
            word = {"verdict": verdict["verdict"], **({"comment": verdict["comment"]} if verdict.get("comment") else {})}  # fmt: skip
            subprocess.run(
                [str(self.repo / ".nock" / "nock"), "items", "judge", str(verdict["ref"]), json.dumps(word)],
                cwd=self.repo, capture_output=True, text=True, env=environment(),
            )  # fmt: skip
            reviewed += 1
        log(self.out, {"arm": self.name, "owner_review": reviewed, "waiting": len(waiting), "cost": answer.get("total_cost_usd")})  # fmt: skip
        return reviewed

    def reflect(self, week: int, identities: list[str]) -> None:
        """The week's reflection, as the arm does it, on the work so far; what
        it changed is kept."""
        if self.name == "bare":
            return
        self.checkout(week)
        self.apply_work(week)
        if self.name == "skills":
            projects = (
                Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"
            )
            transcripts = [
                str(path)
                for identity in identities
                for path in projects.glob(f"*/{identity}.jsonl")
            ]
            prompts = [(HERE / "reflect-skills.md").read_text().replace("{{ transcripts }}", "\n".join(f"- {path}" for path in transcripts))]  # fmt: skip
        else:
            prompts = ["/nock-reflect"]
        for prompt in prompts:
            record = claude(prompt, self.repo, self.model, str(uuid.uuid4()))
            log(self.out, {"arm": self.name, "week": week, "reflection": prompt[:20], "cost": record.get("total_cost_usd"), "seconds": record["seconds"]})  # fmt: skip
        self.keep()


def log(out: Path, entry: dict[str, Any]) -> None:
    with (out / "outcomes.jsonl").open("a") as handle:
        handle.write(json.dumps(entry) + "\n")
    print(json.dumps({key: entry[key] for key in entry if key != "final"}), flush=True)


def run(out: Path, arms: list[str], repeats: int, model: str, weeks: int | None) -> None:
    """Each arm learns through the first weeks, then the last week is run
    `repeats` times, frozen. With `weeks`, only that many learning weeks, and
    no test week unless that is all of them."""
    world = World(out / "world")
    *training, test = world.weeks
    complete = weeks is None or weeks >= len(training)
    training = training if weeks is None else training[:weeks]

    def learn(name: str) -> None:
        arm = Arm(out, world, name, model)
        arm.create()
        for week in training:
            outcomes = [arm.session(report, 1, learning=True) for report in world.of_week(week)]
            for outcome in outcomes:
                log(out, outcome)
            arm.reflect(week, [outcome["session"] for outcome in outcomes])

    def examine(job: tuple[str, int]) -> None:
        name, repeat = job
        arm = Arm(out, world, name, model, label=f"{name}-test-{repeat}")
        arm.create(carried_from=Arm(out, world, name, model).carried)
        for report in world.of_week(test):
            log(out, arm.session(report, repeat, learning=False))

    with ThreadPoolExecutor(max_workers=len(arms)) as pool:
        list(pool.map(learn, arms))
    if not complete:
        report(out)
        return
    jobs = [(name, repeat) for name in arms for repeat in range(1, repeats + 1)]
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        list(pool.map(examine, jobs))
    report(out)


# --- the report -----------------------------------------------------------------------


def report(out: Path) -> None:
    entries = [json.loads(line) for line in (out / "outcomes.jsonl").read_text().splitlines()]
    sessions = [entry for entry in entries if "report" in entry]
    test = World(out / "world").weeks[-1]
    lines = ["# The story eval", ""]
    for title, chosen in (("Weeks 1–3 (learning)", [e for e in sessions if e["week"] < test]), (f"Week {test} (frozen, every repeat)", [e for e in sessions if e["week"] == test])):  # fmt: skip
        lines += [f"## {title}", "", "| arm | sessions | resolved | checks | cost | turns | minutes | decisions |", "|---|---|---|---|---|---|---|---|"]  # fmt: skip
        by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in chosen:
            by_arm[entry["arm"]].append(entry)
        for arm, rows in sorted(by_arm.items()):
            checks = sum(row["checks"] for row in rows) / max(1, sum(row["of"] for row in rows))
            lines.append(
                f"| {arm} | {len(rows)} | {sum(row['passed'] for row in rows) / len(rows):.0%} | {checks:.0%} "
                f"| ${statistics.mean(row['cost'] for row in rows):.2f} | {statistics.mean(row['turns'] for row in rows):.0f} "
                f"| {statistics.mean(row['seconds'] for row in rows) / 60:.1f} | {sum(row.get('decisions', row.get('questions', 0)) for row in rows)} |"
            )
        lines.append("")
    lines += [f"## Week {test}, per report: resolved in how many repeats", "", "| report | family | " + " | ".join(sorted({e['arm'] for e in sessions})) + " |", "|---|---|" + "---|" * len({e['arm'] for e in sessions})]  # fmt: skip
    for identity in sorted({e["report"] for e in sessions if e["week"] == test}):
        rows = [e for e in sessions if e["report"] == identity]
        cells = []
        for arm in sorted({e["arm"] for e in sessions}):
            mine = [row for row in rows if row["arm"] == arm]
            cells.append(f"{sum(row['passed'] for row in mine)}/{len(mine)}")
        lines.append(f"| {identity} | {rows[0].get('family')} | " + " | ".join(cells) + " |")
    reflections = [entry for entry in entries if "reflection" in entry]
    lines += ["", "Reflection cost: " + ", ".join(f"{arm} ${sum(e.get('cost') or 0 for e in reflections if e['arm'] == arm):.2f}" for arm in sorted({e['arm'] for e in reflections})) if reflections else ""]  # fmt: skip
    (out / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("story", "build", "run", "report"):
        command = commands.add_parser(name)
        command.add_argument("out", type=Path)
        if name == "story":
            command.add_argument("--model", default="claude-fable-5-1")
        if name in ("build", "run"):
            command.add_argument("--model", default="claude-opus-5-5")
        if name == "build":
            command.add_argument("--rounds", type=int, default=3)
        if name == "run":
            command.add_argument("--arms", default="bare,skills,nock")
            command.add_argument("--repeats", type=int, default=3)
            command.add_argument(
                "--weeks",
                type=int,
                help="learning weeks to run; the test week only after all of them",
            )
    commands.add_parser("validate").add_argument("world", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "story":
        story(arguments.out, arguments.model)
    elif arguments.command == "build":
        build(arguments.out, arguments.model, arguments.rounds)
    elif arguments.command == "validate":
        problems = World(arguments.world).problems()
        print("\n".join(problems) or "the world validates")
        sys.exit(1 if problems else 0)
    elif arguments.command == "run":
        run(
            arguments.out,
            arguments.arms.split(","),
            arguments.repeats,
            arguments.model,
            arguments.weeks,
        )
    else:
        report(arguments.out)


if __name__ == "__main__":
    main()
