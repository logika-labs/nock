# api.nock.dev

Where nock sends its makers a reflection round's summary (`nock share`, on the
owner's word), the weekly anonymous usage report (on the owner's yes) and what
someone writes to them with `nock report` (on their word). It is
not part of nock: a distribution of its own (`nock-api`, Python 3.14), never
published or vendored, while nock itself stays standard-library only.

```
nock_api/          the server: app.py (the edge and the routes), rules.py (what is kept, field
                   by field), limit.py (the rate limit), migrate.py, telemetry.py, __main__.py
migrations/        NNNN_name.sql, forward-only, applied by `nock-api migrate`
deploy/            deploy.py (from a laptop), install.sh (on the box), nock-api.service,
                   nock-api.caddy
logika.json        the server's own spans, as Logika reads them
tests/             real Postgres (a Docker container per run), real uvicorn, virtual time
```

FastAPI on uvicorn, Postgres through psycopg 3 and an async connection pool,
raw SQL. Only the entry point (`nock_api/__main__.py`) reads the environment and
the clock; the app takes its database URL, `now` and its rate limit as
arguments.

## The API

What arrives is kept with the moment it arrived and nothing about the sender
(no address, no headers). Every `POST` answers `201` with `{"id": N}`, or
`400` with `{"error": "…"}` naming what is wrong — a body with any field it
should not have is refused whole — `413` when the body is too large (refused
unread), `411` without a `Content-Length`, `429` beyond the rate limit, `404`
elsewhere (`501` for a method other than `GET` and `POST`). A `POST`'s
trailing slashes are ignored; a query string names nothing. `GET /health`
answers `{"ok": true}`.

- **`POST /reflections`**: a round's summary, `{"summary": TEXT, "round":
  DATE}` (`round` optional, at most 40 characters; the summary non-empty, at
  most 20,000 characters, kept stripped; the body at most 80 KB). Text
  Postgres cannot hold (a NUL, a lone surrogate) is refused like any other
  wrong value. Kept in `reflections`.
- **`POST /usage`**: a weekly usage report, exactly as nock builds it
  (`src/nock/usage.py`, `Usage.report`; `nock usage` shows one). The body is
  at most 32 KB and holds exactly these fields:

  | field | what |
  |---|---|
  | `schema` | `2` or `3` (3: a metric may be `null`); any other is refused |
  | `project` | the project's anonymous id: a UUID4, lower case |
  | `nock`, `python`, `platform` | versions (`0.3.0`, `3.12`) and `sys.platform` |
  | `settings` | exactly `reminders`, `consult`, `logika`: booleans |
  | `metrics` | at most 64 names (`[a-z][a-z0-9_-]*`, ≤ 40 characters) to numbers ≥ 0 |
  | `commands` | at most 120 of nock's command names (lower-case words) to exactly `{calls, failures}`, whole numbers ≥ 0 |
  | `toolbox` | exactly `tools`, `checks`, `hooks`, `generators`, `load_failures`: whole numbers ≥ 0 |
  | `rounds` | at most 20 kinds of round to whole numbers ≥ 0 |

  Kept in `usage`: the project id and schema as columns (indexed by project,
  to count projects), the report as `jsonb`.
- **`POST /reports`**: what someone wrote with `nock report`, `{"text": TEXT,
  "nock": VERSION, "platform": PLATFORM}` (the text non-empty, at most
  10,000 characters, kept stripped; `nock` and `platform` as in a usage
  report; the body at most 40 KB). Kept in `reports`. Read the latest,
  newest first, with `nock-api reports [--limit N]` (20 by default); on the
  box:

  ```sh
  sudo systemd-run --quiet --wait --pipe --collect --uid=nock-api --gid=nock-api \
    -p EnvironmentFile=/etc/nock-api/nock-api.env /opt/nock-api/current/venv/bin/nock-api reports
  ```

The rate limit is the server's: per client address, 6 requests a minute with a
burst of 5, one limit across every `POST` (a project sends a usage report at
most weekly, a retry at most daily, a summary per round, and a report when
someone writes one); beyond it, `429`
with `{"error": …}` and `Retry-After`. It is a token bucket per address held
in memory only, each address forgotten once its bucket has refilled (under a
minute), never written to the database, a log or a span. The client address
is the first `X-Forwarded-For` entry when the peer is `127.0.0.1` (Caddy),
else the peer. Stock Caddy cannot rate-limit, hence the server's own; the
server runs as one process, so one limit.

### Telemetry

When `OTEL_EXPORTER_OTLP_HEADERS` holds a Logika SDK key
(`authorization=Bearer KEY`), the server sends its own spans to Logika through
`logika-otel`, against `logika.json` (the release's, its working directory);
unset, it runs untraced. Each `POST` is a `reflection`, `usage` or `report` operation
whose outcome is a `kept` child (our row's id, the schema, counts) or a
`refused` one (the status and a one-word reason); the rate limit is a
`limited` moment; migrations are a `migrate` operation. Spans carry counts,
outcomes, schema versions and timings — never an address, a header or
anything a body says (`tests/test_telemetry.py` holds every span to the
ledger and to that). Telemetry never takes the API down: when the enhancer
cannot start, the server says so on stderr and runs untraced. Until
`logika-otel`'s first real release is on PyPI (0.0.2 is a name placeholder),
leave the key unset; then `uv lock --upgrade-package logika-otel`, deploy, set
the key, restart. After changing `logika.json`, `logika sync` it from
`server/`.

## Developing

```sh
cd server
uv sync
uv run pytest            # needs Docker: one postgres:17-alpine container per run
uv run ruff check && uv run ruff format --check && uv run basedpyright
```

To run it locally against a Postgres of your own:

```sh
DATABASE_URL=postgresql://… uv run nock-api migrate
DATABASE_URL=postgresql://… uv run nock-api serve        # 127.0.0.1:8610
DATABASE_URL=postgresql://… uv run nock-api reports      # the latest reports people sent
```

A schema change is a new `migrations/NNNN_name.sql`, never an edit to one
already deployed.

## Where it runs

On Logika's box 1 (Debian 13), beside Logika and on its Postgres 17 (which
wal-g backs up continuously, the `nock` database included):

- **The release**: `/opt/nock-api/releases/ID` (wheel, hashed requirements,
  migrations, `deploy/`, `logika.json`), its virtualenv inside it on a
  uv-managed Python 3.14 in `/opt/nock-api/python`; `/opt/nock-api/current`
  links the live one. Root's, read-only to the service; the five newest are
  kept.
- **The unit**: `deploy/nock-api.service` as
  `/etc/systemd/system/nock-api.service`: the system user `nock-api`,
  sandboxed (`ProtectSystem=strict`, `NoNewPrivileges`, `PrivateTmp`, no
  capabilities, writing nowhere), listening on `127.0.0.1:8610`, restarted on
  failure, its settings from `/etc/nock-api/nock-api.env`.
- **The settings**: `/etc/nock-api/nock-api.env` (root, 0600, read by
  systemd): `DATABASE_URL`, and `OTEL_EXPORTER_OTLP_HEADERS` to send spans to
  Logika.
- **Caddy**: `deploy/nock-api.caddy` as `/etc/caddy/sites/nock-api.caddy`
  (Logika's Caddyfile imports `/etc/caddy/sites/*.caddy`): TLS for
  `api.nock.dev`, the security headers, bodies at most 128 KB, forwarding to
  `127.0.0.1:8610`, no access log; uvicorn writes none either.
- **DNS**: on Cloudflare, an `A` (and `AAAA`) record for `api.nock.dev` to the
  box, DNS only (not proxied), so Caddy gets its certificate and sees the
  sender's address.

### Deploy

From a clean checkout, with the tests green:

```sh
python3 server/deploy/deploy.py ops@BOX
```

It prints its steps and asks first. It builds the wheel and the hashed
requirements (`uv export --frozen`), packs them with the migrations, `deploy/`
and `logika.json` (`COPYFILE_DISABLE=1`, so macOS adds no `._` files), copies
the tarball over SSH and unpacks it under `/opt/nock-api/releases/ID`; then
`deploy/install.sh` on the box, as root: the virtualenv and packages, the
migrations (as `nock-api`, before the restart: forward-only, so the running
release keeps working), the unit, the Caddy site when it changed (validated,
else the previous one is put back), the `current` symlink, the restart, and
the prune.

### Provisioning

Once, on the box, as root (`sudo -i`). The user may already exist from the
standard-library server this replaced:

```sh
id nock-api || useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin nock-api
openssl rand -hex 24 > /root/nock-pg-password && chmod 600 /root/nock-pg-password
sudo -u postgres psql -c "CREATE ROLE nock LOGIN PASSWORD '$(cat /root/nock-pg-password)'"
sudo -u postgres psql -c "CREATE DATABASE nock OWNER nock"
sudo -u postgres psql -d nock -c "REVOKE ALL ON SCHEMA public FROM PUBLIC; ALTER SCHEMA public OWNER TO nock"
install -d -m 0755 /etc/nock-api /opt/nock-api /opt/nock-api/releases
umask 077
printf 'DATABASE_URL=postgresql://nock:%s@localhost:5432/nock\n' "$(cat /root/nock-pg-password)" > /etc/nock-api/nock-api.env
chmod 600 /etc/nock-api/nock-api.env
```

Keep the password in the password manager. `uv` and Caddy are already there
for Logika. Then, from your laptop, the first deploy:

```sh
python3 server/deploy/deploy.py ops@BOX
```

which migrates the new database, installs the unit and the Caddy site, and
starts `nock-api`. Check it:

```sh
curl -s https://api.nock.dev/health
ssh ops@BOX 'systemctl status nock-api --no-pager; sudo -u postgres psql -d nock -c "\dt"'
```

The standard-library server's leftovers go once the new one answers (its
SQLite database never held a row):

```sh
rm -rf /srv/nock-api /var/lib/nock-api
```

To send spans to Logika once `logika-otel` is released (see Telemetry): add
`OTEL_EXPORTER_OTLP_HEADERS=authorization=Bearer KEY` to
`/etc/nock-api/nock-api.env` and `systemctl restart nock-api`.
