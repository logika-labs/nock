"""Comparing an evaluation's outputs (`nock eval compare`): one rule's
current outputs, grouped by one parameter while the others are held fixed,
pooled over the repetitions (or any parameters named), each mean with a
bootstrap confidence interval. DuckDB averages each unit (`nock.results`);
a difference from the baseline is paired — a join on the units both sides
share — when both have the same units."""

from __future__ import annotations

import json
import random
from typing import Any, NotRequired, TypedDict

from nock.errors import UsageError
from nock.evaluation import Evaluations
from nock.project import Project
from nock.results import Results, identifier, literal

RESAMPLES = 2000
SEED = 0
LEVEL = 0.95


class Query(TypedDict):
    by: str
    """The parameter whose values are compared."""
    metric: str
    """A key of the outputs' metrics.json. True counts 1, false 0."""
    scenario: NotRequired[str]
    """The scenario; the only one there is by default."""
    where: NotRequired[dict[str, Any]]
    """Only the leaves with these values."""
    over: NotRequired[list[str]]
    """The parameters pooled into each number; `rep` by default, the rest held fixed."""
    unit: NotRequired[str]
    """Average within each of this parameter's values first, and resample those (the bugs, say)."""
    step: NotRequired[str]
    """The rule whose outputs are compared; the only one with metrics by default."""
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


def natural(value: str) -> tuple[int, float, str]:
    """Numbers in their order, before words in theirs."""
    try:
        return (0, float(value), "")
    except ValueError:
        return (1, 0.0, value)


def value_key(value: Any) -> str:
    """How a value is named in a query: `none`, `3`, `true`."""
    return value if isinstance(value, str) else json.dumps(value)


class Comparison:
    def __init__(self, project: Project) -> None:
        self.project = project

    def compare(self, query: Query) -> list[dict[str, Any]]:
        scenario = Evaluations(self.project).scenario(query.get("scenario"))
        results = Results(scenario)
        measured = results.rows("SELECT DISTINCT rule FROM metrics ORDER BY rule")
        rules = [row["rule"] for row in measured]
        name = query.get("step") or (rules[0] if len(rules) == 1 else None)
        if name is None or name not in results.rules():
            raise UsageError(
                f'name the rule to compare (`"step": …`): the rules with metrics are {", ".join(rules) or "none yet — run the scenario first"}'
                if name is None
                else f"no rule `{name}` has outputs; the rules: {', '.join(results.rules())}"
            )
        reads = sorted(
            {key for result in results.states if result.rule == name for key in result.parameters}
        )
        by = query["by"]
        where = query.get("where", {})
        over = list(query.get("over", ["rep"] if "rep" in reads else []))
        unit = query.get("unit")
        for parameter in [by, *where, *over, *([unit] if unit else [])]:
            if parameter not in reads:
                raise UsageError(
                    f"`{name}`'s outputs have no parameter `{parameter}`; they have: {', '.join(reads)}"
                )
        if by in over or by == unit:
            raise UsageError(f"`{by}` is compared, so it cannot be pooled too")
        if unit and unit not in over:
            over.append(unit)
        fixed = [parameter for parameter in reads if parameter != by and parameter not in over]
        members = [unit] if unit else over
        table = identifier(results.table(name))
        text = {key: f"CAST({identifier(key)} AS VARCHAR)" for key in reads}
        narrowed = "".join(
            f" AND {text[key]} = {literal(value_key(value))}" for key, value in where.items()
        )
        grouped = [*(text[key] for key in fixed), text[by], *(text[key] for key in members)]
        metric = identifier(query["metric"])
        units, failures, columns = results.run(
            [
                f"SELECT {', '.join(grouped)}, avg(CAST({metric} AS DOUBLE)) AS measured"
                f" FROM {table} WHERE state = 'current' AND {metric} IS NOT NULL{narrowed}"
                f" GROUP BY ALL ORDER BY ALL",
                f"SELECT {', '.join([*(text[key] for key in fixed), text[by]])}, count(*) AS failed"
                f" FROM {table} WHERE state = 'failed'{narrowed} GROUP BY ALL",
                f"SELECT column_name FROM (DESCRIBE {table})",
            ]
        )
        known = [row["column_name"] for row in columns.get("rows", [])]
        if "error" in units or not units["rows"]:
            metrics = [
                column
                for column in known
                if column not in reads
                and column not in ("state", "why", "cost_usd", "seconds", "error", "path")
            ]
            raise UsageError(
                f"no current `{name}` output has a number at `{query['metric']}`"
                + (
                    f"; their metrics: {', '.join(metrics)}"
                    if metrics
                    else "; run the scenario first"
                )
            )
        # fixed values → value of `by` → unit → its mean.
        cells: dict[tuple[str, ...], dict[str, dict[tuple[str, ...], float]]] = {}
        for row in units["rows"]:
            values = list(row.values())
            key = tuple(values[: len(fixed)])
            group = values[len(fixed)]
            member = tuple(values[len(fixed) + 1 : -1])
            cells.setdefault(key, {}).setdefault(group, {})[member] = float(row["measured"])
        failed = {
            (tuple(list(row.values())[: len(fixed)]), list(row.values())[len(fixed)]): row["failed"]
            for row in failures.get("rows", [])
        }
        baseline = value_key(query["baseline"]) if "baseline" in query else None
        generator = random.Random(SEED)
        rows = []
        for row, groups in sorted(cells.items()):
            values = sorted(groups, key=natural)
            first = baseline if baseline in groups else values[0]
            base_units = groups[first]
            for value in values:
                numbers = list(groups[value].values())
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
                    self.difference(base_units, groups[value], generator)
                    if value != first
                    else dict.fromkeys(
                        ("difference", "difference_low", "difference_high", "paired")
                    )
                )
                entry["failed"] = failed.get((row, value), 0)
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
