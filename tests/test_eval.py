"""`nock eval`: a toy Snakemake scenario — a word list built, a bug planted in
it (a fork on `bug`), a detector per arm and repetition (a checkpoint), a fix
only where the toolbox detected the bug (`when`), and a score joining both
arms — run for real through uv's Snakemake, read with uv's DuckDB, cached in
the scenario's cache/ and restored from it in a fresh clone."""

from __future__ import annotations

import json
import shutil
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nock.evaluation import RUNS
from nock.project import Project
from nock.studio import Studio

from .conftest import git, nock

OUTPUTS = 1 + 2 + 12 + 3 + 6
"""build, plant per bug, detect per arm, bug and rep, fix where found, score per bug and rep."""


def call(directory: Path, *arguments: str) -> Any:
    result = nock(directory, "eval", *arguments, "--json")
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


def query(directory: Path, sql: str) -> list[dict[str, Any]]:
    return call(directory, "query", sql)


def metrics(toy: Path, path: str) -> dict[str, Any]:
    return json.loads((toy / path / "metrics.json").read_text())


def test_a_run_forks_joins_skips_and_reads_a_checkpoint_and_a_second_computes_nothing(
    project: Project, toy: Path
) -> None:
    first = call(project.root, "run")
    assert (first["computed"], first["from_cache"]) == (OUTPUTS, 0), first
    assert first["cost_usd"] == pytest.approx(1.2) and "failed" not in first
    # The fork: both plants from the one build, its state (a git repository) carried in state.tar.
    assert metrics(toy, "results/plant/bug=drop-banana") == {"dropped": 1, "words": 3}
    assert metrics(toy, "results/plant/bug=none") == {"dropped": 0, "words": 3}
    # The checkpoint and `when`: a fix only where the toolbox found the bug.
    assert sorted(path.name for path in (toy / "results/fix/bug=drop-banana").iterdir()) == [
        "rep=1",
        "rep=2",
        "rep=3",
    ]
    assert not (toy / "results/fix/bug=none").exists()
    assert "+banana" in (toy / "results/fix/bug=drop-banana/rep=2/diff.patch").read_text()
    # The join: a score reads both arms.
    assert metrics(toy, "results/score/bug=drop-banana/rep=2") == {"gain": 1, "fixed": True}
    assert metrics(toy, "results/score/bug=none/rep=1") == {"gain": 0, "fixed": False}
    cost = json.loads((toy / "results/detect/arm=toolbox/bug=none/rep=1/cost.json").read_text())
    assert cost["usd"] == 0.1 and cost["seconds"] >= 0

    second = call(project.root, "run")
    assert (second["computed"], second["cost_usd"]) == (0, 0)
    assert call(project.root, "run", "--dry")["to_compute"] == 0


def test_a_fresh_clone_restores_every_output_from_the_committed_cache(
    project: Project, toy: Path, tmp_path: Path
) -> None:
    call(project.root, "run")
    status = git(project.root, "status", "--porcelain", "--untracked-files=all")
    assert "evals/toy/cache/" in status and "results" not in status, status
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "The toy's cache")

    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(project.root), str(clone))
    shutil.copytree(project.root / ".nock/local", clone / ".nock/local")
    dry = call(clone, "run", "--dry")
    restored = [job for job in dry["jobs"] if job["does"] == "from cache"]
    assert len(restored) >= 1 + 2 + 12, dry
    rerun = call(clone, "run")
    assert (rerun["computed"], rerun["from_cache"], rerun["cost_usd"]) == (0, OUTPUTS, 0)
    assert metrics(clone / "evals/toy", "results/score/bug=drop-banana/rep=2")["gain"] == 1

    # Every checked-out file is newer than the clone's results; only content counts.
    plant = clone / "evals/toy/steps/plant.py"
    plant.write_text(plant.read_text() + "\n# tuned\n")
    jobs = call(clone, "run", "--dry")["jobs"]
    plants = [job for job in jobs if job["job"].startswith("plant ")]
    assert plants and all(job["does"].startswith("compute") for job in plants)
    assert "Code has changed" in plants[0]["why"]
    assert not any(job["job"].startswith("build ") for job in jobs)


def test_a_dry_run_says_what_reruns_and_why_and_show_marks_the_stale(
    project: Project, toy: Path
) -> None:
    call(project.root, "run")
    (toy / "parameters/bug/drop-banana.json").write_text('{"drop": "cherry"}\n')
    dry = call(project.root, "run", "--dry")
    plant = next(job for job in dry["jobs"] if job["job"] == "plant bug=drop-banana")
    assert plant["why"] == "Updated input files: parameters/bug/drop-banana.json"
    assert not any(job["job"] == "plant bug=none" for job in dry["jobs"])
    assert dry["estimated_cost_usd"] == pytest.approx(0.6)

    shown = call(project.root, "show", "toy")
    rules = {row["rule"]: row for row in shown["rules"]}
    assert rules["plant"]["stale"] == 1 and rules["detect"]["stale"] == 6
    assert rules["build"]["current"] == 1
    why = {row["path"]: row["why"] for row in shown["stale"]}
    assert why["results/plant/bug=drop-banana"] == plant["why"]
    assert why["results/detect/arm=control/bug=drop-banana/rep=1"] == (
        "Input files updated by another job: results/plant/bug=drop-banana"
    )
    assert call(project.root, "show")[0]["stale"] == 1 + 6 + 3 + 3


def test_a_budget_refuses_a_run_estimated_to_cost_more(project: Project, toy: Path) -> None:
    refused = nock(project.root, "eval", "run", "--budget", "0.5")
    assert refused.returncode == 40 and "the estimate, $1.20 for" in refused.stderr
    assert not (toy / "results").exists(), "nothing ran"
    assert call(project.root, "run", "--budget", "2")["cost_usd"] == pytest.approx(1.2)

    (toy / "steps/detect.py").write_text((toy / "steps/detect.py").read_text() + "\n# tuned\n")
    again = nock(project.root, "eval", "run", "--budget", "0.5")
    assert again.returncode == 40 and "$1.20 for" in again.stderr, "from what detect cost"


def test_a_failed_step_is_a_cached_result_until_pruned(
    project: Project, toy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TOY_FAIL", "control")
    failing = call(project.root, "run")
    assert len(failing["failed"]) == 10, "the first ten named"
    error = json.loads((toy / "results/detect/arm=control/bug=none/rep=1/error.json").read_text())
    assert error["error"] == "RuntimeError: the detector broke"
    assert "Traceback" in error["traceback"]
    # A step one of whose inputs failed fails too, without running.
    skipped = json.loads((toy / "results/score/bug=none/rep=1/error.json").read_text())
    assert skipped == {
        "error": "an input failed: results/detect/arm=control/bug=none/rep=1",
        "skipped": True,
    }
    monkeypatch.delenv("TOY_FAIL")
    assert call(project.root, "run")["computed"] == 0, "a failure is a result: kept"
    shown = call(project.root, "show", "toy")
    assert len(shown["failed"]) == 12
    assert "RuntimeError: the detector broke" in {row["error"] for row in shown["failed"]}

    dry = call(project.root, "prune", "--dry")
    assert {row["why"] for row in dry} == {"failed"}
    assert len(dry) == 12
    assert len(call(project.root, "prune", "--dry")) == len(dry), "a dry prune deletes nothing"
    pruned = call(project.root, "prune")
    assert len(pruned) == len(dry)
    assert not (toy / "results/detect/arm=control/bug=none/rep=1").exists()
    again = call(project.root, "run")
    assert again["computed"] == len(dry) and "failed" not in again
    assert "resumed" not in metrics(toy, "results/detect/arm=control/bug=none/rep=1"), "pruned"
    assert metrics(toy, "results/score/bug=drop-banana/rep=1") == {"gain": 0, "fixed": True}
    assert call(project.root, "prune") == "nothing to prune"

    (toy / "steps/score.py").write_text((toy / "steps/score.py").read_text() + "\n# tuned\n")
    call(project.root, "run")
    stale = call(project.root, "prune")
    assert len(stale) == 6 and all(row["why"].startswith("stale") for row in stale), stale


def test_retry_computes_the_failed_again_and_a_step_reads_its_failed_attempt(
    project: Project, toy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TOY_FAIL", "control")
    call(project.root, "run")
    monkeypatch.delenv("TOY_FAIL")
    assert call(project.root, "run", "--retry", "--dry")["retry"] == 12
    assert len(call(project.root, "show", "toy")["failed"]) == 12, "a dry run changes nothing"
    again = call(project.root, "run", "--retry")
    assert (again["retried"], again["computed"]) == (12, 12) and "failed" not in again, again
    assert metrics(toy, "results/detect/arm=control/bug=none/rep=1") == {
        "detected": False,
        "alarms": 0,
        "resumed": True,
    }
    assert "resumed" not in metrics(toy, "results/detect/arm=toolbox/bug=none/rep=1")
    assert "failed" not in call(project.root, "show", "toy")
    assert call(project.root, "run", "--retry")["computed"] == 0, "nothing failed"
    limited = call(project.root, "run", "results/score/bug=none/rep=1", "--limit", "agents=1")
    assert limited["computed"] == 0 and "snakemake" not in limited, limited


def test_a_cache_outside_git_holds_the_outputs_and_takes_outputs_imported_into_it(
    project: Project, toy: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    settings = project.root / ".nock/config.toml"
    settings.write_text(settings.read_text() + f'\n[eval]\ncache = "{outside}"\n')
    first = call(project.root, "run")
    assert first["computed"] == OUTPUTS and "commit" not in first["next"]
    assert first["tokens"] == 1200
    # Every output's entry, beside the dotted log of runs.
    entries = [entry for entry in (outside / "toy").iterdir() if not entry.name.startswith(".")]
    assert len(entries) == OUTPUTS and (outside / "toy" / RUNS).is_file()
    assert [entry.name for entry in (toy / "cache").iterdir()] == [".gitkeep"]
    assert query(
        project.root, "SELECT sum(tokens) AS tokens FROM outputs WHERE rule = 'detect'"
    ) == [{"tokens": 1200}]

    # What another pipeline computed: each output's files, numbers and cost.
    elsewhere = tmp_path / "elsewhere"
    record = []
    for row in query(project.root, "SELECT path FROM outputs ORDER BY path"):
        source = elsewhere / row["path"]
        shutil.copytree(toy / row["path"], source)
        numbers = {
            name: json.loads((source / name).read_text()) for name in ("metrics.json", "cost.json")
        }
        for name in numbers:
            (source / name).unlink()
        item = {"output": row["path"], "source": str(source)}
        record.append(item | {"metrics": numbers["metrics.json"], "cost": numbers["cost.json"]})
    shutil.rmtree(outside)
    shutil.rmtree(toy / "results")
    assert call(project.root, "run", "--dry")["from_cache"] == 0

    # The jobs after a checkpoint are known once it is restored: import in two rounds.
    early = [
        item for item in record if not item["output"].startswith(("results/fix/", "results/score/"))
    ]
    detects = [item["output"] for item in early if item["output"].startswith("results/detect/")]
    imported = call(project.root, "import", json.dumps({"outputs": early, "targets": detects}))
    assert (imported["imported"], imported["present"]) == (len(early), 0)
    restored = call(project.root, "run", *detects)
    assert (restored["computed"], restored["from_cache"]) == (0, len(early))
    late = [item for item in record if item not in early]
    failed = next(item for item in late if item["output"] == "results/score/bug=none/rep=1")
    failed["error"] = "it broke elsewhere"
    again = call(project.root, "import", json.dumps({"outputs": record}))
    assert (again["imported"], again["present"], again["failed"]) == (len(late), len(early), 1)
    rerun = call(project.root, "run")
    assert (rerun["computed"], rerun["cost_usd"]) == (0, 0), rerun
    assert metrics(toy, "results/score/bug=drop-banana/rep=2") == {"gain": 1, "fixed": True}
    assert (toy / "results/plant/bug=drop-banana/state.tar").is_file()
    shown = call(project.root, "show", "toy")
    assert shown["failed"] == [
        {"path": "results/score/bug=none/rep=1", "error": "it broke elsewhere"}
    ]
    assert (elsewhere / "results/build/corpus=fruit/state.tar").is_file(), "sources stay"

    unknown = nock(
        project.root, "eval", "import", json.dumps({"outputs": [{"output": "results/nope/x=1"}]})
    )
    assert unknown.returncode == 40 and "no cached job" in unknown.stderr


SHAPES = """\
rule all:
    input:
        "results/example/tree=plain",
        "results/example/tree=instrumented/setup=logika",
        "results/example/tree=fixed/setup=none/tree=again",


rule example:
    output:
        directory("results/example/{where}"),
    wildcard_constraints:
        where=".+",
    params:
        keyed=lambda wildcards: dict(wildcards),
    cache: "omit-software"
    script:
        "steps/example.py"
"""


def test_a_rule_whose_outputs_differ_in_their_parameters_reads_as_one_table(
    project: Project,
) -> None:
    call(project.root, "init", "shapes")
    directory = project.root / "evals/shapes"
    (directory / "Snakefile").write_text(SHAPES)
    (directory / "steps/example.py").write_text(
        "from nock.steps import Step\n\nStep(snakemake).run(lambda step: {'ok': 1})\n"
    )
    assert call(project.root, "run")["computed"] == 3
    # A name repeated in a path keeps its first value.
    assert query(project.root, "SELECT tree, setup, ok FROM example ORDER BY tree") == [
        {"tree": "fixed", "setup": "none", "ok": 1},
        {"tree": "instrumented", "setup": "logika", "ok": 1},
        {"tree": "plain", "setup": None, "ok": 1},
    ]
    assert query(
        project.root, "SELECT parameters['tree'] AS tree FROM outputs WHERE path LIKE '%again'"
    ) == [{"tree": "fixed"}]


def test_query_reads_the_results_with_sql_and_nothing_else(project: Project, toy: Path) -> None:
    call(project.root, "run")
    # Comparing arms is a self-join on the parameters they share.
    gains = query(
        project.root,
        "SELECT t.bug, t.rep, t.detected::INT - c.detected::INT AS gain FROM detect t"
        " JOIN detect c USING (bug, rep) WHERE t.arm = 'toolbox' AND c.arm = 'control'"
        " ORDER BY t.bug, t.rep",
    )
    assert [(row["bug"], row["rep"], row["gain"]) for row in gains] == [
        ("drop-banana", 1, 0),
        ("drop-banana", 2, 1),
        ("drop-banana", 3, 1),
        ("none", 1, 0),
        ("none", 2, 0),
        ("none", 3, 0),
    ]
    spent = query(
        project.root,
        "SELECT rule, count(*) AS outputs, round(sum(cost_usd), 2) AS usd FROM outputs"
        " GROUP BY rule ORDER BY rule",
    )
    assert spent[1] == {"rule": "detect", "outputs": 12, "usd": 1.2}
    detected = query(
        project.root,
        "SELECT parameters['arm'] AS arm, avg(value) AS rate FROM metrics"
        " WHERE metric = 'detected' AND parameters['bug'] = 'drop-banana' GROUP BY 1 ORDER BY 1",
    )
    assert detected == [
        {"arm": "control", "rate": pytest.approx(1 / 3)},
        {"arm": "toolbox", "rate": 1.0},
    ]
    diffs = query(project.root, "SELECT rule, added, removed FROM diffs WHERE rule = 'plant'")
    assert sorted((row["added"], row["removed"]) for row in diffs) == [(0, 0), (0, 1)]

    for sql in ("COPY (SELECT 1) TO 'leak.csv'", "SELECT * FROM read_text('Snakefile')"):
        refused = nock(project.root, "eval", "query", sql)
        assert refused.returncode == 40, refused.stdout
    assert not (toy / "leak.csv").exists()
    wrong = nock(project.root, "eval", "query", "SELECT * FROM absent")
    assert wrong.returncode == 40 and "the tables: outputs, metrics, diffs, build" in wrong.stderr


def test_compare_groups_outputs_by_a_parameter_with_intervals_and_paired_differences(
    project: Project, toy: Path
) -> None:
    call(project.root, "run")
    asked = {"by": "arm", "metric": "detected", "step": "detect"}
    rows = call(project.root, "compare", json.dumps(asked))
    by = {(row["bug"], row["arm"]): row for row in rows}
    control, toolbox = by[("drop-banana", "control")], by[("drop-banana", "toolbox")]
    assert control["n"] == 3 and control["mean"] == pytest.approx(1 / 3, abs=1e-3)
    assert control["low"] == 0 and control["high"] == 1 and control["difference"] is None
    assert toolbox["mean"] == 1 and toolbox["difference"] == pytest.approx(2 / 3, abs=1e-3)
    assert toolbox["paired"] is True and by[("none", "toolbox")]["mean"] == 0

    pooled = call(
        project.root, "compare", json.dumps({**asked, "unit": "bug", "baseline": "toolbox"})
    )
    assert [(row["arm"], row["n"]) for row in pooled] == [("control", 2), ("toolbox", 2)]
    assert pooled[0]["difference"] == pytest.approx(-1 / 3, abs=1e-3)

    narrowed = call(
        project.root,
        "compare",
        json.dumps(
            {**asked, "by": "rep", "metric": "alarms", "where": {"bug": "none"}, "over": []}
        ),
    )
    assert {row["rep"] for row in narrowed} == {"1", "2", "3"}
    unnamed = nock(project.root, "eval", "compare", json.dumps({"by": "arm", "metric": "x"}))
    assert unnamed.returncode == 40 and "the rules with metrics are build, detect" in unnamed.stderr
    missing = nock(project.root, "eval", "compare", json.dumps({**asked, "metric": "nope"}))
    assert missing.returncode == 40 and "their metrics: detected, alarms" in missing.stderr


def test_init_scaffolds_a_scenario_that_runs_and_the_check_holds_its_rules(
    project: Project,
) -> None:
    written = call(project.root, "init", "smoke")
    assert "evals/smoke/Snakefile" in written and "evals/smoke/profile/config.yaml" in written
    directory = project.root / "evals/smoke"
    assert "results/" in (directory / ".gitignore").read_text()
    assert nock(project.root, "check", "nock-eval").returncode == 0
    assert call(project.root, "run")["computed"] == 3
    assert query(project.root, "SELECT rep FROM example ORDER BY rep") == [
        {"rep": 1},
        {"rep": 2},
        {"rep": 3},
    ]
    assert nock(project.root, "eval", "init", "smoke").returncode == 40

    snakefile = directory / "Snakefile"
    original = snakefile.read_text()
    unkeyed = original.replace(
        "        keyed=lambda wildcards: dict(wildcards),\n", "        rate=1,\n"
    )
    snakefile.write_text(unkeyed)
    found = nock(project.root, "check", "nock-eval")
    assert found.returncode == 1 and "keeps no wildcards in its params" in found.stdout
    shutil.rmtree(directory / "results")
    assert nock(project.root, "eval", "run", "results/example/rep=1").returncode == 0
    shared = nock(project.root, "eval", "run", "--dry")
    assert "would all be restored from one cache entry" in shared.stdout, shared.stdout
    snakefile.write_text(original.replace('    cache: "omit-software"\n', ""))
    assert "is not cached" in nock(project.root, "check", "nock-eval").stdout
    snakefile.write_text(original + "\nrule broken\n")
    assert "snakemake --list-rules failed" in nock(project.root, "check", "nock-eval").stdout


def test_a_step_dispatches_an_agent_as_nock_does_with_the_allowlist_it_gives(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_ARGUMENTS", str(project.root / "arguments.json"))
    assert nock(project.root, "eval", "init", "agent").returncode == 0
    directory = project.root / "evals" / "agent"
    (directory / "steps/example.py").write_text(
        "from nock.steps import Step\n\n\n"
        "def run(step):\n"
        "    said = step.agent('Answer: why?', allowed=['Write'])\n"
        "    return {'said': said, 'wrote': (step.directory / 'answer.txt').read_text()}\n\n\n"
        "Step(snakemake).run(run)\n"
    )
    result = nock(project.root, "eval", "run", "results/example/rep=1", "--json")
    assert result.returncode == 0, result.stderr
    assert metrics(directory, "results/example/rep=1") == {
        "said": "answered",
        "wrote": "Answer: why?",
    }
    assert {"role": "evaluated"} in project.store.rows("SELECT role FROM sessions")
    arguments = json.loads(Path(project.root / "arguments.json").read_text())
    assert arguments[arguments.index("--permission-mode") + 1] == "dontAsk"
    assert arguments[arguments.index("--tools") + 1] == "Read,Grep,Glob,Bash"
    assert "Write" in arguments[arguments.index("--allowedTools") :]


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
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise AssertionError(error.read().decode()) from error


def test_the_studio_explores_the_graph_and_weighs_a_run_without_running_it(
    project: Project, toy: Path, page: str
) -> None:
    call(project.root, "run")
    explored: dict[str, Any] = {}
    # The studio reads the workflow in the background: the page polls until it has.
    for _ in range(1200):
        explored = post(f"{page}evals/toy/explore", {})
        rules = [item["rule"] for item in explored.get("columns", [])]
        if "fix" in rules and explored["counts"]["done"] == OUTPUTS:
            break
        threading.Event().wait(0.1)
    assert [item["rule"] for item in explored["columns"]] == [
        "build",
        "plant",
        "detect",
        "fix",
        "score",
    ]
    with urllib.request.urlopen(f"{page}evals") as response:
        [summary] = json.loads(response.read())["scenarios"]
    assert summary["steps"] == OUTPUTS and summary["counts"]["done"] == OUTPUTS, summary
    leaf = "results/detect/arm=toolbox/bug=none/rep=3"
    run = post(f"{page}evals/toy/run", {"output": leaf})
    assert run["state"] == "done" and "metrics.json" in [item["name"] for item in run["files"]]
    text = post(f"{page}evals/toy/file", {"output": leaf, "name": "metrics.json"})
    assert json.loads(text["text"]) == {"detected": False, "alarms": 1}

    detect = toy / "steps/detect.py"
    detect.write_text(detect.read_text() + "\n# a draft\n")
    weighed = post(f"{page}evals/toy/dry", {"budget": 0.5})
    assert weighed["summary"]["to_compute"] >= 12 and "passes the budget" in weighed["refused"]
    entries = [entry for entry in (toy / "cache").iterdir() if not entry.name.startswith(".")]
    assert len(entries) == OUTPUTS, "a dry run computes nothing"

    asked = {"by": "arm", "metric": "detected", "step": "detect"}
    detect.write_text(detect.read_text().replace("\n# a draft\n", ""))
    compared = post(f"{page}evals/toy/compare", asked)
    assert {row["arm"] for row in compared} == {"control", "toolbox"}
