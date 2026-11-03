"""The logika topic: in a Logika project — a `logika.json` ledger, the `logika`
CLI on PATH (here a stand-in script) — a round that reads the ledger and the
decisions earlier rounds left, finishes with its report and a ledger that
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
from nock.logika import LogikaRound
from nock.project import Project
from nock.reflect import Reflection, Rounds

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
    "summary": "Refunds are positive.",
    "changes": [
        {
            "kind": "validate",
            "target": "refund",
            "why": "no refund of 0 or less in 30 days of data",
            "expect": "fires only on a refund of 0 or less",
            "tested": "silent on the test suite's capture; fired on a replay setting -1",
        }
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


def start(project: Project) -> dict[str, Any]:
    result = nock(project.root, "reflect", "logika", "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def finish(project: Project, record: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    return nock(project.root, "reflect", "logika", "finish", json.dumps(record))


def test_a_logika_round_needs_a_ledger_and_the_logika_cli(project: Project, on_path: Path) -> None:
    refused = nock(project.root, "reflect", "logika")
    assert refused.returncode == 42 and "not a Logika project" in refused.stderr
    assert not (project.root / ".claude" / "skills" / "nock-reflect-logika").exists()
    assert json.loads(nock(project.root, "status", "--json").stdout)["rounds"] == {}
    write_ledger(project, LEDGER)
    on_path.unlink()
    refused = nock(project.root, "reflect", "logika")
    assert refused.returncode == 42 and "`logika` is not on PATH" in refused.stderr


def test_init_installs_the_logika_skill_in_a_logika_project(logika: Project) -> None:
    skill = logika.root / ".claude" / "skills" / "nock-reflect-logika"
    lead = (skill / "SKILL.md").read_text()
    assert lead.startswith("---\nname: nock-reflect-logika\n")
    assert "`.nock/nock reflect logika` prints" in lead
    assert "## 4. Prove each rule both ways" in (skill / "rules.md").read_text()


def test_the_material_says_what_the_ledger_holds_and_what_was_decided(logika: Project) -> None:
    asked = nock(
        logika.root,
        "decide",
        json.dumps(
            {
                "title": "Refunds never exceed the charge",
                "status": "done",
                "summary": "A rule would hold every refund to its charge.",
                "tags": ["logika", "important"],
            }
        ),
    )
    assert asked.returncode == 0, asked.stderr
    nock(logika.root, "decisions", "edit", '{"number": 1, "review": "rejected", "note": "110%"}')
    started = start(logika)
    material = Path(started["material"]["rules"]).read_text()
    assert "3 events (1 spans; 1 with `validate`, 0 with paths, 1 with a timeout)" in material
    assert 'checkout,span,order_id amount,"amount > 0",-,2m,on,-' in material
    assert "checkout.reserved,leaf,sku,-,-,-,-,-" in material
    assert "refund,leaf,order_id amount,-,-,-,expected,-" in material
    assert "- rule: checkout.order_id → refund.order_id within 7d" in material
    assert "shop,src,,yes,1," in material
    assert "Instrument the shop" in material
    assert "This is the first logika round." in material
    assert "- [D1] done, rejected: Refunds never exceed the charge — the owner: 110%" in material
    assert started["write"] == [".nock/reflections/logika/" + started["round"] + "/report.md"]
    analytics = Path(started["material"]["analytics"]).read_text()
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
    analytics = Path(start(logika)["material"]["analytics"]).read_text()
    assert "(1 identities, 1 dimensions), 1 funnels, 1 milestones, 1 views" in analytics
    assert "user_id,str,yes,-,yes,checkout signup" in analytics
    assert "plan,str,-,yes,-,checkout" in analytics
    assert "- funnel `activation` within 7d: signup.user_id → checkout.user_id" in analytics
    assert "- milestone `first_buy`: signup.user_id → checkout.user_id" in analytics
    assert "- view `Checkout`: 1 panels" in analytics


def test_a_logika_round_finishes_and_commits_the_ledger_apart_from_nock_s_rounds(
    logika: Project,
) -> None:
    assert finish(logika, RECORD).returncode == 42
    started = start(logika)
    refused = finish(logika, RECORD)
    assert refused.returncode == 42 and "write report.md" in refused.stderr
    (logika.root / started["write"][0]).write_text("# The round\n\nRefunds are positive.\n")
    (logika.root / "logika.json").write_text("{ not json")
    broken = finish(logika, RECORD)
    assert broken.returncode == 1 and "logika.json does not parse" in broken.stdout
    untested = copy.deepcopy(RECORD)
    del untested["changes"][0]["tested"]
    refused = finish(logika, untested)
    assert refused.returncode == 1 and "does not say how it was tested" in refused.stdout
    ledger = copy.deepcopy(LEDGER)
    ledger["events"][1]["validate"] = "amount > 0"
    write_ledger(logika, ledger)
    finished = finish(logika, RECORD)
    assert finished.returncode == 0, finished.stdout + finished.stderr
    assert git(logika.root, "status", "--porcelain") == ""
    assert git(logika.root, "log", "-1", "--format=%s") == (
        f"Logika round {started['round']}: Refunds are positive."
    )
    assert "logika.json" in git(logika.root, "show", "--name-only", "--format=", "HEAD")
    (record,) = LogikaRound(logika).rounds.all()
    assert record["ledger_before"]["validated"] == 1 and record["ledger"]["validated"] == 2
    assert record["changes"][0]["tested"].startswith("silent on")
    assert Rounds(logika).all() == [] and Reflection(logika).window().since is None

    again = start(logika)
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
    assert "`/nock-reflect-logika`" in first and "never start it unasked" in first
    assert "logika" not in said("s2")
    standing = json.loads(nock(logika.root, "status", "--json").stdout)["rounds"]["logika"]
    assert standing["due"].startswith("no logika round has run") and standing["skill"]

    started = start(logika)
    (logika.root / started["write"][0]).write_text("# The round\n")
    assert finish(logika, RECORD).returncode == 0
    assert LogikaRound(logika).due() == ""
    local = logika.root / ".nock" / "local" / "config.toml"
    local.write_text(local.read_text() + "[reflect.logika]\ndays = 0\n")
    assert LogikaRound(Project.discover(logika.root)).due() == ""
    ledger = copy.deepcopy(LEDGER)
    ledger["params"]["reason"] = {"type": "str"}
    write_ledger(logika, ledger)
    # Later than the round's finish, which is to the second.
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2099-01-01T00:00:00Z")
    git(logika.root, "commit", "-qam", "Declare the refund's reason")
    assert (
        LogikaRound(Project.discover(logika.root))
        .due()
        .startswith("a logika round is due (1 commits changed")
    )
