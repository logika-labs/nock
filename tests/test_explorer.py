"""What the Experiment tab is drawn from, over the toy scenario (`tests/toy`):
Snakemake's description of the jobs kept and derived again only when what
shapes it changes, the rules in the order they run, and a Snakemake run's lock,
log and markers read as running."""

from __future__ import annotations

import json
import os
from pathlib import Path

from nock.evaluation import Evaluations
from nock.explorer import Explorer, Graph, Job, Monitor, Status, record_path, recorded
from nock.project import Project


def explorer(project: Project) -> Explorer:
    return Explorer(Evaluations(project).scenario("toy"), project.local / "evals")


def test_the_description_is_kept_and_derived_again_only_when_the_scenario_changes(
    project: Project, toy: Path
) -> None:
    first = explorer(project)
    graph = first.current(wait=True)
    assert graph is not None, first.problem
    rules = {job.rule for job in graph.jobs.values() if not job.target}
    assert {"build", "plant", "detect"} <= rules
    assert graph.rules[:3] == ["build", "plant", "detect"]
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
    assert going.active
    assert going.running == {started: "Tue Nov  3 12:00:03 2026"}
    assert going.incomplete == {started}
    # The log is read on from where it stopped.
    with log.open("a") as handle:
        handle.write("Error in rule detect:\n    jobid: 7\n    output: " + started + "\n")
    assert monitor.read().running == {}, "a job that failed is no longer running"
    # A long output's record is cut into parts, as Snakemake cuts it.
    long = "results/" + "/".join(f"parameter{index}=value{index}" for index in range(30))
    path = record_path(state / "metadata", long)
    assert len(path.relative_to(state / "metadata").parts) > 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
    assert recorded(state / "metadata") == [long]


def test_rules_run_in_order_a_target_has_no_output_and_the_description_reads_back(
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
    assert graph.rules == ["plain", "report", "instrumented"]
    assert isinstance(graph.jobs["all"], Job) and graph.jobs["all"].target
    kept = Graph.from_json(json.loads(json.dumps(graph.to_json())))
    assert kept.jobs == graph.jobs
    assert os.path.basename(next(iter(kept.jobs))) == "target=t"
