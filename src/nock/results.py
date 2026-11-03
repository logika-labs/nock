"""Reading an evaluation's results with SQL: DuckDB, run through uv, over the
JSON files the steps wrote under `results/` — no index, nothing kept. Each
call loads the tables fresh from the files, then turns off DuckDB's access to
files and settings before the query runs, so a query only reads:

- `outputs`: a row per step output — rule, path, parameters (a map), state
  (current, stale, failed), why it is stale, cost_usd, seconds, tokens, error;
- `metrics`: a row per number in an output's metrics.json (true is 1);
- `diffs`: an output's diff.patch against the state before it: bytes, files,
  lines added and removed;
- a table per rule, named by it: a column per parameter (typed from the path;
  empty where an output lacks it) and per metric, with state, cost_usd,
  seconds, tokens, error and path."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from nock.errors import UsageError
from nock.evaluation import Result, Scenario, parameters_of, uv
from nock.steps import COST, DIFF, ERROR, METRICS

DUCKDB = "duckdb==2.0.0"
COSTS = "{usd: 'DOUBLE', seconds: 'DOUBLE', tokens: 'BIGINT'}"
TABLES = ("outputs", "metrics", "diffs")

# Runs in uv's interpreter, with duckdb; reads the request on stdin, writes JSON on stdout.
SCRIPT = r"""
import json, sys
import duckdb

request = json.load(sys.stdin)
connection = duckdb.connect()
for statement in request["setup"]:
    try:
        connection.execute(statement)
    except duckdb.Error as error:
        print(json.dumps({"setup": str(error).splitlines()[0], "statement": statement}))
        sys.exit(0)
connection.execute("SET enable_external_access = false")
connection.execute("SET lock_configuration = true")
answers = []
for query in request["queries"]:
    try:
        cursor = connection.execute(query)
        columns = [item[0] for item in cursor.description or []]
        answers.append({"rows": [dict(zip(columns, row)) for row in cursor.fetchall()]})
    except duckdb.Error as error:
        answers.append({"error": str(error).splitlines()[0]})
print(json.dumps(answers, default=str))
"""


def literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def files(paths: list[str]) -> str:
    return "[" + ", ".join(literal(path) for path in paths) + "]"


class Results:
    """One scenario's results, as tables a query reads."""

    def __init__(self, scenario: Scenario, states: list[Result] | None = None) -> None:
        self.scenario = scenario
        self.states = states if states is not None else scenario.states()

    def present(self, name: str) -> list[str]:
        """The outputs' files called `name`, relative to the scenario."""
        directory = self.scenario.directory
        return [
            f"{result.path}/{name}"
            for result in self.states
            if (directory / result.path / name).is_file()
        ]

    def rules(self) -> list[str]:
        return sorted({result.rule for result in self.states})

    def table(self, rule: str) -> str:
        return f"rule_{rule}" if rule in TABLES else rule

    def setup(self) -> list[str]:
        """The statements that load the tables from the files."""
        states = ", ".join(
            f"({literal(result.rule)}, {literal(result.path)}, {literal(result.state)}, "
            f"{literal(result.why) if result.why else 'NULL'})"
            for result in self.states
        )
        statements = [
            "CREATE TABLE states (rule VARCHAR, path VARCHAR, state VARCHAR, why VARCHAR)",
            *([f"INSERT INTO states VALUES {states}"] if states else []),
        ]
        costs, errors = self.present(COST), self.present(ERROR)
        statements.append(
            "CREATE TABLE costs AS "
            + (
                f"SELECT parse_dirpath(filename) AS path, usd, seconds, tokens FROM read_json({files(costs)},"
                f" filename = true, union_by_name = true, columns = {COSTS})"
                if costs
                else "SELECT NULL::VARCHAR AS path, NULL::DOUBLE AS usd, NULL::DOUBLE AS seconds,"
                " NULL::BIGINT AS tokens WHERE false"
            )
        )
        statements.append(
            "CREATE TABLE errors AS "
            + (
                f"SELECT parse_dirpath(filename) AS path, error FROM read_json({files(errors)},"
                " filename = true, union_by_name = true, columns = {error: 'VARCHAR', traceback: 'VARCHAR'})"
                if errors
                else "SELECT NULL::VARCHAR AS path, NULL::VARCHAR AS error WHERE false"
            )
        )
        pattern = literal("([^/=]+)=([^/]+)")
        statements.append(
            "CREATE TABLE outputs AS SELECT s.rule, s.path,"
            f" map(regexp_extract_all(s.path, {pattern}, 1), regexp_extract_all(s.path, {pattern}, 2))"
            " AS parameters, s.state, s.why, c.usd AS cost_usd, c.seconds, c.tokens, e.error"
            " FROM states s LEFT JOIN costs c USING (path) LEFT JOIN errors e USING (path)"
        )
        metrics = self.present(METRICS)
        value = "json_extract(j.json, '$.\"' || replace(k.key, '\"', '\\\"') || '\"')"
        statements.append(
            "CREATE TABLE metrics AS "
            + (
                "SELECT o.rule, o.path, o.parameters, o.state, k.key AS metric, CASE"
                f" json_type({value}) WHEN 'BOOLEAN' THEN CASE WHEN {value}::VARCHAR = 'true'"
                f" THEN 1.0 ELSE 0.0 END WHEN 'BIGINT' THEN {value}::DOUBLE WHEN 'UBIGINT'"
                f" THEN {value}::DOUBLE WHEN 'DOUBLE' THEN {value}::DOUBLE END AS value"
                f" FROM read_json_objects({files(metrics)}, filename = true) j"
                " CROSS JOIN unnest(json_keys(j.json)) AS k(key)"
                " JOIN outputs o ON o.path = parse_dirpath(j.filename)"
                if metrics
                else "SELECT NULL::VARCHAR AS rule, NULL::VARCHAR AS path, NULL::MAP(VARCHAR, VARCHAR)"
                " AS parameters, NULL::VARCHAR AS state, NULL::VARCHAR AS metric,"
                " NULL::DOUBLE AS value WHERE false"
            )
        )
        statements.append("DELETE FROM metrics WHERE value IS NULL")
        diffs = self.present(DIFF)
        lines = "string_split(content, chr(10))"
        statements.append(
            "CREATE TABLE diffs AS "
            + (
                "SELECT o.rule, o.path, o.parameters, d.size AS bytes,"
                f" len(list_filter({lines}, lambda line: starts_with(line, 'diff --git '))) AS files,"
                f" len(list_filter({lines}, lambda line: starts_with(line, '+') AND NOT starts_with(line, '+++')))"
                " AS added,"
                f" len(list_filter({lines}, lambda line: starts_with(line, '-') AND NOT starts_with(line, '---')))"
                " AS removed"
                f" FROM read_text({files(diffs)}) d JOIN outputs o ON o.path = parse_dirpath(d.filename)"
                if diffs
                else "SELECT NULL::VARCHAR AS rule, NULL::VARCHAR AS path, NULL::MAP(VARCHAR, VARCHAR)"
                " AS parameters, NULL::BIGINT AS bytes, NULL::BIGINT AS files, NULL::BIGINT AS added,"
                " NULL::BIGINT AS removed WHERE false"
            )
        )
        for rule in self.rules():
            statements.append(self.rule_table(rule))
        return statements

    def rule_table(self, rule: str) -> str:
        """A rule's outputs, a column per parameter (from the path) and per metric."""
        costs = [path for path in self.present(COST) if path.split("/")[1] == rule]
        metrics = [path for path in self.present(METRICS) if path.split("/")[1] == rule]
        # DuckDB reads hive partitions only when every file has the same names,
        # so the outputs are read in groups by their parameters' names, then joined.
        shapes: dict[tuple[str, ...], list[str]] = {}
        for path in costs:
            shapes.setdefault(tuple(sorted(parameters_of(path.rsplit("/", 1)[0]))), []).append(path)
        source = (
            " UNION ALL BY NAME ".join(
                f"SELECT * EXCLUDE (filename, usd, seconds, tokens), parse_dirpath(filename) AS path"
                f" FROM read_json({files(group)}, filename = true, hive_partitioning = true,"
                f" union_by_name = true, columns = {COSTS})"
                for group in shapes.values()
            )
            if costs
            else "SELECT NULL::VARCHAR AS path WHERE false"
        )
        measured = (
            f"LEFT JOIN (SELECT * EXCLUDE (filename), parse_dirpath(filename) AS path FROM"
            f" read_json({files(metrics)}, filename = true, union_by_name = true,"
            " hive_partitioning = false)) m ON m.path = h.path"
            if metrics
            else ""
        )
        return (
            f"CREATE TABLE {identifier(self.table(rule))} AS SELECT h.* EXCLUDE (path),"
            + (" m.* EXCLUDE (path)," if metrics else "")
            + " o.state, o.why, o.cost_usd, o.seconds, o.tokens, o.error, o.path"
            f" FROM ({source}) h {measured} JOIN outputs o ON o.path = h.path"
        )

    def run(self, queries: list[str]) -> list[dict[str, Any]]:
        """Each query's answer: its rows, or its error."""
        result = subprocess.run(
            [uv(), "run", "--no-project", "--quiet", "--with", DUCKDB, "python", "-c", SCRIPT],
            cwd=self.scenario.directory,
            input=json.dumps({"setup": self.setup(), "queries": queries}),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise UsageError(
                "DuckDB could not load the results: " + result.stderr.strip().splitlines()[-1]
                if result.stderr.strip()
                else f"DuckDB exited {result.returncode}"
            )
        answers = json.loads(result.stdout)
        if isinstance(answers, dict):
            raise UsageError(
                f"DuckDB could not load the results: {answers['setup']}",
                {"statement": answers["statement"]},
            )
        return answers

    def rows(self, query: str) -> list[dict[str, Any]]:
        answer = self.run([query])[0]
        if "error" in answer:
            tables = ", ".join([*TABLES, *(self.table(rule) for rule in self.rules())])
            raise UsageError(f"{answer['error']} — the tables: {tables}")
        return answer["rows"]
