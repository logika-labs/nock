"""`nock eval`: a toy scenario — a word list built, a bug planted in it (a
fork on `bug`), a detector run per arm and repetition — run for real, in
step processes, against snapshots on disk."""

from __future__ import annotations

import json
import shutil
import threading
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nock.project import Project
from nock.studio import Studio

from .conftest import git, nock

TOY = Path(__file__).with_name("toy")
EVERYTHING = {"bug": "*", "arm": "*", "rep": "*"}


@pytest.fixture
def toy(project: Project) -> Path:
    """The toy scenario, committed in the project's evals/."""
    directory = project.root / "evals" / "toy"
    shutil.copytree(TOY, directory)
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "The toy scenario")
    return directory


def call(project: Project, *arguments: str) -> Any:
    result = nock(project.root, "eval", *arguments, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def run(project: Project, assignment: dict[str, Any], *options: str) -> dict[str, Any]:
    summary = call(project, "run", json.dumps(assignment), *options)
    return json.loads((project.root / "evals/toy/runs" / summary["run"] / "run.json").read_text())


def snapshot(toy: Path, record: dict[str, Any], step: str, **values: Any) -> dict[str, Any]:
    """The snapshot a run reached at `step` with these values."""
    node = next(
        node
        for node in record["nodes"]
        if node["step"] == step
        and all(node["parameters"].get(key) == value for key, value in values.items())
    )
    return {
        "hash": node["snapshot"],
        "directory": toy / "snapshots" / node["snapshot"],
        **json.loads((toy / "snapshots" / node["snapshot"] / "snapshot.json").read_text()),
    }


def test_a_run_computes_each_snapshot_once_and_a_second_run_reuses_them(
    project: Project, toy: Path
) -> None:
    first = run(project, EVERYTHING, "--parallel", "3")
    assert len(first["snapshots"]["computed"]) == 15 and "reused" not in first["snapshots"]
    assert first["cost_usd"] == pytest.approx(1.2) and first["finished"]
    assert first["commit"]["sha"] == git(project.root, "rev-parse", "HEAD")
    planted = snapshot(toy, first, "plant", bug="drop-banana")
    # The snapshot before the fork holds the whole state every branch resumes from.
    assert (planted["directory"] / "artefacts/words.txt").read_text() == "apple\ncherry\n"
    assert planted["parameters"] == {"corpus": "fruit", "bug": "drop-banana"}
    assert [entry["step"] for entry in planted["digests"]["steps"]] == ["build", "plant"]
    leaf = snapshot(toy, first, "detect", bug="drop-banana", arm="toolbox", rep=2)
    assert leaf["results"] == {"detected": True, "alarms": 1} and leaf["status"] == "computed"
    assert {entry["path"] for entry in leaf["artefacts"]} == {"report.md", "words.txt"}
    assert (leaf["directory"] / "artefacts/report.md").read_text() == "missing: 1\n"

    second = run(project, EVERYTHING)
    assert len(second["snapshots"]["reused"]) == 15 and "computed" not in second["snapshots"]
    assert second["cost_usd"] == 0

    narrower = run(project, {"bug": "none", "arm": ["toolbox"], "rep": [1, 2]})
    assert len(narrower["snapshots"]["reused"]) == 4


def test_an_assignment_names_every_open_parameter_and_only_real_values(
    project: Project, toy: Path
) -> None:
    for assignment, said in [
        ({"bug": "*", "arm": "*"}, "leaves `rep` open"),
        ({**EVERYTHING, "bugs": "none"}, "no parameter bugs"),
        ({**EVERYTHING, "arm": "magic"}, "`arm` has no value magic"),
        ({**EVERYTHING, "scenario": "other"}, "no scenario `other`"),
    ]:
        result = nock(project.root, "eval", "run", json.dumps(assignment))
        assert result.returncode in (40, 44) and said in result.stderr


def test_dry_prints_the_tree_with_what_is_reused_and_the_estimate_and_writes_nothing(
    project: Project, toy: Path
) -> None:
    run(project, {"bug": "none", "arm": "*", "rep": "*"})
    dry = nock(project.root, "eval", "run", json.dumps(EVERYTHING), "--dry")
    assert dry.returncode == 0, dry.stderr
    lines = dry.stdout.splitlines()
    assert lines[0].startswith("build corpus=fruit  [") and lines[0].endswith("reused")
    assert "  plant bug=drop-banana  [" in lines[1] and "] compute ~" in lines[1]
    assert "    detect arm=control rep=1  [" in lines[2] and "compute ~" in lines[2]
    assert "to_compute: 7" in dry.stdout and "reused: 8" in dry.stdout
    assert "estimated_cost_usd: 0.6" in dry.stdout
    assert len(list((toy / "runs").iterdir())) == 1


def test_a_file_edit_stales_the_snapshots_that_read_it_and_a_run_computes_beside_them(
    project: Project, toy: Path
) -> None:
    first = run(project, EVERYTHING)
    (toy / "parameters/bug/drop-banana.json").write_text('{"drop": "cherry"}\n')
    shown = call(project, "show", "toy")
    assert shown["snapshots"] == {"current": 8, "stale": 7, "failed": 0}
    assert {item["why"] for item in shown["stale"]} == {"changed since: bug=drop-banana"}
    second = run(project, EVERYTHING)
    assert len(second["snapshots"]["computed"]) == 7 and len(second["snapshots"]["reused"]) == 8
    old = snapshot(toy, first, "plant", bug="drop-banana")
    assert old["directory"].is_dir(), "a stale snapshot is kept until pruned"
    assert (
        snapshot(toy, second, "plant", bug="drop-banana")["directory"] / "artefacts/words.txt"
    ).read_text() == "apple\nbanana\n"

    (toy / "steps/detect.py").write_text((toy / "steps/detect.py").read_text() + "\n# tuned\n")
    stale = call(project, "show", "toy")["stale"]
    assert len(stale) == 7 + 12 and "changed since: step `detect`" in {
        item["why"] for item in stale
    }


def test_a_budget_stops_starting_steps_once_spent_and_estimated_would_pass_it(
    project: Project, toy: Path
) -> None:
    record = run(project, {**EVERYTHING, "budget_usd": 0.35}, "--parallel", "1")
    assert record["cost_usd"] == pytest.approx(0.3)
    assert len(record["snapshots"]["computed"]) == 6
    assert len(record["snapshots"]["over budget"]) == 9
    assert record["assignment"]["budget_usd"] == 0.35
    resumed = run(project, EVERYTHING)
    assert len(resumed["snapshots"]["reused"]) == 6 and len(resumed["snapshots"]["computed"]) == 9


def test_a_failed_step_is_a_result_with_its_log_and_prune_deletes_it_and_the_stale(
    project: Project, toy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TOY_FAIL", "control")
    failing = run(project, EVERYTHING)
    assert len(failing["snapshots"]["failed"]) == 6 and len(failing["snapshots"]["computed"]) == 9
    broken = snapshot(toy, failing, "detect", bug="none", arm="control", rep=1)
    assert broken["status"] == "failed" and broken["error"] == "RuntimeError: the detector broke"
    assert "the detector broke" in (broken["directory"] / "log.txt").read_text()
    shown = call(project, "show", broken["hash"][:6])
    assert shown["error"] == broken["error"] and shown["log"].endswith("log.txt")
    monkeypatch.delenv("TOY_FAIL")
    assert len(run(project, EVERYTHING)["snapshots"]["failed"]) == 6, "a failure is a result: kept"

    (toy / "parameters/corpus/fruit.txt").write_text("apple\nbanana\n")
    dry = call(project, "prune", "--dry")
    assert len(dry) == 15 and {row["why"] for row in dry} == {"stale: changed since: corpus=fruit"}
    assert len(call(project, "prune", "--dry")) == 15
    (toy / "parameters/corpus/fruit.txt").write_text("apple\nbanana\ncherry\n")
    pruned = call(project, "prune")
    assert len(pruned) == 6 and {row["why"] for row in pruned} == {"failed"}
    assert not broken["directory"].exists()
    again = run(project, EVERYTHING)
    assert len(again["snapshots"]["computed"]) == 6
    history = call(project, "show", failing["id"])
    assert history["snapshots"] == {"computed": 9, "failed": 6}
    assert len(history["leaves"]) == 12 and history["cost_usd"] == pytest.approx(0.6)


def test_compare_groups_leaves_by_a_parameter_with_intervals_and_the_runs_behind(
    project: Project, toy: Path
) -> None:
    record = run(project, EVERYTHING)
    rows = call(project, "compare", json.dumps({"by": "arm", "metric": "detected"}))
    by = {(row["bug"], row["arm"]): row for row in rows}
    control, toolbox = by[("drop-banana", "control")], by[("drop-banana", "toolbox")]
    assert control["n"] == 3 and control["mean"] == pytest.approx(1 / 3, abs=1e-3)
    assert control["low"] == 0 and control["high"] == 1 and control["difference"] is None
    assert toolbox["mean"] == 1 and toolbox["difference"] == pytest.approx(2 / 3, abs=1e-3)
    assert toolbox["paired"] is True and toolbox["runs"] == record["id"]
    assert by[("none", "toolbox")]["mean"] == 0

    pooled = call(
        project,
        "compare",
        json.dumps({"by": "arm", "metric": "detected", "unit": "bug", "baseline": "toolbox"}),
    )
    assert [(row["arm"], row["n"]) for row in pooled] == [("control", 2), ("toolbox", 2)]
    assert pooled[0]["difference"] == pytest.approx(-1 / 3, abs=1e-3)

    narrowed = call(
        project,
        "compare",
        json.dumps({"by": "rep", "metric": "alarms", "where": {"bug": "none"}, "over": []}),
    )
    assert {row["rep"] for row in narrowed} == {"1", "2", "3"}
    missing = nock(project.root, "eval", "compare", json.dumps({"by": "arm", "metric": "nope"}))
    assert missing.returncode == 40 and "their results have: alarms, detected" in missing.stderr


def test_the_check_holds_the_scenario_its_steps_and_committed_artefacts(
    project: Project, toy: Path
) -> None:
    assert nock(project.root, "check", "nock-eval").returncode == 0
    record = run(project, {"bug": "none", "arm": "toolbox", "rep": 1})
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "Snapshots")
    assert nock(project.root, "check", "nock-eval").returncode == 0

    leaf = snapshot(toy, record, "detect")
    (leaf["directory"] / "artefacts/report.md").unlink()
    found = nock(project.root, "check", "nock-eval")
    assert found.returncode == 1 and "its artefact report.md is missing" in found.stdout
    (toy / ".gitignore").write_text("snapshots/*/artefacts/report.md\n")
    assert nock(project.root, "check", "nock-eval").returncode == 0, (
        "an ignored artefact is not committed"
    )
    (toy / ".gitignore").write_text("")

    planted = snapshot(toy, record, "plant")
    words = planted["directory"] / "artefacts/words.txt"
    words.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:00\nsize 99\n")
    assert nock(project.root, "check", "nock-eval").returncode == 1, "report.md is still missing"
    shown = call(project, "show", planted["hash"])
    assert {
        "path": "words.txt",
        "bytes": 20,
        "here": "in Git LFS, not fetched (git lfs pull)",
    } in shown["artefacts"]
    dry = nock(
        project.root,
        "eval",
        "run",
        json.dumps({"bug": "none", "arm": "control", "rep": 1}),
        "--dry",
    )
    assert (
        "lacks 1 artefact(s) here: words.txt (in Git LFS" in dry.stdout
        and "blocked: 1" in dry.stdout
    )

    scenario = json.loads((toy / "scenario.json").read_text())
    scenario["steps"][1]["reads"] = ["bug", "colour"]
    scenario["steps"].append({"name": "score", "reads": []})
    (toy / "scenario.json").write_text(json.dumps(scenario))
    (toy / "steps/build.py").write_text(
        (toy / "steps/build.py").read_text() + '\n\ndef peek(step):\n    return step.value("arm")\n'
    )
    problems = nock(project.root, "check", "nock-eval").stdout
    assert "step `plant` reads colour, which scenario.json does not declare" in problems
    assert "step `score` has no steps/score.py" in problems
    assert (
        "steps/build.py: line 8 reads `arm`, which neither this step nor one before it reads"
        in problems
    )
    (toy / "scenario.json").write_text('{"steps": [], "parameters": {}, "extra": 1}')
    assert "toy/scenario.json: " in nock(project.root, "check", "nock-eval").stdout


def test_init_scaffolds_a_scenario_the_check_accepts(project: Project) -> None:
    written = call(project, "init", "smoke")
    assert "evals/smoke/scenario.json" in written and "evals/smoke/.gitattributes" in written
    assert "# snapshots/*/artefacts/" in (project.root / "evals/smoke/.gitignore").read_text()
    assert "filter=lfs" in (project.root / "evals/smoke/.gitattributes").read_text()
    assert nock(project.root, "check", "nock-eval").returncode == 0
    assert call(project, "show")[0]["scenario"] == "smoke"
    again = nock(project.root, "eval", "init", "smoke")
    assert again.returncode == 40


def test_a_step_dispatches_an_agent_as_nock_does_with_the_allowlist_it_gives(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_ARGUMENTS", str(project.root / "arguments.json"))
    directory = project.root / "evals" / "agent"
    (directory / "steps").mkdir(parents=True)
    (directory / "scenario.json").write_text(
        json.dumps(
            {
                "steps": [{"name": "ask", "reads": ["question"]}],
                "parameters": {"question": {"values": ["why?"]}},
            }
        )
    )
    (directory / "steps/ask.py").write_text(
        "def run(step):\n"
        "    said = step.agent('Answer: ' + step.value('question'), allowed=['Write'])\n"
        "    return {'said': said, 'wrote': (step.directory / 'answer.txt').read_text()}\n"
    )
    result = nock(project.root, "eval", "run", '{"scenario": "agent"}', "--json")
    assert result.returncode == 0, result.stderr
    made = next((directory / "snapshots").glob("*/snapshot.json"))
    data = json.loads(made.read_text())
    assert data["results"] == {"said": "answered", "wrote": "Answer: why?"}, data
    roles = project.store.rows("SELECT role FROM sessions")
    assert {"role": "evaluated"} in roles
    arguments = json.loads(Path(project.root / "arguments.json").read_text())
    assert arguments[arguments.index("--permission-mode") + 1] == "dontAsk"
    assert arguments[arguments.index("--tools") + 1] == "Read,Grep,Glob,Bash"
    assert "Write" in arguments[arguments.index("--allowedTools") :]

    (directory / "steps/ask.py").write_text(
        "def run(step):\n"
        "    step.agent('Answer: ' + step.value('question'), allowed=[])\n"
        "    return {'refused': step.refused, 'wrote': (step.directory / 'answer.txt').exists()}\n"
    )
    assert nock(project.root, "eval", "run", '{"scenario": "agent"}').returncode == 0
    refused = [
        json.loads(path.read_text())["results"]
        for path in (directory / "snapshots").glob("*/snapshot.json")
        if "refused" in json.loads(path.read_text())["results"]
    ]
    assert refused == [{"refused": ["Write: answer.txt"], "wrote": False}], refused


@pytest.fixture
def page(project: Project) -> Iterator[str]:
    server = Studio(project, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.address
    server.shutdown()
    server.server_close()


def post(address: str, body: dict[str, Any]) -> Any:
    request = urllib.request.Request(
        address,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def test_the_studio_reads_the_files_and_weighs_a_draft_without_writing(
    project: Project, toy: Path, page: str
) -> None:
    record = run(project, EVERYTHING)
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "Snapshots")
    with urllib.request.urlopen(f"{page}evals") as response:
        scenarios = json.loads(response.read())["scenarios"]
    toy_page = scenarios[0]
    assert [step["new"] for step in toy_page["steps"]] == [["corpus"], ["bug"], ["arm", "rep"]]
    assert len(toy_page["snapshots"]) == 15 and toy_page["runs"][0]["id"] == record["id"]
    assert all(item["runs"] == [record["id"]] for item in toy_page["snapshots"])
    assert "def run(step)" in toy_page["steps"][2]["code"]

    code = (toy / "steps/plant.py").read_text() + "\n# a draft\n"
    weighed = post(
        f"{page}evals/toy/dry", {"assignment": EVERYTHING, "drafts": {"steps/plant.py": code}}
    )
    outcomes = {(node["step"], node["outcome"]) for node in weighed["nodes"]}
    assert outcomes == {("build", "reused"), ("plant", "compute"), ("detect", "compute")}
    assert weighed["summary"]["to_compute"] == 14
    assert git(project.root, "status", "--porcelain") == "", "a draft writes nothing"

    compared = post(f"{page}evals/toy/compare", {"by": "arm", "metric": "detected"})
    assert {row["arm"] for row in compared} == {"control", "toolbox"}
