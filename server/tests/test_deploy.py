"""The deploy's plan, step by step, and its local half run for real: what the tarball holds."""

import importlib.util
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

SERVER = Path(__file__).resolve().parents[1]


def load() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "deploy", SERVER / "deploy" / "deploy.py"
    )
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


DEPLOY = load()
RELEASE = "20261103T120000Z-0123456789ab"


def test_the_release_is_named_by_its_time_then_its_commit() -> None:
    moment = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    assert DEPLOY.release_id(moment, "0123456789ab") == RELEASE


def test_the_box_is_always_named() -> None:
    assert DEPLOY.destination_problem("ops@box-1") is None
    assert DEPLOY.destination_problem("") and DEPLOY.destination_problem("-oProxyCommand=x")


def test_the_remote_half_copies_unpacks_and_installs_under_opt(tmp_path: Path) -> None:
    steps = DEPLOY.plan("ops@box-1", RELEASE, tmp_path)
    remote = f"/tmp/nock-api-{RELEASE}.tar.gz"
    box = f"/opt/nock-api/releases/{RELEASE}"
    assert [step.command for step in steps[-3:]] == [
        ["scp", "-q", str(tmp_path / f"{RELEASE}.tar.gz"), f"ops@box-1:{remote}"],
        [
            "ssh",
            "ops@box-1",
            "sudo sh -c 'mkdir -p /opt/nock-api/releases && tar -C /opt/nock-api/releases"
            f" -xzf {remote} && rm {remote}'",
        ],
        ["ssh", "ops@box-1", f"sudo sh {box}/deploy/install.sh {box}"],
    ]
    pack = steps[-4].command
    assert pack[:2] == ["env", "COPYFILE_DISABLE=1"] and pack[2] == "tar"


def test_the_local_half_packs_a_wheel_hashed_requirements_migrations_and_the_ledger(
    tmp_path: Path,
) -> None:
    steps = DEPLOY.plan("ops@box-1", RELEASE, tmp_path)
    for step in steps[:-3]:
        subprocess.run(step.command, cwd=SERVER, check=True)
    with tarfile.open(tmp_path / f"{RELEASE}.tar.gz") as packed:
        names = packed.getnames()
        requirements = packed.extractfile(f"{RELEASE}/requirements.txt")
        assert requirements is not None
        pinned = requirements.read().decode()
    assert not [name for name in names if Path(name).name.startswith("._")]
    for expected in (
        "migrations/0001_reflections_and_usage.sql",
        "deploy/install.sh",
        "deploy/nock-api.service",
        "deploy/nock-api.caddy",
        "logika.json",
    ):
        assert f"{RELEASE}/{expected}" in names
    wheels = [name for name in names if name.endswith(".whl")]
    assert len(wheels) == 1 and Path(wheels[0]).name.startswith("nock_api-")
    packages = {line.split("==")[0] for line in pinned.splitlines() if line and line[0].isalnum()}
    assert not packages & {"nock", "nock-api", "pytest", "ruff"}
    assert {"fastapi", "uvicorn", "psycopg", "psycopg-pool", "logika-otel"} <= packages
    assert "--hash=sha256:" in pinned
    assert all("==" in line for line in pinned.splitlines() if line and line[0].isalnum())


def test_install_sh_is_sound_shell() -> None:
    subprocess.run(["sh", "-n", str(SERVER / "deploy" / "install.sh")], check=True)
