"""What a session would have cost at the API's list prices — API-equivalent
cost, which a subscription does not pay per token. The prices are LiteLLM's
public table, fetched with a plain GET at most once a day and cached in
`.nock/local/prices.json`; `[pricing]` overrides them by model-name prefix. A
model in neither, or no table at all, is unpriced: its cost is unknown, never 0."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from nock.errors import PreconditionError
from nock.releases import VERSION
from nock.utils import read_json, write_atomic

if TYPE_CHECKING:
    from nock.project import Project

CACHE = "prices.json"
# Seconds a fetched table stands, and how long after a failed fetch the next is tried.
REFRESH = 86400
RETRY = 3600
# Seconds a fetch may take: it can run as a session starts.
TIMEOUT = 3
# The token kinds a session counts, and the table's per-token price of each.
KINDS = {
    "input": "input_cost_per_token",
    "output": "output_cost_per_token",
    "cache_read": "cache_read_input_token_cost",
    "cache_write": "cache_creation_input_token_cost",
}
DATED = re.compile(r"-\d{8}$")


class Prices:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.path = project.local / CACHE
        self.overrides = {
            prefix: rates
            for prefix, rates in project.configuration.section("pricing").items()
            if isinstance(rates, dict)
        }
        self.loaded: dict[str, dict[str, float]] | None = None

    def table(self) -> dict[str, dict[str, float]]:
        """Model → dollars per token by kind: the cached table, fetched again
        when a day old (and fetching is on); empty when there is none."""
        if self.loaded is not None:
            return self.loaded
        cached = self.cached()
        moment = time.time()
        fresh = moment - float(cached.get("fetched") or 0) < REFRESH
        tried = moment - float(cached.get("tried") or 0) < RETRY
        if not fresh and not tried and self.project.configuration.get("pricing.fetch") is not False:
            cached = self.fetch(cached, moment)
        loaded: dict[str, dict[str, float]] = cached.get("models") or {}
        self.loaded = loaded
        return loaded

    def cached(self) -> dict[str, Any]:
        try:
            return read_json(self.path) if self.path.is_file() else {}
        except PreconditionError:
            return {}

    def fetch(self, cached: dict[str, Any], moment: float) -> dict[str, Any]:
        """The table from `pricing.table`, reduced to the prices nock uses;
        the cache as it was, marked tried, when it cannot be had."""
        url = str(self.project.configuration.get("pricing.table"))
        request = urllib.request.Request(url, headers={"User-Agent": f"nock/{VERSION}"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                raw = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            self.keep({**cached, "tried": moment})
            return {**cached, "tried": moment}
        models = {
            name: {kind: float(entry.get(field) or 0) for kind, field in KINDS.items()}
            for name, entry in (raw.items() if isinstance(raw, dict) else [])
            if isinstance(entry, dict)
            and isinstance(entry.get("input_cost_per_token"), int | float)
        }
        fetched = {"fetched": moment, "tried": moment, "models": models}
        self.keep(fetched)
        return fetched

    def keep(self, cached: dict[str, Any]) -> None:
        write_atomic(self.path, json.dumps(cached, separators=(",", ":")))

    def rates(self, model: str) -> dict[str, float] | None:
        """Dollars per token by kind for `model`: `[pricing]`'s longest
        matching prefix (dollars per million), else the table's entry for the
        model, its undated name or its `anthropic/` name."""
        matching = [prefix for prefix in self.overrides if model.startswith(prefix)]
        if matching:
            rates = self.overrides[max(matching, key=len)]
            return {kind: float(rates.get(kind, 0)) / 1_000_000 for kind in KINDS}
        table = self.table()
        for name in (model, DATED.sub("", model), f"anthropic/{model}"):
            if name in table:
                return table[name]
        return None

    def cost(self, usage: Mapping[str, Mapping[str, int]]) -> float | None:
        """The API-equivalent cost of tokens by model and kind; None when any
        model that used tokens is unpriced."""
        total = 0.0
        for model, tokens in usage.items():
            if not any(tokens.values()):
                continue
            rates = self.rates(model)
            if rates is None:
                return None
            total += sum(tokens.get(kind, 0) * rates[kind] for kind in KINDS)
        return total
