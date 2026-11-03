"""The studio's evaluation explorer over the toy scenario (`tests/toy`, with its
studio.json): Snakemake's description of the jobs kept and derived again only
when what shapes it changes; the columns, rows and groups; narrowing to what
was made from a selection; what a change reruns; the declared comparison in
counts; and a Snakemake run's lock, log and markers read as running."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from nock.evaluation import Evaluations
from nock.explorer import (
    Exploration,
    Explorer,
    Graph,
    Job,
    Monitor,
    Status,
    View,
    command_targets,
    record_path,
    recorded,
)
from nock.project import Project

from .test_eval import call


def explorer(project: Project) -> Explorer:
    return Explorer(Evaluations(project).scenario("toy"), project.local / "evals")


def explored(found: Explorer, view: View) -> dict[str, Any]:
    graph = found.current(wait=True)
    assert graph is not None, found.problem
    activity, facts = found.read(graph)
    return Exploration(found.scenario, graph, facts, activity, view).page()


def column(page_json: dict[str, Any], rule: str) -> dict[str, Any]:
    return next(item for item in page_json["columns"] if item["rule"] == rule)


def labels(page_json: dict[str, Any], rule: str) -> list[str]:
    return [unit["label"] for unit in column(page_json, rule)["units"]]


def test_the_description_is_kept_and_derived_again_only_when_the_scenario_changes(
    project: Project, toy: Path
) -> None:
    first = explorer(project)
    graph = first.current(wait=True)
    assert graph is not None, first.problem
    rules = {job.rule for job in graph.jobs.values() if not job.target}
    assert {"build", "plant", "detect"} <= rules
    assert graph.rules[:3] == ["build", "plant", "detect"]
    assert graph.targets() == ["all"]
    detect = graph.jobs["results/detect/arm=toolbox/bug=none/rep=2"]
    assert detect.parameters == {"arm": "toolbox", "bug": "none", "rep": "2"}
    assert detect.after == ["results/plant/bug=none"] and detect.checkpoint
    assert detect.entry and detect.script == "steps/detect.py"
    assert "parameters/bug/none.json" in graph.jobs["results/plant/bug=none"].sources
    activity, facts = first.read(graph)
    assert not activity.active and {item.status for item in facts.values()} == {Status.MISSING}

    # Another studio reads the kept description instead of asking Snakemake again.
    again = explorer(project)
    assert again.graph is not None and again.graph.derived_at == graph.derived_at
    assert again.current(wait=True) is again.graph
    assert again.graph.derived_at == graph.derived_at, "nothing changed, nothing derived"

    # A changed Snakefile is another workflow: derived again.
    snakefile = toy / "Snakefile"
    snakefile.write_text(snakefile.read_text() + "\n# a note\n")
    changed = again.current(wait=True)
    assert changed is not None and changed.derived_at > graph.derived_at
    # Words are only the studio's: editing them derives nothing.
    words = toy / "studio.json"
    words.write_text(words.read_text().replace("Detection", "Detector"))
    assert again.current(wait=True).derived_at == changed.derived_at  # type: ignore[union-attr]


def test_the_graph_folds_runs_into_rows_narrows_to_what_follows_and_weighs_a_change(
    project: Project, toy: Path
) -> None:
    call(project.root, "run")
    found = explorer(project)
    whole = explored(found, {})
    assert [item["rule"] for item in whole["columns"]] == [
        "build",
        "plant",
        "detect",
        "fix",
        "score",
    ]
    assert whole["lanes"] == "bug", "the earliest parameter that forks the runs"
    assert whole["counts"]["done"] == 24
    assert {"name": "corpus", "label": "corpus", "value": "fruit"} in whole["constant"]
    # A row per planted bug, its value in the scenario's words; the build before the fork is one box.
    assert labels(whole, "detect") == ["drop-banana", "no bug (the clean twin)"]
    assert labels(whole, "build") == ["the one run"]
    detect = column(whole, "detect")
    assert detect["title"] == "Detection" and detect["means"].startswith("A detector")
    banana = detect["units"][0]
    assert banana["count"] == 6 and banana["counts"]["done"] == 6
    assert banana["splits"] == {"name": "arm", "label": "Arm"}
    assert banana["numbers"]["metrics"][0]["text"] == "4/6"
    assert banana["card"]["title"] == "Detection · drop-banana"
    assert {"label": "Arm", "value": "2 values: control, toolbox"} in banana["card"]["parameters"]
    # Each box's wires: plant's rows feed detect's, the build feeds both plants.
    edges = {(item["from"].split("|")[0], item["to"].split("|")[0]) for item in whole["edges"]}
    assert ("build", "plant") in edges and ("plant", "detect") in edges

    # Split: the banana row by arm, then by rep, down to runs.
    split = explored(found, {"expanded": [banana["id"]]})
    assert labels(split, "detect")[:3] == ["drop-banana", "Arm control", "Arm toolbox"]
    control = column(split, "detect")["units"][1]
    deeper = explored(found, {"expanded": [banana["id"], control["id"]]})
    runs = [unit for unit in column(deeper, "detect")["units"] if unit["depth"] == 2]
    assert [unit["count"] for unit in runs] == [1, 1, 1] and runs[0]["run"].endswith("rep=1")

    # Narrow: the clean twin's plant leaves only its detections and scores, and no fix.
    narrowed = explored(found, {"path": [{"rule": "plant", "filter": {"bug": "none"}}]})
    assert column(narrowed, "detect")["count"] == 6 and column(narrowed, "fix")["count"] == 0
    assert column(narrowed, "score")["count"] == 3
    assert column(narrowed, "plant")["count"] == 2, "the selection's own column stays whole"
    assert narrowed["crumbs"][0]["label"] == "Plant · no bug (the clean twin)"
    assert narrowed["crumbs"][0]["count"] == 1
    assert [unit["selected"] for unit in column(narrowed, "plant")["units"]] == [False, True]
    assert column(narrowed, "build")["units"][0]["lineage"]
    # One run, then: a single detection leads to its one score.
    run = "results/detect/arm=toolbox/bug=drop-banana/rep=2"
    one = explored(
        found,
        {
            "path": [
                {"rule": "plant", "filter": {"bug": "drop-banana"}},
                {"rule": "detect", "run": run},
            ]
        },
    )
    assert column(one, "score")["count"] == 1 and column(one, "fix")["count"] == 1
    assert len(one["crumbs"]) == 2

    # What if: the control arm's value reruns its detections and the scores that read them;
    # the plant's script, everything after the build.
    arm = explored(found, {"change": {"kind": "value", "name": "arm", "value": "control"}})
    assert arm["change"]["count"] == 12 and arm["change"]["done"] == 12
    assert [item["count"] for item in arm["change"]["rules"]] == [6, 6]
    assert sum(unit.get("affected", 0) for unit in column(arm, "detect")["units"]) == 6
    assert arm["change"]["usd"] > 0 and "reruns 12 steps" in arm["change"]["words"]
    plant = explored(found, {"change": {"kind": "code", "name": "steps/plant.py"}})
    assert plant["change"]["count"] == 2 + 12 + 3 + 6
    options = whole["changes"]
    assert {"kind": "value", "name": "bug", "value": "none"} in [
        {key: item[key] for key in ("kind", "name", "value")} for item in options["values"]
    ]
    assert "steps/detect.py" in [item["name"] for item in options["code"]]

    # The declared comparison, in counts: the toolbox found the banana every time.
    [analysis] = whole["analyses"]
    assert (
        analysis["name"] == "Does the toolbox find the planted bug?" and not analysis["suggested"]
    )
    rows = {row["value"]: (row["x"], row["y"], row["baseline"]) for row in analysis["rows"]}
    assert rows == {"control": (1, 3, True), "toolbox": (3, 3, False)}
    assert analysis["sentence"] == "Detected: toolbox 3/3, against control 1/3."
    assert analysis["rows"][1]["path"] == [
        {"rule": "detect", "filter": {"bug": "drop-banana", "arm": "toolbox"}}
    ]

    # A run's card: its words, the highlights the scenario declared (one naming nothing it
    # has is left out), and its files, one of which reads back.
    detail = found.detail(run)
    assert detail["title"] == "Detection · drop-banana · toolbox · 2"
    assert detail["state"] == "done"
    assert "Detected the bug: yes, with 1 alarms." in detail["highlights"]
    assert not any("Never said" in line for line in detail["highlights"])
    assert "metrics.json" in [item["name"] for item in detail["files"]]
    text = found.file_text(run, "metrics.json")
    assert json.loads(text["text"])["detected"] is True

    # A changed detector makes its outputs stale, and what was made from them.
    detector = toy / "steps/detect.py"
    detector.write_text(detector.read_text() + "\n# a draft\n")
    stale = explored(explorer(project), {})
    assert column(stale, "detect")["counts"]["stale"] == 12
    assert column(stale, "plant")["counts"]["done"] == 2
    again = explorer(project)
    again.current(wait=True)
    assert "code, or a file it reads" in again.detail(run)["status"]
    assert (
        "earlier step that is stale"
        in again.detail("results/score/bug=drop-banana/rep=2")["status"]
    )


def test_a_run_going_on_is_read_from_snakemake_s_lock_log_and_markers(tmp_path: Path) -> None:
    state = tmp_path / ".snakemake"
    (state / "locks").mkdir(parents=True)
    (state / "log").mkdir()
    started = "results/detect/arm=control/bug=none/rep=1"
    finished = "results/plant/bug=none"
    log = state / "log" / "2026-11-03T120000.000000.snakemake.log"
    log.write_text(
        "SNAKEMAKE\n=========\n  Date: 2026-11-03 12:00:00\n"
        "  Command: /x/bin/snakemake --profile profile skills --resources stacks=6\n"
        "Building DAG of jobs...\n"
        "[Tue Nov  3 12:00:01 2026]\nlocalrule plant:\n"
        f"    output: {finished}\n    jobid: 4\n"
        "[Tue Nov  3 12:00:02 2026]\nFinished jobid: 4 (Rule: plant)\n1 of 3 steps (33%) done\n"
        "[Tue Nov  3 12:00:03 2026]\nrule detect:\n"
        f"    input: {finished}\n    output: {started}\n    jobid: 7\n"
    )
    monitor = Monitor(tmp_path)
    idle = monitor.read()
    assert not idle.active and idle.running == {}, "no lock, no run"
    (state / "locks" / "0.input.lock").write_text("")
    record = record_path(state / "incomplete", started)
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("")
    going = monitor.read()
    assert going.active and going.targets == ["skills"]
    assert (going.done, going.total) == (1, 3)
    assert going.running == {started: "Tue Nov  3 12:00:03 2026"}
    assert going.incomplete == {started}
    # The log is read on from where it stopped.
    with log.open("a") as handle:
        handle.write("Error in rule detect:\n    jobid: 7\n    output: " + started + "\n")
    assert monitor.read().running == {} and started in monitor.read().failed
    # A long output's record is cut into parts, as Snakemake cuts it.
    long = "results/" + "/".join(f"parameter{index}=value{index}" for index in range(30))
    path = record_path(state / "metadata", long)
    assert len(path.relative_to(state / "metadata").parts) > 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
    assert recorded(state / "metadata") == [long]
    assert command_targets("python /x/snakemake --profile profile -n a b --cores 4 c") == [
        "a",
        "b",
        "c",
    ]


def test_rows_are_the_earliest_fork_and_a_parameter_a_rule_lacks_does_not_fork(
    tmp_path: Path,
) -> None:
    rows = [
        {"rule": "plain", "output": "results/plain/target=t", "after": []},
        *[
            {
                "rule": "instrumented",
                "output": f"results/instrumented/target=t/setup={setup}"
                + ("/planner=p" if setup == "logika" else "")
                + f"/sample={sample}",
                "after": ["results/plain/target=t"],
            }
            for setup in ("none", "logika")
            for sample in (1, 2)
        ],
        {"rule": "report", "output": "results/report/request=r", "after": []},
        {"rule": "all", "output": None, "after": ["results/report/request=r"]},
    ]
    graph = Graph.of(rows)
    assert graph.varying(graph.jobs) == ["setup", "planner", "sample"]
    assert graph.rules == ["plain", "report", "instrumented"]
    assert isinstance(graph.jobs["all"], Job) and graph.jobs["all"].target
    assert graph.scope(["all"]) == {"results/report/request=r"}
    kept = Graph.from_json(json.loads(json.dumps(graph.to_json())))
    assert kept.jobs == graph.jobs
    assert os.path.basename(next(iter(kept.jobs))) == "target=t"
