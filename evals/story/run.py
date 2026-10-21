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
installed and keeps `.nock/` (toolbox, questions, map) and its skills,
running `/reflect` and `/consolidate` each week.
"""

from __future__ import annotations

import argparse
import json
import os
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

The engineer's questions to you, filed in the team's question tracker
(each with its options, numbered from 1):

{questions}

The engineer's last message:

{final}

Answer as the owner would. Reply with JSON only:
{{"answers": [{{"number": N, "choice": K or null, "comment": "…" or null}}],
  "reply": "what you say back to the engineer, or an empty string"}}
Answer every tracked question. Say something in `reply` only when the last
message asks you something or waits on you; otherwise leave it empty."""


def environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in PARENT_SESSION_VARIABLES}


def git(directory: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=directory, check=True, capture_output=True, text=True
    ).stdout.strip()


def claude(
    prompt: str, directory: Path, model: str, session: str, resume: bool = False
) -> dict[str, Any]:
    """One headless turn; its result record (cost, turns, usage, the final message)."""
    command = ["claude", "-p", "--output-format", "json", "--permission-mode", "bypassPermissions"]
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
        if any(self.carried.iterdir()):
            shutil.copytree(self.carried, self.repo, dirs_exist_ok=True)
            git(self.repo, "add", "-A")
            git(self.repo, "commit", "-qm", "Team tooling", "--no-verify")

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
        setup = run_script(self.world.file(report, "setup.py"), self.repo)
        if setup.returncode != 0:
            raise SystemExit(f"{report['id']}: setup.py failed: {setup.stderr[-600:]}")
        identity = str(uuid.uuid4())
        message = self.world.file(report, "message.md").read_text()
        records = [claude(message + INSTRUCTIONS, self.repo, self.model, identity)]
        asked = self.questions(identity)
        reply = self.owner(report, records[-1], asked)
        if reply:
            records.append(claude(reply, self.repo, self.model, identity, resume=True))
        verdict = run_script(self.world.file(report, "verify.py"), self.repo)
        checks = [json.loads(line) for line in verdict.stdout.splitlines() if line.startswith("{")]
        if learning:
            self.keep()
        usage = [record.get("usage") or {} for record in records]
        return {
            "arm": self.name, "week": report["week"], "repeat": repeat, "report": report["id"],
            "family": report.get("family"), "session": identity,
            "passed": verdict.returncode == 0,
            "checks": sum(1 for check in checks if check.get("ok")), "of": len(checks),
            "cost": sum(float(record.get("total_cost_usd") or 0) for record in records),
            "turns": sum(int(record.get("num_turns") or 0) for record in records),
            "seconds": sum(record["seconds"] for record in records),
            "input_tokens": sum(int(item.get("input_tokens") or 0) for item in usage),
            "output_tokens": sum(int(item.get("output_tokens") or 0) for item in usage),
            "questions": len(asked), "owner_replied": bool(reply),
            "final": str(records[-1].get("result") or "")[-600:],
        }  # fmt: skip

    def questions(self, identity: str) -> list[dict[str, Any]]:
        directory = self.repo / ".nock" / "questions"
        if not directory.is_dir():
            return []
        found = [json.loads(path.read_text()) for path in sorted(directory.glob("[0-9]*.json"))]
        return [
            question
            for question in found
            if question["state"] == "open" and question["asked"].get("session") == identity
        ]

    def owner(
        self, report: dict[str, Any], record: dict[str, Any], asked: list[dict[str, Any]]
    ) -> str:
        """The scripted owner: answers the session's tracked questions on the
        page's behalf, and replies when its last message waits on the owner."""
        final = str(record.get("result") or "")
        if not asked and "?" not in final[-800:]:
            return ""
        shown = [
            {key: question[key] for key in ("number", "title", "context", "options", "recommended")}
            for question in asked
        ]
        prompt = OWNER.format(
            message=self.world.file(report, "message.md").read_text(),
            owner=self.world.file(report, "owner.md").read_text(),
            questions=json.dumps(shown, indent=2) if shown else "(none)",
            final=final[-3000:],
        )
        with tempfile.TemporaryDirectory() as scratch:
            answer = claude(prompt, Path(scratch), "claude-sonnet-5-5", str(uuid.uuid4()))
        text = str(answer.get("result") or "").strip().removeprefix("```json").removesuffix("```")
        try:
            decided = json.loads(text)
        except json.JSONDecodeError:
            return ""
        answered = 0
        for item in decided.get("answers", []):
            path = self.repo / ".nock" / "questions" / f"{int(item['number']):04d}.json"
            if not path.is_file():
                continue
            question = json.loads(path.read_text())
            question["owner"] = {
                "choice": item.get("choice"),
                "comment": item.get("comment"),
                "elaborate": False,
            }
            question["state"] = "pending"
            question["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            path.write_text(json.dumps(question, indent=2) + "\n")
            answered += 1
        reply = str(decided.get("reply") or "").strip()
        if answered and not reply:
            reply = "I answered your question(s) in the tracker."
        return reply

    def reflect(self, week: int, identities: list[str]) -> None:
        """The week's reflection, as the arm does it; what it changed is kept."""
        if self.name == "bare":
            return
        self.checkout(week)
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
            prompts = ["/reflect", "/consolidate"]
        for prompt in prompts:
            record = claude(prompt, self.repo, self.model, str(uuid.uuid4()))
            log(self.out, {"arm": self.name, "week": week, "reflection": prompt[:20], "cost": record.get("total_cost_usd"), "seconds": record["seconds"]})  # fmt: skip
        self.keep()


def log(out: Path, entry: dict[str, Any]) -> None:
    with (out / "outcomes.jsonl").open("a") as handle:
        handle.write(json.dumps(entry) + "\n")
    print(json.dumps({key: entry[key] for key in entry if key != "final"}), flush=True)


def run(out: Path, arms: list[str], repeats: int, model: str) -> None:
    world = World(out / "world")
    *training, test = world.weeks

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
    jobs = [(name, repeat) for name in arms for repeat in range(1, repeats + 1)]
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        list(pool.map(examine, jobs))
    report(out)


# --- the report -----------------------------------------------------------------------


def report(out: Path) -> None:
    entries = [json.loads(line) for line in (out / "outcomes.jsonl").read_text().splitlines()]
    sessions = [entry for entry in entries if "report" in entry]
    test = max(entry["week"] for entry in sessions)
    lines = ["# The story eval", ""]
    for title, chosen in (("Weeks 1–3 (learning)", [e for e in sessions if e["week"] < test]), (f"Week {test} (frozen, every repeat)", [e for e in sessions if e["week"] == test])):  # fmt: skip
        lines += [f"## {title}", "", "| arm | sessions | resolved | checks | cost | turns | minutes | questions |", "|---|---|---|---|---|---|---|---|"]  # fmt: skip
        by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in chosen:
            by_arm[entry["arm"]].append(entry)
        for arm, rows in sorted(by_arm.items()):
            checks = sum(row["checks"] for row in rows) / max(1, sum(row["of"] for row in rows))
            lines.append(
                f"| {arm} | {len(rows)} | {sum(row['passed'] for row in rows) / len(rows):.0%} | {checks:.0%} "
                f"| ${statistics.mean(row['cost'] for row in rows):.2f} | {statistics.mean(row['turns'] for row in rows):.0f} "
                f"| {statistics.mean(row['seconds'] for row in rows) / 60:.1f} | {sum(row['questions'] for row in rows)} |"
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
        run(arguments.out, arguments.arms.split(","), arguments.repeats, arguments.model)
    else:
        report(arguments.out)


if __name__ == "__main__":
    main()
