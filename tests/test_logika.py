"""The logika topic: in a Logika project — a `logika.json` ledger, the `logika`
CLI on PATH (here a stand-in script) — a round that reads the ledger and the
the items earlier rounds left in the `logika` topic, finishes with its report and a ledger that
parses, commits both, and is offered gently, never run."""

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
from nock.rounds import Protocol, named

from .conftest import git, nock, own_protocol
from .test_topics import judge
from .test_topics import submit as decide

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
    "protocol": "logika.rules",
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


def start(project: Project, name: str = "logika") -> dict[str, Any]:
    """Start the logika rounds (or the one NAME names): each by its protocol."""
    result = nock(project.root, "reflect", name, "--json")
    assert result.returncode == 0, result.stderr
    started = json.loads(result.stdout)
    return {begun["protocol"]: begun for begun in started.get("rounds", [started])}


def submit(project: Project, record: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    return nock(project.root, "reflect", "--submit", json.dumps(record))


def protocol(project: Project, name: str) -> Protocol:
    (found,) = named(Project.discover(project.root), name)
    return found


def test_a_logika_round_needs_a_ledger_and_the_logika_cli(project: Project, on_path: Path) -> None:
    refused = nock(project.root, "reflect", "logika")
    assert refused.returncode == 42 and "not a Logika project" in refused.stderr
    assert not (project.root / ".claude" / "skills" / "logika").exists()
    assert json.loads(nock(project.root, "status", "--json").stdout)["rounds"] == {}
    write_ledger(project, LEDGER)
    on_path.unlink()
    refused = nock(project.root, "reflect", "logika")
    assert refused.returncode == 42 and "`logika` is not on PATH" in refused.stderr


def test_init_installs_the_logika_skills_in_a_logika_project(logika: Project) -> None:
    skills = logika.root / ".claude" / "skills"
    for name, target in (
        ("logika", "logika"),
        ("logika-rules", "logika.rules"),
        ("logika-analytics", "logika.analytics"),
    ):
        lead = (skills / name / "SKILL.md").read_text()
        assert lead.startswith(f"---\nname: {name}\n")
        assert lead.endswith(f"Run `.nock/nock reflect {target}` and do what it says.\n")
        assert {path.name for path in (skills / name).iterdir()} == {"SKILL.md"}
    assert not (skills / "nock-reflect-logika").exists()
    agents = logika.root / ".claude" / "agents"
    rules = (agents / "logika-rules.md").read_text()
    assert rules.startswith("---\nname: logika-rules\n")
    assert rules.endswith("Run `.nock/nock docs reflection.logika.rules` and do what it says.\n")
    analytics = (agents / "logika-analytics.md").read_text()
    assert analytics.endswith(
        "Run `.nock/nock docs reflection.logika.analytics` and do what it says.\n"
    )
    assert "reflect --submit" in nock(logika.root, "docs", "reflection.logika.lead").stdout


def test_a_skill_of_the_project_s_own_keeps_its_name_from_a_round(logika: Project) -> None:
    own = logika.root / ".claude" / "skills" / "logika" / "SKILL.md"
    own.write_text("---\nname: logika\ndescription: How this project logs.\n---\n\nLog it.\n")
    assert nock(logika.root, "init").returncode == 0
    assert own.read_text().endswith("Log it.\n")
    rules = (logika.root / ".claude" / "skills" / "logika-rules" / "SKILL.md").read_text()
    assert rules.endswith("Run `.nock/nock reflect logika.rules` and do what it says.\n")


def test_the_material_says_what_the_ledger_holds_and_what_was_decided(logika: Project) -> None:
    ref = decide(
        logika.root,
        {
            "title": "Refunds never exceed the charge",
            "decision": {"answer": "A rule would hold every refund to its charge."},
        },
        topic="logika",
    )
    judge(logika.root, ref, "rejected", "110%")
    begun = start(logika)
    assert set(begun) == {"logika.rules", "logika.analytics"}
    started = begun["logika.rules"]
    assert started["agents"][0]["type"] == "logika-rules"
    assert started["agents"][0]["one per"] == "each directory logika map shows open items in"
    material = Path(started["material"]["rules"]).read_text()
    assert "3 events (1 spans; 1 with `validate`, 0 with paths, 1 with a timeout)" in material
    assert "event,kind,params,validate,paths,timeout,rules,anomaly\n" in material
    assert 'checkout,span,order_id amount,"amount > 0",-,2m,on,-\n' in material
    assert "checkout.reserved,leaf,sku,-,-,-,-,-\n" in material
    assert "refund,leaf,order_id amount,-,-,-,expected,-\n" in material
    assert "- rule: checkout.order_id → refund.order_id within 7d" in material
    assert "shop,src,,yes,1," in material
    assert "Instrument the shop" in material
    assert "This is the first logika round." in material
    assert (
        f"- [{ref}] done, rejected: Refunds never exceed the charge — the owner: 110%" in material
    )
    assert started["write"] == [
        ".nock/shared/rounds/logika.rules/" + started["round"] + "/report.md"
    ]
    analytics = Path(begun["logika.analytics"]["material"]["analytics"]).read_text()
    assert "3 events, 3 params (0 identities, 0 dimensions), 0 funnels" in analytics
    assert "order_id,str,-,-,-,checkout refund" in analytics
    assert "Instrument the shop" in analytics and "Refunds never exceed the charge" in analytics


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
    started = start(logika, "logika.analytics")["logika.analytics"]
    analytics = Path(started["material"]["analytics"]).read_text()
    assert "(1 identities, 1 dimensions), 1 funnels, 1 milestones, 1 views" in analytics
    assert "user_id,str,yes,-,yes,checkout signup" in analytics
    assert "plan,str,-,yes,-,checkout" in analytics
    assert "- funnel `activation` within 7d: signup.user_id → checkout.user_id" in analytics
    assert "- milestone `first_buy`: signup.user_id → checkout.user_id" in analytics
    assert "- view `Checkout`: 1 panels" in analytics


def test_a_logika_round_finishes_and_commits_the_ledger_apart_from_nock_s_rounds(
    logika: Project,
) -> None:
    assert submit(logika, RECORD).returncode == 42
    started = start(logika)["logika.rules"]
    refused = submit(logika, RECORD)
    assert refused.returncode == 42 and "write report.md" in refused.stderr
    (logika.root / started["write"][0]).write_text("# The round\n\nRefunds are positive.\n")
    (logika.root / "logika.json").write_text("{ not json")
    broken = submit(logika, RECORD)
    assert broken.returncode == 1 and "logika.json does not parse" in broken.stdout
    ledger = copy.deepcopy(LEDGER)
    ledger["events"][1]["validate"] = "amount > 0"
    write_ledger(logika, ledger)
    finished = submit(logika, RECORD)
    assert finished.returncode == 0, finished.stdout + finished.stderr
    assert git(logika.root, "status", "--porcelain") == ""
    assert git(logika.root, "log", "-1", "--format=%s") == (
        f"logika.rules round {started['round']}: Refunds are positive."
    )
    assert "logika.json" in git(logika.root, "show", "--name-only", "--format=", "HEAD")
    (record,) = protocol(logika, "logika.rules").rounds.all()
    assert record["ledger_before"]["validated"] == 1 and record["ledger"]["validated"] == 2
    assert record["changes"][0]["tested"].startswith("quiet in the noise check")
    assert "tested" not in record["changes"][1]
    assert protocol(logika, "logika.analytics").rounds.all() == []
    assert protocol(logika, "nock.fit").rounds.all() == []
    assert Reflection(logika).window().since is None

    again = start(logika, "logika.rules")["logika.rules"]
    assert again["round"] == f"{started['round']}-2"
    material = Path(again["material"]["rules"]).read_text()
    assert "# The last logika round" in material
    assert "expected fires only on a refund of 0 or less" in material


def test_a_logika_round_is_offered_once_a_week_never_run(
    logika: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    def said(session: str) -> str:
        begun = HookRunner(logika, {"session_id": session}).handle("SessionStart")
        return (begun or {}).get("systemMessage", "")

    first = said("s1")
    assert "no logika round has run, and the ledger declares 3 events" in first
    assert "`/logika`" in first and "never start it unasked" in first
    assert "logika" not in said("s2")
    standing = json.loads(nock(logika.root, "status", "--json").stdout)["rounds"]["logika"]
    assert standing["due"].startswith("no logika round has run") and standing["skill"]

    started = start(logika, "logika.rules")["logika.rules"]
    (logika.root / started["write"][0]).write_text("# The round\n")
    assert submit(logika, RECORD).returncode == 0
    assert protocol(logika, "logika.rules").due() == ""
    own_protocol(logika, "logika.rules", {"days": 0})
    assert protocol(logika, "logika.rules").due() == ""
    ledger = copy.deepcopy(LEDGER)
    ledger["params"]["reason"] = {"type": "str"}
    write_ledger(logika, ledger)
    # Later than the round's finish, which is to the second.
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2099-01-01T00:00:00Z")
    git(logika.root, "commit", "-qam", "Declare the refund's reason")
    assert (
        protocol(logika, "logika.rules")
        .due()
        .startswith("a logika round is due (1 commits changed")
    )


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


def test_the_instrument_round_runs_by_name_only_and_starts_from_the_map(
    logika: Project, mapped: Path
) -> None:
    assert set(start(logika)) == {"logika.rules", "logika.analytics"}
    assert not (logika.root / ".claude" / "skills" / "logika-instrument").exists()
    standing = json.loads(nock(logika.root, "status", "--json").stdout)["rounds"]
    assert "logika.instrument" not in json.dumps(standing)
    started = start(logika, "logika.instrument")["logika.instrument"]
    assert started["agents"] == [] and "logika map <area>" in started["brief"]
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
    begun = json.loads((Path(started["material"]["instrument"]).parent / "round.json").read_text())
    assert begun["open"] == {"silent": 2, "verdicts": 1, "unread": 2}


def test_an_instrument_round_keeps_its_reasons_for_the_next_one(
    logika: Project, mapped: Path
) -> None:
    started = start(logika, "logika.instrument")["logika.instrument"]
    (logika.root / started["write"][0]).write_text("# The round\n")
    record: dict[str, Any] = {
        "protocol": "logika.instrument",
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
    (kept,) = protocol(logika, "logika.instrument").rounds.all()
    assert kept["open_before"] == {"silent": 2, "verdicts": 1, "unread": 2}
    assert kept["open"] == {"silent": 0, "verdicts": 1, "unread": 1}
    assert kept["ledger"]["events"] == 3

    again = start(logika, "logika.instrument")["logika.instrument"]
    material = Path(again["material"]["instrument"]).read_text()
    assert "- unread refund.sent — left: the provider acknowledges every send\n" in material
    assert "- verdicts refund.decided\n" in material
    assert "silent" not in material.split("# Open items")[1]


def test_the_instrument_material_says_when_the_map_fails(logika: Project, mapped: Path) -> None:
    mapped.unlink()
    started = start(logika, "logika.instrument")["logika.instrument"]
    material = Path(started["material"]["instrument"]).read_text()
    assert (
        "`logika map --json` exited 3: logika.json: the ledger does not parse: run it yourself."
        in material
    )
    assert "No earlier instrument round left an item with a reason." in material
