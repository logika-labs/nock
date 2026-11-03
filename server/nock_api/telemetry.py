"""The server's own spans, declared in `server/logika.json` and read in Logika.

Call sites open spans on `tracer`. Until `start` installs the enhancer, OpenTelemetry's default provider
makes them no-ops, so tests and a server without a key pay nothing. The entry point calls `start` when
`OTEL_EXPORTER_OTLP_HEADERS` holds the SDK key; the enhancer reads it, and the ledger `logika.json` from
the working directory (a release's root on the box). Spans carry counts, outcomes, schema versions and
timings: never an address, a header or anything a body says.
"""

import sys
from importlib import metadata

from opentelemetry import trace

tracer = trace.get_tracer("nock_api")


def start() -> None:
    """Install the enhancer as the global tracer provider. Telemetry never takes the API down: when the
    enhancer cannot start, the server says why and runs untraced."""
    import logika_otel  # only a traced server loads the SDK

    try:
        logika_otel.init(service_version=metadata.version("nock-api"))  # pyright: ignore[reportAttributeAccessIssue]
    except Exception as error:
        print(f"nock-api: untraced, the enhancer did not start: {error!r}", file=sys.stderr)
