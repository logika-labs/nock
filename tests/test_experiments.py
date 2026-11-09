"""The studio's Experiments tab over the toy scenario (`tests/toy`): the steps as
a tree forking by parameter (the pooled bug, the arm) and by repeat, a declared
decision under the step it reads, the results each set of values made, the runs
they belong to, the measures, and an output's results as its rule's words say."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from nock.evaluation import Evaluations
from nock.experiments import Experiment
from nock.explorer import Explorer
from nock.project import Project
from nock.studio import ExperimentsTab

from .test_eval import call


def experiment(project: Project) -> Experiment:
    found = Explorer(Evaluations(project).scenario("toy"), project.local / "evals")
    graph = found.current(wait=True)
    assert graph is not None, found.problem
    _, facts = found.read(graph)
    return Experiment(found, graph, facts)


def worded(toy: Path) -> None:
    """The toy's studio.json, with what the Experiments tab reads."""
    path = toy / "studio.json"
    words: dict[str, Any] = json.loads(path.read_text())
    words["question"] = "Does the toolbox find the planted bug?"
    words["parameters"]["bug"].update(pooled=True, controls=["none"])
    words["rules"]["detect"]["results"] = [
        {"name": "numbers", "kind": "facts", "about": "What the detector said."}
    ]
    words["rules"]["detect"]["score"] = {"metric": "alarms", "name": "alarms"}
    words["decisions"] = [
        {
            "after": "detect",
            "label": "Detected?",
            "metric": "detected",
            "measure": "Bugs detected",
            "condition": "The detector said the bug is there.",
            "branches": [
                {"id": "yes", "equals": True, "verdict": "good"},
                {"id": "no", "verdict": "bad"},
            ],
        }
    ]
    path.write_text(json.dumps(words))


def test_the_steps_fork_by_parameter_and_repeat_with_a_decision_under_the_step_it_reads(
    project: Project, toy: Path
) -> None:
    worded(toy)
    before = experiment(project).model()
    nodes = {node["id"]: node for node in before["nodes"]}
    assert before["question"] == "Does the toolbox find the planted bug?"
    assert nodes["build"]["parent"] is None
    # The bug is pooled: one line for its values, not a node per bug.
    assert nodes["build/plant"]["via"] == {"kind": "fork", "pooled": ["bug"]}
    # The arm is compared: a node per value, each repeated three times.
    toolbox = nodes["build/plant/detect[arm=toolbox]"]
    assert toolbox["via"] == {"kind": "fork", "values": {"arm": "toolbox"}, "repeat": 3}
    assert "build/plant/detect[arm=control]" in nodes
    decision = nodes["build/plant/detect[arm=toolbox]?Detected?"]
    assert decision["kind"] == "decision" and decision["parent"] == toolbox["id"]
    assert [branch["id"] for branch in decision["branches"]] == ["yes", "no"]
    # Nothing has run: no results, no runs.
    assert before["states"] == [] and before["runs"] == []
    assert before["parameters"]["bug"]["pooled"] and before["parameters"]["bug"]["controls"] == [
        "none"
    ]
    assert [measure["name"] for measure in before["measures"]] == [
        "Bugs detected",
        "Cost per Planted bug",
    ]


def test_results_runs_and_decisions_once_the_scenario_ran(project: Project, toy: Path) -> None:
    worded(toy)
    call(project.root, "run")
    found = experiment(project)
    model = found.model()
    states = {state["id"]: state for state in model["states"]}
    one = states["results/detect/arm=toolbox/bug=drop-banana/rep=2"]
    assert one["status"] == "complete" and one["rep"] == 2
    assert one["params"] == {"arm": "toolbox", "bug": "drop-banana"}
    assert one["parent"] == "results/plant/bug=drop-banana"
    assert one["usd"] == 0.1 and one["score"] == {"value": 1}
    # The decision read each detection: the toolbox found the planted bug, the clean twin has none.
    taken = states["results/detect/arm=toolbox/bug=drop-banana/rep=2?Detected?"]
    assert taken["branch"] == "yes" and taken["parent"] == one["id"]
    assert states["results/detect/arm=toolbox/bug=none/rep=2?Detected?"]["branch"] == "no"
    # Runs end trajectories, their iterations together; every result belongs to one.
    assert model["runs"] and all(re.fullmatch(r"[A-Za-z0-9-]+", run["id"]) for run in model["runs"])
    assert all(state["run"] for state in model["states"])
    assert all("rep" not in run["params"] for run in model["runs"])
    # The run is in the cache's log, and each result it computed names it.
    (launch,) = model["launches"]
    made = [state for state in model["states"] if "branch" not in state]
    assert launch["id"] == "run-1" and launch["computed"] == len(made)
    assert one["launch"] == "run-1" and launch["started"] <= launch["finished"]
    # A run that computes and restores nothing new adds no line.
    call(project.root, "run")
    assert len(Evaluations(project).scenario("toy").runs()) == 1
    # Results are read when the page shows them, as the rule's words say.
    shown = found.results([one["id"]])[one["id"]]
    assert shown == {"facts:numbers": {"detected": True}}, "the score is shown as the score"


def test_the_tab_answers_a_scenario_and_its_results(project: Project, toy: Path) -> None:
    worded(toy)
    call(project.root, "run")
    tab = ExperimentsTab(project)
    assert tab.get("") == {"scenarios": ["toy"]}
    tab.explorer("toy").current(wait=True)
    model = tab.get("toy")
    assert model["name"] == "toy" and model["states"]
    output = "results/plant/bug=drop-banana"
    assert output in tab.post("toy/results", {"outputs": [output]})
