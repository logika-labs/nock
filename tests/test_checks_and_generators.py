"""Checks — one verdict that says whether the code or the machine is wrong —
and generators, which keep derived files from drifting."""

from __future__ import annotations

import json
from pathlib import Path

from nock.checks import Checks, Outcome
from nock.project import Project

from .conftest import git, nock, write_tool


def configure(project: Project, text: str) -> None:
    path = project.root / ".nock" / "config.toml"
    path.write_text(path.read_text() + "\n" + text)
    git(project.root, "commit", "-qam", "configure")
    project.__dict__.pop("configuration", None)


def test_a_failing_command_is_the_code_and_a_missing_tool_is_the_machine(project: Project) -> None:
    configure(
        project,
        '[checks.lint]\ncommand = "echo bad style; exit 1"\n[checks.types]\ncommand = "definitely-not-a-tool-xyz"\n',
    )
    verdict = Checks(project).run()
    assert verdict.results["lint"].outcome is Outcome.FAILED
    assert verdict.results["types"].outcome is Outcome.BROKEN
    assert verdict.exit_code == 42
    assert Checks(project).run(["lint"]).exit_code == 1
    result = nock(project.root, "check", "lint")
    assert result.returncode == 1 and result.stdout == "lint: bad style\n"


def test_check_prints_nothing_when_everything_passes(project: Project) -> None:
    configure(project, '[checks.ok]\ncommand = "echo fine"\n')
    result = nock(project.root, "check", "--all")
    assert result.returncode == 0 and result.stdout == "" and result.stderr == ""


CHAINS = """
[checks.format]
command = "sleep 2; echo format >> order.log"
chain = "rust"

[checks.lint]
command = "echo lint >> order.log; exit 1"
chain = "rust"

[checks.tests]
command = "echo tests >> order.log"
chain = "rust"

[checks.web]
command = "touch web.started; {meet_types}; echo web >> order.log"

[checks.types]
command = "touch types.started; {meet_web}; echo types >> order.log"
""".format(
    # Each check side by side waits for the other to have started, for a minute at most: run one
    # after the other, the first logs that it ran alone.
    **{
        f"meet_{other}": f"i=0; until [ -e {other}.started ] || [ $i -ge 600 ]; do sleep 0.1; i=$((i+1)); done; "
        f"[ -e {other}.started ] || echo alone >> order.log"
        for other in ("web", "types")
    }
)


def test_chains_run_in_order_and_side_by_side(project: Project) -> None:
    configure(project, CHAINS)
    result = nock(project.root, "check", "rust", "web", "types")
    assert result.returncode == 1 and result.stdout == "lint: exited 1, printing nothing\n"
    order = (project.root / "order.log").read_text().split()
    assert [step for step in order if step in ("format", "lint", "tests")] == [
        "format",
        "lint",
        "tests",
    ]
    assert "alone" not in order, "the chains ran one after another"
    assert sorted(order) == ["format", "lint", "tests", "types", "web"]


def test_a_chain_or_a_check_can_be_named(project: Project) -> None:
    configure(project, CHAINS)
    (project.root / "order.log").unlink(missing_ok=True)
    assert nock(project.root, "check", "tests").returncode == 0
    assert (project.root / "order.log").read_text().split() == ["tests"]
    missing = nock(project.root, "check", "rusty")
    assert missing.returncode == 44 and "chains: rust" in missing.stderr


AFFECTED = """
[checks.api]
command = "echo api >> ran.log; exit 1"
paths = ["api/**"]

[checks.web]
command = "echo web >> ran.log"
paths = ["web/**"]
"""


def test_check_runs_what_the_changes_affect_and_all_runs_every_one(project: Project) -> None:
    with (project.root / ".gitignore").open("a") as ignore:
        ignore.write("ran.log\n")
    git(project.root, "add", ".gitignore")
    configure(project, AFFECTED)
    ran = project.root / "ran.log"

    def checked(*arguments: str) -> tuple[int, list[str]]:
        ran.unlink(missing_ok=True)
        code = nock(project.root, "check", *arguments).returncode
        return code, sorted(ran.read_text().split()) if ran.exists() else []

    assert checked() == (0, []), "a clean main has nothing to check"
    (project.root / "web").mkdir()
    (project.root / "web" / "page.html").write_text("<p>hi</p>\n")
    assert checked() == (0, ["web"])
    assert checked("--all") == (1, ["api", "web"])
    assert checked("api") == (1, ["api"]), "a named check runs whatever changed"
    assert nock(project.root, "check", "--changed").returncode == 40


def test_a_check_returns_problems_and_asks_for_fixtures(project: Project) -> None:
    write_tool(
        project,
        "rules",
        "import nock\n\n"
        "@nock.check\ndef no_todos(root, changed):\n    '''No TODO in changed files.'''\n"
        "    return [nock.Problem('a TODO', path, 1) for path in changed"
        " if path.endswith('.txt') and 'TODO' in (root / path).read_text()]\n",
    )
    assert nock(project.root, "check", "no-todos").returncode == 0
    (project.root / "notes.txt").write_text("TODO later\n")
    result = nock(project.root, "check", "no-todos")
    assert result.returncode == 1 and result.stdout == "no-todos: notes.txt:1: a TODO\n"


def test_examples_are_run_so_a_broken_tool_fails_the_gate(project: Project) -> None:
    write_tool(
        project,
        "db",
        "import nock\n\n"
        "@nock.command(examples=['', '--table users'])\ndef rows(*, table: str = 'all') -> str:\n"
        "    '''Count rows.'''\n"
        "    if table == 'users':\n        raise nock.PreconditionError('the database is gone')\n"
        "    return '3'\n",
    )
    result = nock(project.root, "check", "nock-tools")
    assert result.returncode == 1
    assert "`rows --table users` (.nock/tools/db.py) exited 42" in result.stdout
    assert "the database is gone" in result.stdout
    assert project.store.rows("SELECT tool FROM calls WHERE tool = 'rows'") == []


def release_tool(project: Project, examples: list[str]) -> Path:
    """A `confirm=True` tool whose run leaves a marker file; the marker's path."""
    marker = project.root / "released"
    write_tool(
        project,
        "release",
        "import nock\nfrom pathlib import Path\n\n"
        f"@nock.command(confirm=True, examples={examples!r})\n"
        "def release(version: str = 'next', *, push: bool = False) -> str:\n"
        "    '''Tag and push a release.'''\n"
        f"    Path({str(marker)!r}).write_text(version)\n"
        "    return version\n",
    )
    return marker


def test_a_confirm_tool_s_examples_are_parsed_never_run(project: Project) -> None:
    marker = release_tool(project, ["", "1.2.3 --push"])
    assert nock(project.root, "check", "nock-tools").returncode == 0
    assert not marker.exists()
    assert project.store.rows("SELECT tool FROM calls WHERE tool = 'release'") == []
    assert nock(project.root, "release", "--help").stdout.count(".nock/nock release 1.2.3") == 1


def test_a_confirm_tool_s_example_that_calls_it_wrong_fails_the_check(project: Project) -> None:
    marker = release_tool(project, ["--psh", "a b"])
    result = nock(project.root, "check", "nock-tools")
    assert result.returncode == 1
    assert "`release --psh` (.nock/tools/release.py) is called wrong" in result.stdout
    assert "`release a b` (.nock/tools/release.py) is called wrong" in result.stdout
    assert not marker.exists()


def test_a_hook_needs_its_event_wired(project: Project) -> None:
    write_tool(
        project,
        "hooks",
        "import nock\n\n@nock.hook('tool-failed')\ndef remind(payload):\n    return 'x'\n",
    )
    result = nock(project.root, "check", "nock-wiring")
    assert result.returncode == 1 and "`.nock/nock init` wires it" in result.stdout
    assert nock(project.root, "init").returncode == 0
    assert nock(project.root, "check", "nock-wiring").returncode == 0


def test_a_generator_function_writes_its_file_and_drift_fails_the_check(project: Project) -> None:
    write_tool(
        project,
        "gen",
        "import nock\n\n"
        "@nock.generator('src/version.py')\ndef version(root):\n"
        "    return f'VERSION = {(root / \"VERSION\").read_text().strip()!r}'\n",
    )
    (project.root / "VERSION").write_text("1.2\n")
    assert nock(project.root, "gen").stdout == "src/version.py\n"
    assert (project.root / "src" / "version.py").read_text() == "VERSION = '1.2'\n"
    assert nock(project.root, "check", "nock-generators").returncode == 0
    (project.root / "VERSION").write_text("1.3\n")
    drifted = nock(project.root, "check", "nock-generators")
    assert drifted.returncode == 1 and "src/version.py has drifted" in drifted.stdout


def test_a_generator_s_bytes_are_the_file_exactly(project: Project) -> None:
    write_tool(
        project,
        "gen",
        "import nock\n\n"
        "@nock.generator('golden.bin')\ndef golden(root):\n"
        "    return (root / 'source.txt').read_bytes()[::-1]\n",
    )
    (project.root / "source.txt").write_bytes(b"\x00\xffno newline")
    assert nock(project.root, "gen").stdout == "golden.bin\n"
    assert (project.root / "golden.bin").read_bytes() == b"enilwen on\xff\x00"
    assert nock(project.root, "check", "nock-generators").returncode == 0
    (project.root / "golden.bin").write_bytes(b"enilwen on\xff\x00\n")
    assert nock(project.root, "check", "nock-generators").returncode == 1


def test_two_generators_cannot_own_one_file(project: Project) -> None:
    write_tool(
        project,
        "gen",
        "import nock\n\n"
        "@nock.generator('out.txt')\ndef first():\n    return 'one'\n\n"
        "@nock.generator('out.txt')\ndef second():\n    return 'two'\n",
    )
    result = nock(project.root, "check", "nock-tools")
    assert result.returncode == 1
    assert "`out.txt` is already generated by first (.nock/tools/gen.py)" in result.stdout


def test_a_generator_may_read_what_an_earlier_one_writes(project: Project) -> None:
    write_tool(
        project,
        "gen",
        "import nock\n\n"
        "@nock.generator('schema.json')\ndef schema(root):\n"
        "    return (root / 'source.txt').read_text().upper()\n\n"
        "@nock.generator('types.txt')\ndef types(root):\n"
        "    return 'types of ' + (root / 'schema.json').read_text()\n",
    )
    (project.root / "source.txt").write_text("v1")
    assert nock(project.root, "gen").returncode == 0
    (project.root / "source.txt").write_text("v2")
    assert nock(project.root, "gen").stdout == "schema.json\ntypes.txt\n"
    assert (project.root / "types.txt").read_text() == "types of V2\n"
    assert nock(project.root, "check", "nock-generators").returncode == 0


def test_a_catalog_is_plain_files_rendered_by_gen_and_held_by_the_check(
    project: Project,
) -> None:
    catalog = project.root / ".nock" / "generators" / "errors"
    (catalog / "templates").mkdir(parents=True)
    schema = {"type": "object", "required": ["code"], "properties": {"code": {"type": "integer"}}}
    (catalog / "schema.json").write_text(json.dumps(schema))
    entries = {"not-found": {"code": 404}, "teapot": {"code": 418}}
    (catalog / "entries.json").write_text(json.dumps(entries))
    (catalog / "templates" / "errors.py.template").write_text(
        "!for entry in entries:\n    {{ entry.key.upper().replace('-', '_') }} = {{ entry.code }}\n"
    )
    (catalog / "outputs.toml").write_text(
        '[[output]]\ntemplate = "errors.py.template"\nfile = "src/errors.py"\n'
    )
    assert nock(project.root, "gen").stdout == "src/errors.py\n"
    output = project.root / "src" / "errors.py"
    assert output.read_text() == "NOT_FOUND = 404\nTEAPOT = 418\n"
    listed = json.loads(nock(project.root, "gen", "--list", "--json").stdout)
    assert listed == [{"file": "src/errors.py", "from": "errors", "stale": False}]
    output.write_text("NOT_FOUND = 404\n")
    assert nock(project.root, "check", "nock-generators").returncode == 1
    nock(project.root, "gen")
    (catalog / "entries.json").write_text(json.dumps({**entries, "bad": {"code": "x"}}))
    held = nock(project.root, "check", "nock-generators")
    assert held.returncode == 1 and "errors.bad" in held.stdout + held.stderr
    refused = nock(project.root, "gen")
    assert refused.returncode == 40 and "errors.bad" in refused.stderr
