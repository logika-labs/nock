"""The studio's Experiment tab: a scenario as an experiment — its steps forking
by parameter, by repeat and by decision, the results each set of values made
and the runs they belong to, and the measures that compare the variants —
derived from the explorer's description of the jobs and the files they made,
worded by the scenario's `studio.json`.

A job's output is a result (a state of its step); the jobs it was made from
(its main input, `first`) give the tree. A step's node is its rule under its
parent's node, split by the parameter values it adds that are neither pooled
(added up, like a bug in a bank) nor the repeat (`rep`). A decision is code
over a step's metrics, declared in `studio.json`, that picks one of its
branches; a branch with a verdict ends the trajectory well or badly, and each
decision with a good branch is a measure. A run is a trajectory: the results
that end one, grouped by their values but the repeat's, with everything they
were made from."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from nock.errors import NotFoundError
from nock.explorer import (
    SPENDING,
    Branch,
    Decision,
    Explorer,
    Facts,
    Graph,
    Job,
    ResultWords,
    Status,
    Wording,
    read_json,
)
from nock.steps import COST, METRICS

RESULT_BYTES = 200_000
"""How much of a result file the page is sent: its start."""
REPEAT = "rep"
"""The parameter that repeats a step, unless `studio.json` names another."""

# What the page calls an output's status.
STATUSES = {
    Status.DONE: "complete",
    Status.STALE: "outdated",
    Status.FAILED: "incomplete",
    Status.RUNNING: "incomplete",
}


def flat_metrics(metrics: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """metrics.json's keys, nested objects joined with dots."""
    found: dict[str, Any] = {}
    for key, value in metrics.items():
        if isinstance(value, dict):
            found.update(flat_metrics(value, f"{prefix}{key}."))
        else:
            found[f"{prefix}{key}"] = value
    return found


def number_of(value: str) -> int | str:
    return int(value) if value.isdigit() else value


def slug(text: str) -> str:
    """Letters, digits and single hyphens: what a page's address may hold."""
    return re.sub(r"-+", "-", re.sub(r"[^A-Za-z0-9]+", "-", text)).strip("-")


def taken(decision: Decision, value: Any) -> Branch | None:
    """The branch a metric's value takes."""
    for branch in decision["branches"]:
        if "equals" in branch:
            if value == branch["equals"]:
                return branch
        elif "above" in branch:
            number = isinstance(value, (int, float)) and not isinstance(value, bool)
            if number and value > branch["above"]:
                return branch
        else:
            return branch
    return None


class Experiment:
    """One scenario's experiment, built from the explorer's description and statuses."""

    def __init__(self, explorer: Explorer, graph: Graph, facts: dict[str, Facts]) -> None:
        self.explorer = explorer
        self.scenario = explorer.scenario
        self.graph = graph
        self.facts = facts
        self.wording = Wording(explorer.scenario)
        self.words: dict[str, Any] = dict(self.wording.words)
        self.parameter_words: dict[str, Any] = self.words.get("parameters", {})
        self.repeat = next(
            (name for name, words in self.parameter_words.items() if words.get("repeat")), REPEAT
        )
        self.pooled = {name for name, words in self.parameter_words.items() if words.get("pooled")}
        self.decisions: list[Decision] = list(self.words.get("decisions", []))
        self.jobs = {
            job.id: job for job in graph.jobs.values() if not job.target and job.id in facts
        }
        # `nock eval run`s, from the cache's log: which made each output, by its entry.
        self.launches = [
            {"id": f"run-{index + 1}", **record}
            for index, record in enumerate(explorer.scenario.runs())
        ]
        self.made_by: dict[tuple[str, str], str] = {
            (path, entry): launch["id"]
            for launch in self.launches
            for path, entry in (launch.get("computed") or {}).items()
            if isinstance(entry, str)
        }

    # --- where an output's files are ---------------------------------------------------

    def directory(self, job: Job) -> Path | None:
        facts = self.facts[job.id]
        if facts.where == "results":
            return self.scenario.directory / job.id
        if facts.where == "cache" and facts.entry:
            return self.scenario.cache / facts.entry
        return None

    def times(self, job: Job) -> tuple[float | None, float | None]:
        """When it started and finished: its cost.json's time, less the seconds it took."""
        directory = self.directory(job)
        if directory is None:
            return None, None
        try:
            finished = (directory / COST).stat().st_mtime
        except OSError:
            return None, None
        seconds = self.facts[job.id].seconds or 0.0
        return finished - seconds, finished

    # --- the tree ------------------------------------------------------------------------

    def parent(self, job: Job) -> Job | None:
        """The step it was made from: of the jobs before it, the one sharing the most of
        its parameter values, the latest to run on a tie (a fix is made from its arm's
        tree more than from the bug it plants)."""
        before = [self.jobs[identifier] for identifier in job.after if identifier in self.jobs]
        if not before:
            return None

        # One with a value the job doesn't have (the clean run a bug's run is set
        # against) is read, not made from.
        def closeness(candidate: Job) -> tuple[bool, int, int]:
            items = candidate.parameters.items()
            shared = sum(1 for name, value in items if job.parameters.get(name) == value)
            consistent = all(job.parameters.get(name) == value for name, value in items)
            return consistent, shared, self.graph.rules.index(candidate.rule)

        return max(before, key=closeness)

    def known(self, job: Job | None) -> dict[str, str]:
        """The parameter values along its trajectory, up to and including it."""
        values: dict[str, str] = {}
        while job is not None:
            values = {**job.parameters, **values}
            job = self.parent(job)
        return values

    def added(self, job: Job) -> dict[str, str]:
        """The parameter values a job adds to its trajectory."""
        known = self.known(self.parent(job))
        return {
            name: value
            for name, value in job.parameters.items()
            if "#" not in name and known.get(name) != value
        }

    def node_of(self, job: Job, nodes: dict[str, dict[str, Any]], memo: dict[str, str]) -> str:
        if job.id in memo:
            return memo[job.id]
        before = self.parent(job)
        parent = self.node_of(before, nodes, memo) if before else None
        added = self.added(job) if before else {}
        values = {
            name: value
            for name, value in added.items()
            if name not in self.pooled and name != self.repeat
        }
        tag = ",".join(f"{name}={value}" for name, value in values.items())
        identifier = f"{parent + '/' if parent else ''}{job.rule}{f'[{tag}]' if tag else ''}"
        node = nodes.get(identifier)
        if node is None:
            pooled = [name for name in added if name in self.pooled]
            via: dict[str, Any] = {"kind": "fork" if values or pooled else "then"}
            if values:
                via["values"] = values
            if pooled:
                via["pooled"] = pooled
            node = {
                "id": identifier,
                "kind": "stage",
                "parent": parent,
                "stage": job.rule,
                "via": via,
                "repeats": set(),
            }
            nodes[identifier] = node
        if self.repeat in added:
            node["repeats"].add(added[self.repeat])
            node["via"]["kind"] = "fork"
        memo[job.id] = identifier
        return identifier

    # --- the model ------------------------------------------------------------------------

    def model(self) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {}
        memo: dict[str, str] = {}
        ordered = sorted(self.jobs.values(), key=lambda job: self.graph.rules.index(job.rule))
        for job in ordered:
            self.node_of(job, nodes, memo)
        for node in nodes.values():
            repeats = node.pop("repeats")
            if repeats:
                node["via"]["repeat"] = len(repeats)
        states = self.states(memo)
        self.decide(nodes, states)
        runs = self.runs(states)
        return {
            "name": self.scenario.name,
            "question": self.words.get("question") or self.scenario.name,
            "parameters": self.parameters(),
            "stages": self.stages(),
            "nodes": list(nodes.values()),
            "runs": runs,
            "launches": [
                {
                    "id": launch["id"],
                    "started": launch.get("started"),
                    "finished": launch.get("finished"),
                    "targets": launch.get("targets") or [],
                    "computed": len(launch.get("computed") or {}),
                    "restored": len(launch.get("restored") or []),
                    "failed": len(launch.get("failed") or []),
                    "usd": launch.get("usd"),
                }
                for launch in self.launches
            ],
            "states": states,
            "measures": self.measures(),
        }

    def states(self, memo: dict[str, str]) -> list[dict[str, Any]]:
        found = []
        for job in self.jobs.values():
            facts = self.facts[job.id]
            status = STATUSES.get(facts.status)
            if status is None:
                continue
            started, finished = self.times(job)
            metrics = flat_metrics(facts.metrics)
            before = self.parent(job)
            state: dict[str, Any] = {
                "id": job.id,
                "node": memo[job.id],
                "parent": before.id if before and before.id in memo else None,
                "rep": number_of(job.parameters[self.repeat])
                if self.repeat in self.added(job)
                else None,
                "params": {
                    name: value
                    for name, value in job.parameters.items()
                    if name != self.repeat and "#" not in name
                },
                "status": status,
                "why": facts.error
                or (
                    "Its code, parameters or inputs changed since it was made."
                    if facts.status is Status.STALE
                    else "Still running."
                    if facts.status is Status.RUNNING
                    else None
                ),
                "started": started,
                "finished": finished,
                "minutes": round(facts.seconds / 60, 2) if facts.seconds is not None else None,
                "usd": self.spent(facts, metrics),
                "score": self.score(job.rule, metrics),
                "metrics": metrics,
                "launch": self.made_by.get((job.id, facts.entry or "")),
            }
            found.append(state)
        return found

    def spent(self, facts: Facts, metrics: dict[str, Any]) -> float | None:
        """Its dollars: cost.json's, or the metrics' `usd` where a step reported them
        there and not through `Step.spend`."""
        reported = metrics.get("usd")
        if isinstance(reported, (int, float)) and not isinstance(reported, bool):
            return max(facts.usd or 0.0, float(reported))
        return facts.usd

    def score(self, rule: str, metrics: dict[str, Any]) -> dict[str, Any] | None:
        declared = self.wording.rule(rule).get("score")
        if not declared:
            return None
        value = metrics.get(declared["metric"])
        if isinstance(value, bool):
            value = int(value)
        if not isinstance(value, (int, float)):
            return None
        score: dict[str, Any] = {"value": value}
        out_of = metrics.get(declared.get("of", "")) if declared.get("of") else None
        if isinstance(out_of, (int, float)):
            score["of"] = out_of
        return score

    def decide(self, nodes: dict[str, dict[str, Any]], states: list[dict[str, Any]]) -> None:
        """A decision node under each node of the rule it reads, and a result per output
        it read: the branch its metric takes."""
        for decision in self.decisions:
            under = [
                node for node in list(nodes.values()) if node.get("stage") == decision["after"]
            ]
            for node in under:
                identifier = f"{node['id']}?{decision['label']}"
                nodes[identifier] = {
                    "id": identifier,
                    "kind": "decision",
                    "parent": node["id"],
                    "via": {"kind": "then"},
                    "label": decision["label"],
                    "condition": decision.get("condition") or decision["label"],
                    "reads": decision["metric"],
                    "branches": [
                        {
                            "id": branch["id"],
                            "label": branch.get("label") or branch["id"],
                            **({"verdict": branch["verdict"]} if "verdict" in branch else {}),
                        }
                        for branch in decision["branches"]
                    ],
                }
                for state in [item for item in states if item["node"] == node["id"]]:
                    value = state["metrics"].get(decision["metric"])
                    branch = taken(decision, value) if value is not None else None
                    if branch is None:
                        continue
                    states.append(
                        {
                            **{
                                key: state[key]
                                for key in ("params", "status", "why", "finished", "launch")
                            },
                            "id": f"{state['id']}?{decision['label']}",
                            "node": identifier,
                            "parent": state["id"],
                            "rep": None,
                            "started": state["finished"],
                            "minutes": 0,
                            "usd": 0,
                            "score": None,
                            "metrics": {},
                            "branch": branch["id"],
                        }
                    )

    def runs(self, states: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """A run per trajectory: the results that end one, grouped by their values but
        the repeat's; each result belongs to the earliest run it is part of."""
        by_id = {state["id"]: state for state in states}
        children: set[str] = {state["parent"] for state in states if state["parent"]}
        ends = [state for state in states if state["id"] not in children]
        grouped: dict[str, dict[str, Any]] = {}
        for end in ends:
            stage = end["node"].rsplit("/", 1)[-1]
            values = "-".join(end["params"][name] for name in end["params"])
            identifier = slug(f"{stage}-{values}") or slug(stage)
            run = grouped.setdefault(
                identifier,
                {"id": identifier, "params": dict(end["params"]), "ends": [], "ts": None},
            )
            run["ends"].append(end["id"])
        for run in grouped.values():
            starts = [by_id[end]["started"] for end in run["ends"] if by_id[end]["started"]]
            run["ts"] = min(starts) if starts else None
        owner: dict[str, str] = {}
        for run in sorted(grouped.values(), key=lambda item: item["ts"] or 0):
            for end in run["ends"]:
                state: dict[str, Any] | None = by_id[end]
                while state is not None and state["id"] not in owner:
                    owner[state["id"]] = run["id"]
                    state = by_id.get(state["parent"]) if state["parent"] else None
        for state in states:
            state["run"] = owner.get(state["id"])
        return [
            {"id": run["id"], "ts": run["ts"], "params": run["params"]}
            for run in sorted(grouped.values(), key=lambda item: item["ts"] or 0)
        ]

    def parameters(self) -> dict[str, Any]:
        seen: dict[str, list[str]] = {}
        for rule in self.graph.rules:
            for job in self.jobs.values():
                if job.rule != rule:
                    continue
                for name, value in job.parameters.items():
                    if name == self.repeat or "#" in name:
                        continue
                    values = seen.setdefault(name, [])
                    if value not in values:
                        values.append(value)
        found = {}
        for name, values in seen.items():
            words = self.parameter_words.get(name, {})
            found[name] = {
                "name": name,
                "label": words.get("label") or name,
                "about": words.get("about", ""),
                "pooled": name in self.pooled,
                "controls": list(words.get("controls", [])),
                "values": [
                    {"id": value, "label": self.wording.value(name, value)}
                    for value in sorted(values, key=natural_key)
                ],
            }
        return found

    def stages(self) -> dict[str, Any]:
        found = {}
        for rule in self.graph.rules:
            words = self.wording.rule(rule)
            score = words.get("score")
            found[rule] = {
                "name": self.wording.title(rule),
                "about": self.wording.means(rule),
                "results": [
                    {"kind": item["kind"], "name": item["name"], "about": item.get("about", "")}
                    for item in self.result_words(rule)
                ],
                "scorer": {
                    "name": score.get("name") or self.wording.metric(score["metric"]),
                    "about": score.get("about", ""),
                    "better": score.get("better", "higher"),
                }
                if score
                else None,
            }
        return found

    def measures(self) -> list[dict[str, Any]]:
        over = next(iter(sorted(self.pooled)), None)
        found: list[dict[str, Any]] = []
        for decision in self.decisions:
            good = next((b for b in decision["branches"] if b.get("verdict") == "good"), None)
            if good is None:
                continue
            found.append(
                {
                    "id": slug(decision["label"]).lower() or decision["label"],
                    "name": decision.get("measure") or decision["label"],
                    "about": decision.get("condition") or "",
                    "decision": decision["label"],
                    "branch": good["id"],
                    "over": over,
                    "better": "higher",
                }
            )
        if over:
            found.append(
                {
                    "id": "cost",
                    "name": f"Cost per {self.parameter_words.get(over, {}).get('label') or over}",
                    "about": f"Everything one {over}'s trajectory cost, from where it forks to the end.",
                    "cost": {},
                    "over": over,
                    "better": "lower",
                }
            )
        return found

    # --- results, read when the page shows them ---------------------------------------------

    def result_words(self, rule: str) -> list[ResultWords]:
        declared = self.wording.rule(rule).get("results")
        if declared is not None:
            return list(declared)
        return [
            {"name": "numbers", "kind": "facts", "about": "What the step's metrics.json says."},
            {
                "name": "the change",
                "kind": "patch",
                "file": "diff.patch",
                "about": "What it changed.",
            },
        ]

    def results(self, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        """Each output's results, as its rule's words say they are held."""
        found: dict[str, dict[str, Any]] = {}
        for identifier in ids:
            job = self.jobs.get(identifier)
            if job is None:
                raise NotFoundError(f"no job makes {identifier}")
            directory = self.directory(job)
            metrics = flat_metrics(read_json(directory / METRICS)) if directory else {}
            score = self.wording.rule(job.rule).get("score", {}).get("metric")
            held: dict[str, Any] = {}
            words = self.result_words(job.rule)
            # Metrics another result shows (checks under a prefix) are not facts as well.
            prefixes = tuple(item["metrics"] for item in words if "metrics" in item)
            shown = {key: value for key, value in metrics.items() if not key.startswith(prefixes)}
            for item in words:
                value = self.result(item, directory, metrics if "metrics" in item else shown, score)
                if value is not None:
                    held[item["kind"] + ":" + item["name"]] = value
            found[identifier] = held
        return found

    def result(
        self, item: ResultWords, directory: Path | None, metrics: dict[str, Any], score: str | None
    ) -> Any:
        if "metrics" in item:
            prefix = item["metrics"]
            checks = [
                {"name": key.removeprefix(prefix), "pass": bool(value)}
                for key, value in metrics.items()
                if key.startswith(prefix)
            ]
            return checks or None
        if "file" not in item:
            if item["kind"] != "facts":
                return None
            shown = {
                key: value
                for key, value in metrics.items()
                if not SPENDING.match(key) and key != score and not isinstance(value, (dict, list))
            }
            return shown or None
        if directory is None:
            return None
        path = directory / item["file"]
        if ".." in Path(item["file"]).parts or not path.is_file():
            return None
        with path.open("rb") as handle:
            text = handle.read(RESULT_BYTES).decode(errors="replace")
        if item["kind"] in ("text", "patch"):
            return text if text.strip() else None
        if item["kind"] == "list":
            try:
                value = json.loads(text)
            except ValueError:
                return [line for line in text.splitlines() if line.strip()]
            return [str(entry) for entry in value] if isinstance(value, list) else None
        try:
            value = json.loads(text)
        except ValueError:
            return [json.loads(line) for line in text.splitlines() if line.strip().startswith("{")]
        if item["kind"] == "checks" and isinstance(value, dict):
            return [{"name": key, "pass": bool(passed)} for key, passed in value.items()]
        return value


def natural_key(value: str) -> tuple[int, float, str]:
    try:
        return (0, float(value), value)
    except ValueError:
        return (1, 0.0, value)
