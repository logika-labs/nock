"""Generators: files the project derives rather than writes — and so can never
drift from their source. Two kinds:

- a `@nock.generator(path)` function returns the text of one file (or its
  exact bytes), from whatever it reads (a schema, a spec, the code itself);
- a catalog is a central ledger the code is generated from — error codes,
  feature flags, UI strings: plain files under `.nock/generators/NAME/` an
  agent edits — the schema of one entry (`schema.json`), the entries
  (`entries.json`), templates (`nock.templates`) and which file each renders
  (`outputs.toml`).

`nock gen` writes every generated file, refusing a catalog whose entries do
not fit its schema; the `nock-generators` check fails on that and on drift."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nock.errors import Error, NotFoundError, PreconditionError, UsageError
from nock.fixtures import Call, Scope
from nock.schema import Validator
from nock.templates import Library
from nock.utils import read_json, write_atomic

if TYPE_CHECKING:
    from nock.project import Project
    from nock.tools import Generator


@dataclass
class Binding:
    template: str
    file: str
    tag: str | None = None


class Catalog:
    def __init__(self, project: Project, name: str) -> None:
        self.project = project
        self.name = name

    @property
    def directory(self) -> Path:
        return self.project.code_path("generators", self.name)

    @property
    def schema_file(self) -> Path:
        return self.directory / "schema.json"

    @property
    def entries_file(self) -> Path:
        return self.directory / "entries.json"

    @property
    def outputs_file(self) -> Path:
        return self.directory / "outputs.toml"

    def exists(self) -> bool:
        return self.schema_file.is_file()

    def schema(self) -> dict[str, Any]:
        return read_json(self.schema_file)

    def entries(self) -> dict[str, dict[str, Any]]:
        return read_json(self.entries_file) if self.entries_file.is_file() else {}

    def bindings(self) -> list[Binding]:
        if not self.outputs_file.is_file():
            return []
        data = tomllib.loads(self.outputs_file.read_text())
        return [
            Binding(item["template"], item["file"], item.get("tag"))
            for item in data.get("output", [])
        ]

    # --- validation ---------------------------------------------------------------

    def problems(self, entries: dict[str, dict[str, Any]] | None = None) -> list[str]:
        entries = self.entries() if entries is None else entries
        schema = self.schema()
        return [
            f"{self.name}.{key}: {problem}".replace("(root)", "(entry)")
            for key, entry in entries.items()
            for problem in Validator().problems(entry, schema)
        ]

    def rendered(self, root: Path | None = None) -> dict[Path, str]:
        """Each bound output's path and the text it should hold."""
        root = root or self.project.here
        entries = self.entries()
        catalogs = {
            catalog.name: listed(catalog.entries()) for catalog in Catalogs(self.project).all()
        }
        outputs = {}
        library = Library(self.directory / "templates")
        for binding in self.bindings():
            chosen = {
                key: entry
                for key, entry in entries.items()
                if binding.tag is None or binding.tag in (entry.get("tags") or [])
            }
            outputs[root / binding.file] = library.render(
                binding.template,
                entries=listed(chosen),
                catalog=self.name,
                catalogs=catalogs,
                tag=binding.tag,
            )
        return outputs

    def drifted(self, root: Path) -> list[str]:
        return [
            str(path.relative_to(root))
            for path, text in self.rendered(root).items()
            if not path.is_file() or path.read_text() != text
        ]


class Entry(dict[str, Any]):
    """An entry as templates see it: its fields read as attributes too
    (`entry.code`), and a field it lacks reads as None."""

    def __getattr__(self, name: str) -> Any:
        return self.get(name)


def listed(entries: dict[str, dict[str, Any]]) -> list[Entry]:
    return [Entry(key=key, **entry) for key, entry in sorted(entries.items())]


class Catalogs:
    def __init__(self, project: Project) -> None:
        self.project = project

    @property
    def directory(self) -> Path:
        return self.project.code_path("generators")

    def all(self) -> list[Catalog]:
        if not self.directory.is_dir():
            return []
        return [
            Catalog(self.project, path.name)
            for path in sorted(self.directory.iterdir())
            if (path / "schema.json").is_file()
        ]

    def get(self, name: str) -> Catalog:
        catalog = Catalog(self.project, name)
        if not catalog.exists():
            raise NotFoundError(f"no catalog {name!r} — `nock gen new {name} SCHEMA` creates it")
        return catalog


class Generators:
    """Every generated file, from functions and catalogs alike."""

    def __init__(self, project: Project) -> None:
        self.project = project

    def outputs(self, root: Path | None = None) -> dict[Path, str | bytes]:
        """Each generated file's path and what it should hold: text, or the
        exact bytes a generator returned."""
        root = root or self.project.here
        outputs: dict[Path, str | bytes] = {}
        for catalog in Catalogs(self.project).all():
            outputs.update(catalog.rendered(root))
        for entry in self.project.registry.generators:
            outputs[root / entry.path] = self.generate(entry)
        return outputs

    def generate(self, entry: Generator) -> str | bytes:
        """Text ends with a newline; bytes are the file as they are."""
        values = {"project": self.project, "call": Call(None, f"generate {entry.name}")}
        try:
            with Scope(self.project.registry, values) as scope:
                text = scope.call(entry.function)
        except Error:
            raise
        except Exception as error:
            raise PreconditionError(
                f"generator {entry.name} ({entry.source}) failed: {type(error).__name__}: {error}"
            ) from error
        if isinstance(text, bytes):
            return text
        if not isinstance(text, str):
            raise PreconditionError(
                f"generator {entry.name} ({entry.source}) returned {type(text).__name__}, not the file's text or bytes"
            )
        return text if text.endswith("\n") or not text else text + "\n"

    def write(self) -> list[Path]:
        """Write every generated file that differs, each before the next is
        generated, so a generator may read a file an earlier one writes;
        returns what changed."""
        written = []
        root = self.project.here
        for catalog in Catalogs(self.project).all():
            problems = catalog.problems()
            if problems:
                raise UsageError(
                    f"catalog {catalog.name}'s entries don't fit its schema: {'; '.join(problems)}"
                )
            for path, text in catalog.rendered(root).items():
                if not holds(path, text):
                    write_atomic(path, text)
                    written.append(path)
        for entry in self.project.registry.generators:
            path, content = root / entry.path, self.generate(entry)
            if not holds(path, content):
                write_atomic(path, content)
                written.append(path)
        return written

    def drifted(self, root: Path) -> list[str]:
        return [
            str(path.relative_to(root))
            for path, content in self.outputs(root).items()
            if not holds(path, content)
        ]


def holds(path: Path, content: str | bytes) -> bool:
    if not path.is_file():
        return False
    return (
        path.read_bytes() == content if isinstance(content, bytes) else path.read_text() == content
    )
