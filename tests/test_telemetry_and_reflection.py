"""Sessions read into telemetry, the hooks around them, and reflection rounds:
what a round's parts read, a round that finishes — or does not — and
sharing its summary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from nock.hooks import HookRunner
from nock.project import Project
from nock.reflect import Reflection, Rounds, shape
from nock.sessions import Sessions, encoded
from nock.share import Sharing

from .conftest import git, nock, write_tool


def transcript(
    project: Project,
    session: str,
    prompts: list[str],
    commands: list[tuple[str, int, bool]],
    *,
    entrypoint: str = "cli",
    model: str = "claude-test",
) -> Path:
    """A Claude Code transcript: the human's prompts, then Bash calls — each a
    command, how many bytes it printed and whether it failed — a second apart,
    from a session someone works in (`cli`) or a `claude -p` run (`sdk-cli`)."""
    directory = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / encoded(project.root)
    directory.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    second = 0
    # An hour ago, so a round's window in days holds it whatever today is.
    start = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)

    def moment() -> str:
        return (start + timedelta(seconds=second)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    for prompt in prompts:
        records.append(
            {
                "type": "user",
                "timestamp": moment(),
                "cwd": str(project.root),
                "entrypoint": entrypoint,
                "message": {"role": "user", "content": prompt},
            }
        )
    for index, (command, size, failed) in enumerate(commands):
        second += 1
        records.append(
            {
                "type": "assistant",
                "timestamp": moment(),
                "message": {
                    "id": f"m{index}",
                    "model": model,
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "cache_read_input_tokens": 1000,
                    },
                    "content": [
                        {
                            "type": "tool_use",
                            "id": f"t{index}",
                            "name": "Bash",
                            "input": {"command": command},
                        }
                    ],
                },
            }
        )
        second += 1
        records.append(
            {
                "type": "user",
                "timestamp": moment(),
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": f"t{index}",
                            "content": "x" * size,
                            "is_error": failed,
                        }
                    ],
                },
            }
        )
    path = directory / f"{session}.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return path


def test_a_transcript_becomes_prompts_events_and_cost(project: Project) -> None:
    path = transcript(
        project,
        "s1",
        ["Fix the login bug", "no, the other login"],
        [("pytest -q tests/test_login.py | tail -20", 5000, True), (".nock/nock check", 0, False)],
    )
    Sessions(project).ingest(path)
    session = project.store.rows("SELECT * FROM sessions")[0]
    assert session["title"] == "Fix the login bug" and session["prompts"] == 2
    assert session["input_tokens"] == 200 and session["cache_read_tokens"] == 2000
    events = project.store.rows("SELECT tool, input, failed, output_bytes, duration FROM events")
    assert events[0] == {
        "tool": "Bash",
        "input": "pytest -q tests/test_login.py | tail -20",
        "failed": 1,
        "output_bytes": 5000,
        "duration": 1.0,
    }
    prompts = [row["text"] for row in project.store.rows("SELECT text FROM prompts")]
    assert prompts == ["Fix the login bug", "no, the other login"]
    Sessions(project).ingest(path)
    assert len(project.store.rows("SELECT * FROM events")) == 2


def test_the_session_hooks_list_the_tools_and_read_the_transcript(project: Project) -> None:
    write_tool(
        project,
        "work",
        "import nock\n\n@nock.command\ndef deploy(*, target: str = 'staging'):\n    '''Ship it. Carefully.'''\n",
    )
    start = HookRunner(project, {"session_id": "s2"}).handle("SessionStart")
    assert start is not None
    context = start["hookSpecificOutput"]["additionalContext"]
    assert "- deploy [--target TARGET]: Ship it" in context
    path = transcript(project, "s2", ["Deploy it"], [("make deploy", 10, False)])
    assert (
        HookRunner(project, {"session_id": "s2", "transcript_path": str(path)}).handle("SessionEnd")
        is None
    )
    assert project.store.rows("SELECT id FROM sessions") == [{"id": "s2"}]


def test_a_round_is_due_after_enough_sessions(project: Project) -> None:
    local = project.root / ".nock" / "local" / "config.toml"
    local.write_text(local.read_text() + "[reflect]\nsessions = 4\ndays = 3650\n")
    for index in range(3):
        transcript(project, f"s{index}", ["work"], [])
    Sessions(project).catch_up()
    assert Reflection(project).due() == ""
    transcript(project, "s3", ["more work"], [])
    Sessions(project).catch_up()
    assert Reflection(project).due() == "a reflection round is due (4 sessions since the last)"
    start = HookRunner(project, {"session_id": "s9"}).handle("SessionStart")
    assert start is not None and "`/nock-reflect`, which runs one" in start["systemMessage"]


def test_the_material_starts_from_the_work_and_names_the_waste(project: Project) -> None:
    write_tool(
        project, "work", "import nock\n\n@nock.command\ndef unused():\n    '''Never called.'''\n"
    )
    git(project.root, "commit", "--allow-empty", "-qm", "Add login rate limiting")
    for index in range(3):
        transcript(
            project,
            f"session-{index}",
            ["Why does login fail?", "no — run the slow suite too"],
            [
                ("cd app && pytest -q tests/ | tail -30", 9000, True),
                ("grep -rn TODO src", 300, False),
                ("pytest -q tests/", 9000, True),
            ],
        )
    nock(project.root, "unusd")
    for _ in range(12):
        nock(project.root, "calls", "--limit", "1")
    started = Reflection(project).start()
    material = (project.root / started["material"]["process"]).read_text()
    assert material.index("# What the human asked for") < material.index("# The toolbox")
    assert "- no — run the slow suite too" in material
    assert "Add login rate limiting" in material
    assert "pytest,6,3,6,3," in material
    assert "pytest → grep ×3" in material
    assert "candidates to retire or merge: unused" in material
    assert "`unusd` ×1" in material
    assert "This is the first round." in material


def test_shapes_name_what_a_command_is() -> None:
    assert shape("cd src && FOO=1 python -m pytest -x tests") == "python -m pytest"
    assert shape("git log --oneline | head") == "git log"
    assert shape("ls -la") == "ls"


def finish(project: Project, record: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return nock(project.root, "reflect", "finish", json.dumps(record))


RECORD = {
    "summary": "Added nothing; calls is fine.",
    "changes": [
        {"kind": "other", "target": "calls", "why": "used twice", "expect": "calls stays under 1k"}
    ],
}


def test_a_command_that_ran_and_failed_is_not_nock_refusing(project: Project) -> None:
    python = sys.executable
    assert nock(project.root, "run", "--", python, "-c", "exit(1)").returncode == 1
    # pytest's own usage error, or any code a wrapped command exits with, is its answer.
    assert nock(project.root, "run", "--", python, "-c", "exit(42)").returncode == 42
    assert nock(project.root, "calls", "--bogus").returncode == 40
    assert finish(project, RECORD).returncode == 42
    reflection = Reflection(project)
    metrics = reflection.metrics(reflection.window())
    assert (metrics["nock_failed"], metrics["nock_refused"], metrics["nock_broke"]) == (2, 2, 0)
    stats = {row["tool"]: row for row in json.loads(nock(project.root, "stats", "--json").stdout)}
    assert (stats["run"]["failed"], stats["run"]["refused"]) == (2, 0)
    assert (stats["calls"]["failed"], stats["calls"]["refused"]) == (0, 1)


def test_a_round_finishes_with_its_report_its_summary_and_its_numbers(project: Project) -> None:
    for _ in range(2):
        nock(project.root, "calls", "--limit", "1")
    assert finish(project, RECORD).returncode == 42
    started = json.loads(nock(project.root, "reflect", "--json").stdout)
    material = {
        part: (project.root / path).read_text() for part, path in started["material"].items()
    }
    assert "This is the first round." in material["process"]
    assert "Empty until the first reflection round" in material["knowledge"]
    assert "these numbers are the baseline" in material["nock"]
    report, share = (project.root / path for path in started["write"])
    refused = finish(project, RECORD)
    assert refused.returncode == 42 and "write report.md and share.md" in refused.stderr

    report.write_text("# The round\n\nNothing needs you.\n")
    share.write_text("A small project. See README.md, or write to test@example.com.\n")
    named = finish(project, RECORD)
    assert named.returncode == 1 and "names `README.md`" not in named.stdout
    assert "names `test@example.com`" in named.stdout
    share.write_text("A small project, a few days in; the toolbox is barely used yet.\n")
    finished = finish(project, RECORD)
    assert finished.returncode == 0, finished.stdout + finished.stderr
    assert git(project.root, "status", "--porcelain") == ""
    assert git(project.root, "log", "-1", "--format=%s").startswith(
        f"Reflection round {started['round']}"
    )
    (round_,) = Rounds(project).all()
    assert round_["changes"][0]["expect"] == "calls stays under 1k"
    assert round_["snapshot"]["calls"]["calls"] == 2 and round_["since"] is None
    assert round_["metrics"]["nock_calls"] >= 2 and round_["shared"] is None

    again = Reflection(project).start()
    assert again["round"] == f"{started['round']}-2"
    process = (project.root / again["material"]["process"]).read_text()
    assert "# The last round" in process and "expected calls stays under 1k" in process
    nock_material = (project.root / again["material"]["nock"]).read_text()
    assert f"| {started['round']} | this window |" in nock_material


def test_a_second_start_picks_up_the_open_round_and_rewrites_nothing(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    first = json.loads(nock(project.root, "reflect", "--json").stdout)
    process = project.root / first["material"]["process"]
    process.write_text("the material as the first start wrote it\n")
    kept = project.local / "reflections" / first["round"] / "round.json"
    begun = json.loads(kept.read_text())
    for _ in range(3):
        nock(project.root, "calls", "--limit", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s2")
    second = json.loads(nock(project.root, "reflect", "--json").stdout)
    assert second["round"] == first["round"] and second["material"] == first["material"]
    assert f"the round {first['round']}, started {begun['started']}" in second["picked_up"]
    assert process.read_text() == "the material as the first start wrote it\n"
    again = json.loads(kept.read_text())
    assert again["metrics"] == begun["metrics"] and again["sessions"] == ["s1", "s2"]


def test_a_summary_is_vetted_and_shared_only_when_sent(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[dict[str, object]] = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"id": 1}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *arguments: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    local = project.root / ".nock" / "local" / "config.toml"
    local.write_text(
        local.read_text()
        + f'[endpoints]\nreflections = "http://127.0.0.1:{server.server_address[1]}/"\n'
    )
    started = Reflection(project).start()
    for path, text in zip(
        started["write"], ("# Report\n", "Early days; little to say.\n"), strict=True
    ):
        (project.root / path).write_text(text)
    assert finish(project, RECORD).returncode == 0
    assert Sharing(project).unshared() == started["round"]
    begun = HookRunner(project, {"session_id": "s1"}).handle("SessionStart")
    assert begun is not None and "summary is not shared yet" in begun["systemMessage"]
    again = HookRunner(project, {"session_id": "s2"}).handle("SessionStart")
    assert again is None or "not shared" not in again.get("systemMessage", "")

    def vetted() -> int:
        return len(project.store.rows("SELECT id FROM sessions WHERE role = 'sharer'"))

    shown = json.loads(nock(project.root, "share", "--json").stdout)
    assert shown["text"] == "Early days, vetted." and received == [] and vetted() == 1
    nock(project.root, "share")
    assert vetted() == 1
    monkeypatch.setenv("FAKE_SHARE", "Early days, says test@example.com.")
    named = nock(project.root, "share", '{"again": true}')
    assert named.returncode == 1 and "names `test@example.com`" in named.stdout
    monkeypatch.delenv("FAKE_SHARE")
    sent = nock(project.root, "share", '{"send": true}', "--json")
    assert sent.returncode == 0, sent.stderr
    assert json.loads(sent.stdout)["id"] == 1 and vetted() == 2
    assert received == [{"summary": "Early days, vetted.", "round": started["round"]}]
    assert Sharing(project).unshared() is None
    assert git(project.root, "status", "--porcelain") == ""
    server.shutdown()
    server.server_close()


def test_init_installs_the_skills_and_retires_the_old_ones(project: Project) -> None:
    skills = project.root / ".claude" / "skills"
    lead = (skills / "nock-reflect" / "SKILL.md").read_text()
    assert lead.startswith("---\nname: nock-reflect\n")
    assert lead.endswith("\n---\n\nRun `.nock/nock docs reflection.lead` and do what it says.\n")
    assert "`.nock/nock reflect` prints" in nock(project.root, "docs", "reflection.lead").stdout
    assert {path.name for path in (skills / "nock-reflect").iterdir()} == {"SKILL.md"}
    toolbox = (project.root / ".claude" / "agents" / "nock-reflect-toolbox.md").read_text()
    assert toolbox.endswith("Run `.nock/nock docs reflection.toolbox` and do what it says.\n")
    assert ".nock/nock docs --full tools tools.signature" in (
        nock(project.root, "docs", "reflection.toolbox").stdout
    )
    stale = skills / "nock-reflect" / "process.md"
    stale.write_text("an earlier version's brief\n")
    assert (skills / "nock-triage" / "SKILL.md").read_text().startswith("---\nname: nock-triage\n")
    work = (skills / "nock-work" / "SKILL.md").read_text()
    assert work.endswith("\n---\n\nRun `.nock/nock docs work` and do what it says.\n")
    assert (project.root / ".agents" / "skills" / "nock-work" / "SKILL.md").read_text() == work
    assert not (project.root / ".agents" / "skills" / "nock-triage").exists()
    printed = nock(project.root, "docs", "work").stdout
    assert ".nock/nock docs work.subagent" in printed and "never `--all`" in printed
    assert (
        "Never kill a process you didn't start"
        in nock(project.root, "docs", "work.subagent").stdout
    )
    old = skills / "consolidate" / "SKILL.md"
    old.parent.mkdir()
    old.write_text("---\nname: consolidate\n---\n")
    assert nock(project.root, "init").returncode == 0
    assert not old.parent.exists() and not stale.exists()


def test_a_round_s_window_opens_at_its_moment_whatever_the_machine_s_time_zone(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = Reflection(project).start()
    for path in started["write"]:
        (project.root / path).write_text("Early days; little to say.\n")
    assert finish(project, RECORD).returncode == 0
    (finished,) = (record["finished"] for record in Rounds(project).all())
    # Nine hours east of UTC: the window's `Z` moment must not be read as local
    # time, which would count this commit from an hour before the round.
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    before = datetime.fromisoformat(finished.replace("Z", "+00:00")) - timedelta(hours=1)
    monkeypatch.setenv("GIT_COMMITTER_DATE", before.isoformat())
    git(project.root, "commit", "--allow-empty", "-qm", "Before the round")
    reflection = Reflection(project)
    assert reflection.metrics(reflection.window())["commits"] == 0


def test_a_session_cannot_end_its_turn_with_the_round_it_started_open(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    def stop(session: str, active: bool = False) -> dict[str, object] | None:
        payload = {"session_id": session, "stop_hook_active": active}
        return HookRunner(project, payload).handle("Stop")

    assert stop("s1") is None
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    started = json.loads(nock(project.root, "reflect", "--json").stdout)
    assert started["finish"] == ".nock/nock reflect finish JSON"
    refused = stop("s1")
    assert refused is not None and refused["decision"] == "block"
    reason = str(refused["reason"])
    assert f"the reflection round {started['round']} is under way and not finished" in reason
    assert "write report.md" in reason and "write share.md" in reason
    assert "`.nock/nock reflect finish JSON` records it" in reason
    assert stop("s1", active=True) is None
    assert stop("s2") is None
    for path, text in zip(started["write"], ("# Report\n", "Early days.\n"), strict=True):
        (project.root / path).write_text(text)
    (project.root / ".nock" / "topics" / "map.md").write_text("- [D9] holds.\n")
    reason = str((stop("s1") or {})["reason"])
    assert "report.md" not in reason and "[D9] is no item" in reason
    (project.root / ".nock" / "topics" / "map.md").write_text("# The map\n")
    assert finish(project, RECORD).returncode == 0
    assert stop("s1") is None


def test_the_stop_waits_with_a_round_s_lead_while_its_parts_run_in_the_background(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    assert nock(project.root, "reflect").returncode == 0
    path = project.root / "s1.jsonl"

    def launched(agent: str) -> dict[str, object]:
        text = f"Async agent launched successfully.\nagentId: {agent} (internal ID)\n"
        result = {
            "type": "tool_result",
            "tool_use_id": agent,
            "content": [{"type": "text", "text": text}],
        }
        return {"type": "user", "message": {"role": "user", "content": [result]}}

    def notified(agent: str) -> dict[str, object]:
        text = f"<task-notification>\n<task-id>{agent}</task-id>\n<status>completed</status>\n"
        return {"type": "user", "message": {"role": "user", "content": text}}

    def stop(*records: dict[str, object]) -> dict[str, object] | None:
        path.write_text("".join(json.dumps(record) + "\n" for record in records))
        payload = {"session_id": "s1", "transcript_path": str(path), "stop_hook_active": False}
        return HookRunner(project, payload).handle("Stop")

    parts = [launched(agent) for agent in ("toolbox", "map", "nock")]
    assert stop(*parts) is None
    assert stop(*parts, notified("map"), notified("nock")) is None
    refused = stop(*parts, notified("map"), notified("nock"), notified("toolbox"))
    assert refused is not None and refused["decision"] == "block"
    assert "is under way and not finished" in str(refused["reason"])


def test_reflect_starts_the_default_kind_and_names_the_others(project: Project) -> None:
    unknown = nock(project.root, "reflect", "lgika")
    assert unknown.returncode == 40 and "did you mean `reflect logika`" in unknown.stderr
    assert nock(project.root, "reflect", "start").returncode == 40
    assert nock(project.root, "reflect", "--topic", "logika").returncode == 40
    listed = nock(project.root).stdout
    assert "reflect —" in listed and "reflect logika —" in listed
    assert "reflect logika finish JSON —" in listed
