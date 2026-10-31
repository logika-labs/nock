"""Comparing an evaluation's leaves (`nock eval compare`): the current
snapshots of one step, grouped by one parameter while the others are held
fixed, pooled over the repetitions (or any parameters named), each mean with
a bootstrap confidence interval and the runs behind it. A difference from the
baseline is paired when both sides have the same units."""

from __future__ import annotations

import random
from typing import Any, NotRequired, TypedDict

from nock.errors import UsageError
from nock.evaluation import Evaluations, Runs, Snapshots, value_key
from nock.project import Project

RESAMPLES = 2000
SEED = 0
LEVEL = 0.95


class Query(TypedDict):
    by: str
    """The parameter whose values are compared."""
    metric: str
    """A result's key; a dotted path reaches into nested results. True counts 1, false 0."""
    scenario: NotRequired[str]
    """The scenario; the only one there is by default."""
    where: NotRequired[dict[str, Any]]
    """Only the leaves with these values."""
    over: NotRequired[list[str]]
    """The parameters pooled into each number; `rep` by default, the rest held fixed."""
    unit: NotRequired[str]
    """Average within each of this parameter's values first, and resample those (the bugs, say)."""
    step: NotRequired[str]
    """Compare this step's snapshots instead of the last step's."""
    baseline: NotRequired[Any]
    """The value of `by` the others are measured against; its first by default."""


def metric_of(results: dict[str, Any], path: str) -> float | None:
    value: Any = results
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def interval(samples: list[float]) -> tuple[float, float]:
    ordered = sorted(samples)
    low = ordered[int((1 - LEVEL) / 2 * len(ordered))]
    high = ordered[min(len(ordered) - 1, int((1 + LEVEL) / 2 * len(ordered)))]
    return low, high


def bootstrap(values: list[float], generator: random.Random) -> tuple[float, float] | None:
    """The mean's confidence interval, by resampling `values`."""
    if len(values) < 2:
        return None
    return interval([mean(generator.choices(values, k=len(values))) for _ in range(RESAMPLES)])


def bootstrap_difference(
    baseline: list[float], other: list[float], generator: random.Random
) -> tuple[float, float] | None:
    if len(baseline) < 2 or len(other) < 2:
        return None
    return interval(
        [
            mean(generator.choices(other, k=len(other)))
            - mean(generator.choices(baseline, k=len(baseline)))
            for _ in range(RESAMPLES)
        ]
    )


class Comparison:
    def __init__(self, project: Project) -> None:
        self.project = project

    def compare(self, query: Query) -> list[dict[str, Any]]:
        scenario = Evaluations(self.project).scenario(query.get("scenario"))
        steps = scenario.steps
        name = query.get("step") or (steps[-1].name if steps else None)
        index = scenario.step_index(name) if name else None
        if index is None:
            raise UsageError(
                f"no step `{name}`; the steps: {', '.join(step.name for step in steps)}"
            )
        reads = scenario.reads_through(index)
        by = query["by"]
        where = query.get("where", {})
        over = list(query.get("over", ["rep"] if "rep" in reads else []))
        unit = query.get("unit")
        for parameter in [by, *where, *over, *([unit] if unit else [])]:
            if parameter not in reads:
                raise UsageError(
                    f"`{name}`'s snapshots have no parameter `{parameter}`; they have: {', '.join(reads)}"
                )
        if by in over or by == unit:
            raise UsageError(f"`{by}` is compared, so it cannot be pooled too")
        if unit and unit not in over:
            over.append(unit)
        fixed = [parameter for parameter in reads if parameter != by and parameter not in over]
        snapshots = Snapshots(scenario)
        through = Runs(scenario).through()
        # fixed values → value of `by` → unit → the metric's values; and the snapshots behind them.
        cells: dict[tuple[str, ...], dict[str, dict[tuple[str, ...], list[float]]]] = {}
        behind: dict[tuple[tuple[str, ...], str], list[str]] = {}
        failed: dict[tuple[tuple[str, ...], str], int] = {}
        keys: set[str] = set()
        for snapshot in snapshots.all():
            parameters = snapshot.parameters
            if snapshot.step != name or snapshots.staleness(snapshot):
                continue
            if any(
                value_key(parameters.get(key)) != value_key(value) for key, value in where.items()
            ):
                continue
            row = tuple(value_key(parameters[key]) for key in fixed)
            group = value_key(parameters[by])
            if snapshot.failed:
                failed[(row, group)] = failed.get((row, group), 0) + 1
                continue
            results = snapshot.data.get("results") or {}
            keys |= set(results)
            measured = metric_of(results, query["metric"])
            if measured is None:
                continue
            member = (
                (value_key(parameters[unit]),)
                if unit
                else tuple(value_key(parameters[key]) for key in over)
            )
            cells.setdefault(row, {}).setdefault(group, {}).setdefault(member, []).append(measured)
            behind.setdefault((row, group), []).append(snapshot.hash)
        if not cells:
            raise UsageError(
                f"no current `{name}` snapshot has a number at `{query['metric']}`"
                + (
                    f"; their results have: {', '.join(sorted(keys))}"
                    if keys
                    else "; run the scenario first"
                )
            )
        order = list(scenario.parameters[by].values)
        baseline = value_key(query["baseline"]) if "baseline" in query else None
        generator = random.Random(SEED)
        rows = []
        for row, groups in sorted(cells.items()):
            values = sorted(
                groups, key=lambda value: order.index(value) if value in order else len(order)
            )
            first = baseline if baseline in groups else values[0]
            base_units = {member: mean(found) for member, found in groups[first].items()}
            for value in values:
                units = {member: mean(found) for member, found in groups[value].items()}
                numbers = list(units.values())
                spread = bootstrap(numbers, generator)
                entry: dict[str, Any] = {
                    **dict(zip(fixed, row, strict=True)),
                    by: value,
                    "n": len(numbers),
                    "mean": round(mean(numbers), 4),
                    "low": round(spread[0], 4) if spread else None,
                    "high": round(spread[1], 4) if spread else None,
                }
                entry.update(
                    self.difference(base_units, units, generator)
                    if value != first
                    else dict.fromkeys(
                        ("difference", "difference_low", "difference_high", "paired")
                    )
                )
                entry["failed"] = failed.get((row, value), 0)
                entry["runs"] = " ".join(
                    sorted({run for hash in behind[(row, value)] for run in through.get(hash, [])})
                )
                rows.append(entry)
        return rows

    def difference(
        self,
        baseline: dict[tuple[str, ...], float],
        other: dict[tuple[str, ...], float],
        generator: random.Random,
    ) -> dict[str, Any]:
        """The difference of the means from the baseline's, paired on the units both have."""
        shared = sorted(set(baseline) & set(other))
        paired = len(shared) >= 2 and len(shared) == len(baseline) == len(other)
        if paired:
            differences = [other[member] - baseline[member] for member in shared]
            spread = bootstrap(differences, generator)
            difference = mean(differences)
        else:
            spread = bootstrap_difference(list(baseline.values()), list(other.values()), generator)
            difference = mean(list(other.values())) - mean(list(baseline.values()))
        return {
            "difference": round(difference, 4),
            "difference_low": round(spread[0], 4) if spread else None,
            "difference_high": round(spread[1], 4) if spread else None,
            "paired": paired,
        }
