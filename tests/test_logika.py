"""The logika round: in a Logika project — a `logika.json` ledger, the `logika`
CLI on PATH (here a stand-in script) — its subrounds, instrument and
analytics, each a run that reads the map or the ledger and the earlier runs'
records, finishes with its report and a ledger that parses, commits the
ledger and its record, and is said to be due, never run unasked."""

from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from nock.hooks import HookRunner
from nock.project import Project
from nock.reflect import Reflection
from nock.rounds import Subround, named

from .conftest import git, nock

LEDGER: dict[str, Any] = {
    "ledger": "shop",
    "params": {"order_id": {"type": "str"}, "amount": {"type": "decimal"}, "sku": {"type": "str"}},
    "events": [
        {
            "name": "checkout",
            "params": ["order_id", "amount"],
            "validate": "amount > 0",
            "span": {"timeout": "2m"},
            "children": [{"name": "reserved", "params": ["sku"]}],
        },
        {"name": "refund", "params": ["order_id", "amount"]},
    ],
    "rules": [{"on": "checkout.order_id", "expect": ["refund.order_id"], "within": "7d"}],
    "invariants": [],
    "map": {"components": [{"name": "shop", "paths": ["src"], "instrumented": True}]},
}
RECORD = {
    "subround": "logika.instrument",
    "summary": "Refunds are positive.",
    "changes": [
        {
            "kind": "validate",
            "target": "refund",
            "why": "no refund of 0 or less in 30 days of data",
            "expect": "fires only on a refund of 0 or less",
            "tested": "quiet in the noise check over the test suite's capture",
        },
        {
            "kind": "reason",
            "target": "unread refund",
            "why": "the provider refuses a second refund of an order",
            "expect": "no rule while refunds go through the provider",
        },
        {
            "kind": "instrumentation",
            "target": "refund",
            "why": "the validate reads the amount refunded, which wasn't logged",
            "expect": "amount on every refund",
        },
    ],
}


@pytest.fixture
def on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in `logika` on PATH: the round only needs it to be there."""
    directory = tmp_path / "bin"
    directory.mkdir()
    program = directory / "logika"
    program.write_text("#!/bin/sh\nexit 0\n")
    program.chmod(0o755)
    monkeypatch.setenv("PATH", f"{directory}:{os.environ['PATH']}")
    return program


@pytest.fixture
def logika(project: Project, on_path: Path) -> Project:
    """A Logika project: its ledger committed, nock re-initialised for it."""
    write_ledger(project, LEDGER)
    (project.root / "src").mkdir()
    (project.root / "src" / "shop.py").write_text("def checkout(): ...\n")
    assert nock(project.root, "init").returncode == 0
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "Instrument the shop")
    return project


def write_ledger(project: Project, ledger: dict[str, Any]) -> None:
    (project.root / "logika.json").write_text(json.dumps(ledger, indent=2) + "\n")


def start(project: Project, name: str) -> dict[str, Any]:
    """`reflect NAME`: a subround's run started, or a round's plan."""
    result = nock(project.root, "reflect", name, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def submit(project: Project, record: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    return nock(project.root, "reflect", "--submit", json.dumps(record))


def subround(project: Project, name: str) -> Subround:
    (found,) = named(Project.discover(project.root), name)
    return found


def test_a_logika_round_needs_a_ledger_and_the_logika_cli(project: Project, on_path: Path) -> None:
    refused = nock(project.root, "reflect", "logika")
    assert refused.returncode == 42 and "not a Logika project" in refused.stderr
    assert not (project.root / ".claude" / "skills" / "logika").exists()
    assert list(json.loads(nock(project.root, "status", "--json").stdout)["due"]) == ["nock.fit"]
    write_ledger(project, LEDGER)
    on_path.unlink()
    refused = nock(project.root, "reflect", "logika")
    assert refused.returncode == 42 and "`logika` is not on PATH" in refused.stderr


def test_init_installs_the_logika_skills_in_a_logika_project(logika: Project) -> None:
    skills = logika.root / ".claude" / "skills"
    for name, target in (
        ("logika", "logika"),
        ("logika-instrument", "logika.instrument"),
        ("logika-analytics", "logika.analytics"),
    ):
        lead = (skills / name / "SKILL.md").read_text()
        assert lead.startswith(f"---\nname: {name}\n")
        assert lead.endswith(f"Run `.nock/nock reflect {target}` and do what it says.\n")
        assert {path.name for path in (skills / name).iterdir()} == {"SKILL.md"}
    assert not (skills / "logika-rules").exists()
    agents = logika.root / ".claude" / "agents"
    instrument = (agents / "logika-instrument.md").read_text()
    assert instrument.startswith("---\nname: logika-instrument\n")
    assert "tools: Read, Grep, Glob, Edit, Write, Bash\n" in instrument
    assert instrument.endswith(
        "Run `.nock/nock docs reflection.logika.instrument` and do what it says.\n"
    )
    analytics = (agents / "logika-analytics.md").read_text()
    assert analytics.endswith(
        "Run `.nock/nock docs reflection.logika.analytics` and do what it says.\n"
    )


def test_a_skill_of_the_project_s_own_keeps_its_name_from_a_round(logika: Project) -> None:
    own = logika.root / ".claude" / "skills" / "logika-instrument" / "SKILL.md"
    own.write_text("---\nname: logika-instrument\ndescription: Ours.\n---\n\nLog it.\n")
    assert nock(logika.root, "init").returncode == 0
    assert own.read_text().endswith("Log it.\n")
    analytics = (logika.root / ".claude" / "skills" / "logika-analytics" / "SKILL.md").read_text()
    assert analytics.endswith("Run `.nock/nock reflect logika.analytics` and do what it says.\n")


def test_the_round_s_plan_is_an_agent_per_subround_and_starts_none(logika: Project) -> None:
    plan = start(logika, "logika")
    assert plan["round"] == "logika" and "dispatch 2 general-purpose subagents" in plan["do"]
    assert [entry["subround"] for entry in plan["subrounds"]] == [
        "logika.analytics",
        "logika.instrument",
    ]
    assert plan["subrounds"][1]["prompt"].startswith(
        "Run `.nock/nock reflect logika.instrument` and do what it says"
    )
    assert not (logika.local / "reflections").exists()
    started = start(logika, "logika.analytics")
    assert started["write"] == [
        str(logika.local / "reflections" / "logika.analytics" / started["run"] / "report.md")
    ]
    analytics = Path(started["material"]["analytics"]).read_text()
    assert "3 events, 3 params (0 identities, 0 dimensions), 0 funnels" in analytics
    assert "order_id,str,-,-,-,checkout refund" in analytics
    assert "shop,src,,yes,1," in analytics
    assert "Instrument the shop" in analytics
    assert "This is the first run." in analytics


def test_the_analytics_part_reads_what_is_measured(logika: Project) -> None:
    ledger = copy.deepcopy(LEDGER)
    ledger["params"]["user_id"] = {"type": "str", "identity": True, "pii": True}
    ledger["params"]["plan"] = {"type": "str", "dimension": True}
    ledger["events"][0]["params"] += ["user_id", "plan"]
    ledger["events"].append({"name": "signup", "params": ["user_id"]})
    ledger["funnels"] = [
        {"name": "activation", "within": "7d", "steps": ["signup.user_id", "checkout.user_id"]}
    ]
    ledger["milestones"] = [
        {"name": "first_buy", "from": "signup.user_id", "to": "checkout.user_id"}
    ]
    ledger["views"] = [{"name": "Checkout", "panels": [{"event": "checkout", "by": "plan"}]}]
    write_ledger(logika, ledger)
    started = start(logika, "logika.analytics")
    analytics = Path(started["material"]["analytics"]).read_text()
    assert "(1 identities, 1 dimensions), 1 funnels, 1 milestones, 1 views" in analytics
    assert "user_id,str,yes,-,yes,checkout signup" in analytics
    assert "plan,str,-,yes,-,checkout" in analytics
    assert "- funnel `activation` within 7d: signup.user_id → checkout.user_id" in analytics
    assert "- milestone `first_buy`: signup.user_id → checkout.user_id" in analytics
    assert "- view `Checkout`: 1 panels" in analytics


def test_a_logika_run_finishes_and_commits_the_ledger_apart_from_nock_s(
    logika: Project,
) -> None:
    assert submit(logika, RECORD).returncode == 42
    started = start(logika, "logika.instrument")
    refused = submit(logika, RECORD)
    assert refused.returncode == 42 and "write report.md" in refused.stderr
    (logika.root / started["write"][0]).write_text("# The run\n\nRefunds are positive.\n")
    (logika.root / "logika.json").write_text("{ not json")
    broken = submit(logika, RECORD)
    assert broken.returncode == 1 and "logika.json does not parse" in broken.stdout
    ledger = copy.deepcopy(LEDGER)
    ledger["events"][1]["validate"] = "amount > 0"
    write_ledger(logika, ledger)
    finished = submit(logika, RECORD)
    assert finished.returncode == 0, finished.stdout + finished.stderr
    assert git(logika.root, "status", "--porcelain") == ""
    subjects = git(logika.root, "log", "-3", "--format=%s").splitlines()
    assert f"logika.instrument run {started['run']}: Refunds are positive." in subjects
    committed = git(logika.root, "log", "-3", "--name-only", "--format=")
    assert "logika.json" in committed
    # The report stays on this machine; the lead reports the subround in its final message.
    assert "report the subround to the session that ran it" in finished.stdout
    shared = logika.root / ".nock" / "shared" / "rounds" / "logika.instrument" / started["run"]
    assert sorted(path.name for path in shared.iterdir()) == ["record.json"]
    (record,) = subround(logika, "logika.instrument").runs.all()
    assert record["ledger_before"]["validated"] == 1 and record["ledger"]["validated"] == 2
    assert record["changes"][0]["tested"].startswith("quiet in the noise check")
    assert "tested" not in record["changes"][1]
    assert subround(logika, "logika.analytics").runs.all() == []
    assert subround(logika, "nock.fit").runs.all() == []
    assert Reflection(logika).window().since is None

    again = start(logika, "logika.instrument")
    assert again["run"] == f"{started['run']}-2"
    material = Path(again["material"]["instrument"]).read_text()
    assert "- unread refund — left: the provider refuses a second refund of an order" in material


def test_a_logika_round_is_quiet_until_fit_ran_then_due_by_its_measure(logika: Project) -> None:
    def said(session: str) -> str:
        begun = HookRunner(logika, {"session_id": session}).handle("SessionStart")
        return (begun or {}).get("systemMessage", "")

    assert "logika" not in said("s1")
    assert subround(logika, "logika.analytics").due() == ""
    # The fit subround ran: from its run on, each subround is due by its own measure.
    fit = logika.root / ".nock" / "shared" / "rounds" / "nock.fit" / "2026-01-01"
    fit.mkdir(parents=True)
    (fit / "record.json").write_text(
        json.dumps(
            {
                "subround": "nock.fit",
                "summary": "set up",
                "changes": [],
                "run": "2026-01-01",
                "finished": "2026-01-01T00:00:00Z",
                "commit": git(logika.root, "rev-parse", "HEAD"),
            }
        )
    )
    analytics = subround(logika, "logika.analytics")
    assert analytics.measure()["value"] == 3 and analytics.due() == ""
    ledger = copy.deepcopy(LEDGER)
    ledger["events"] += [{"name": f"extra.{number}"} for number in range(2)]
    write_ledger(logika, ledger)
    due = subround(logika, "logika.analytics").due()
    assert due == "5 of 5 events added to logika.json in what Analytics looks at", due
    standing = json.loads(nock(logika.root, "status", "--json").stdout)["due"]
    assert standing["logika.analytics"] == {"why": due, "skill": "/logika-analytics"}
    assert (
        said("s2")
        == "nock: due — logika.analytics; offer the human `/logika-analytics`, never start one unasked."
    )
    assert said("s3") == ""


MAP: dict[str, Any] = {
    "path": ".",
    "mode": "logika",
    "files": 12,
    "events": 9,
    "counts": {"silent": 2, "verdicts": 1, "unread": 2},
    "open": {
        "silent": [{"file": "app/billing/refunds.py", "functions": ["Refunds.refund", "clean"]}],
        "verdicts": ["refund.decided"],
        "unread": ["refund", "refund.sent"],
    },
    "directories": [{"path": "app/", "events": 9, "open": 5}],
}


@pytest.fixture
def mapped(logika: Project, on_path: Path) -> Path:
    """The stand-in `logika` prints `map.json` for `logika map --json`, and
    fails as a broken map would while there is none."""
    found = on_path.parent / "map.json"
    on_path.write_text(
        "#!/bin/sh\n"
        'if [ "$1 $2" = "map --json" ]; then\n'
        f'  [ -f "{found}" ] && exec cat "{found}"\n'
        "  echo 'logika.json: the ledger does not parse' >&2; exit 3\n"
        "fi\n"
    )
    found.write_text(json.dumps(MAP))
    return found


def test_the_instrument_subround_splits_the_code_and_starts_from_the_map(
    logika: Project, mapped: Path
) -> None:
    started = start(logika, "logika.instrument")
    (agent,) = started["agents"]
    assert agent["type"] == "logika-instrument" and agent["one per"] == "each area of the code"
    assert "logika-instrument" in started["brief"] and "logika map" in started["brief"]
    material = Path(started["material"]["instrument"]).read_text()
    assert "logika, 12 files, 9 events; open: 2 silent, 1 verdicts, 2 unread." in material
    assert "- app/: 9 events, 5 open" in material
    for item in (
        "silent app/billing/refunds.py Refunds.refund",
        "silent app/billing/refunds.py clean",
        "verdicts refund.decided",
        "unread refund",
        "unread refund.sent",
    ):
        assert f"- {item}\n" in material
    begun = json.loads((Path(started["material"]["instrument"]).parent / "run.json").read_text())
    assert begun["open"] == {"silent": 2, "verdicts": 1, "unread": 2}


def test_the_instrument_subround_is_due_once_the_map_s_open_items_grew_by_5(
    logika: Project, mapped: Path
) -> None:
    fit = logika.root / ".nock" / "shared" / "rounds" / "nock.fit" / "2026-01-01"
    fit.mkdir(parents=True)
    (fit / "record.json").write_text(
        json.dumps({"subround": "nock.fit", "summary": "set up", "changes": [],
                    "finished": "2026-01-01T00:00:00Z"})
    )  # fmt: skip
    instrument = subround(logika, "logika.instrument")
    assert instrument.measure()["value"] == 3 and instrument.due() == ""
    grown = copy.deepcopy(MAP)
    grown["counts"] = {"silent": 9, "verdicts": 2, "unread": 3}
    mapped.write_text(json.dumps(grown))
    due = subround(logika, "logika.instrument").due()
    assert due == "5 of 5 more open items in logika map in what Instrument looks at", due


def test_an_instrument_run_keeps_its_reasons_for_the_next_one(
    logika: Project, mapped: Path
) -> None:
    started = start(logika, "logika.instrument")
    (logika.root / started["write"][0]).write_text("# The run\n")
    record: dict[str, Any] = {
        "subround": "logika.instrument",
        "summary": "Refunds are logged and ruled.",
        "changes": [
            {
                "kind": "validate",
                "target": "refund",
                "why": "a refund never exceeds its charge",
                "expect": "fires only on a refund above its charge",
            },
            {
                "kind": "reason",
                "target": "unread refund.sent",
                "why": "the provider acknowledges every send",
                "expect": "no rule while sends go through the provider",
            },
        ],
    }
    risk = {**record, "changes": [{**record["changes"][1], "kind": "risk"}]}
    refused = submit(logika, risk)
    assert refused.returncode == 40 and "not risk" in refused.stderr
    later = copy.deepcopy(MAP)
    later["counts"] = {"silent": 0, "verdicts": 1, "unread": 1}
    later["open"] = {"silent": [], "verdicts": ["refund.decided"], "unread": ["refund.sent"]}
    mapped.write_text(json.dumps(later))
    finished = submit(logika, record)
    assert finished.returncode == 0, finished.stdout + finished.stderr
    (kept,) = subround(logika, "logika.instrument").runs.all()
    assert kept["open_before"] == {"silent": 2, "verdicts": 1, "unread": 2}
    assert kept["open"] == {"silent": 0, "verdicts": 1, "unread": 1}
    assert kept["ledger"]["events"] == 3

    again = start(logika, "logika.instrument")
    material = Path(again["material"]["instrument"]).read_text()
    assert "- unread refund.sent — left: the provider acknowledges every send\n" in material
    assert "- verdicts refund.decided\n" in material
    assert "silent" not in material.split("# Open items")[1]


def test_the_instrument_material_says_when_the_map_fails(logika: Project, mapped: Path) -> None:
    mapped.unlink()
    started = start(logika, "logika.instrument")
    material = Path(started["material"]["instrument"]).read_text()
    assert (
        "`logika map --json` exited 3: logika.json: the ledger does not parse: run it yourself."
        in material
    )
    assert "No earlier instrument run left an item with a reason." in material
