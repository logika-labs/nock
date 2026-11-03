# nock.dev

The website, kept beside the code it documents. It is not part of nock: `nock
init` vendors `src/nock/` only, and the package is built from `src/` only.
Standard library only, like nock.

```
site/              the pages: index.html, style.css, docs/ (built, gitignored)
docs.html          the docs page's template
legal/             privacy.md and terms.md → site/privacy/, site/terms/ (built, gitignored)
page.html          their template
build.py           ../README.md → site/docs/index.html, with a table of contents; legal/ → its pages
publish.py         build, and push to GitHub Pages
api/               api.nock.dev, where `nock share` sends a summary and nock its usage reports (on Logika's box)
```

## Build

```sh
python3 web/build.py
```

The docs page is the README, so edit the README, never `site/docs/`. To look at
the site, serve `web/site/` (`python3 -m http.server -d web/site`).

## Publish

```sh
python3 web/publish.py --no-push   # build, stage and commit in web/pages/; show the change
python3 web/publish.py             # the same, then ask before pushing
```

The site is served by GitHub Pages from `logika-labs/nock.dev` (branch `main`,
the root). Publishing clones it into `web/pages/` (gitignored), replaces
everything but `.git` with `site/` plus `CNAME` (`nock.dev`) and `.nojekyll`,
commits, shows the change, and pushes only when you answer `y`.

## The API

`api/reflections.py` is api.nock.dev, a standard-library server keeping what
it is sent in one SQLite database, with the moment it arrived and nothing
about the sender (no address, no headers). Every `POST` answers `201` with
`{"id": N}`, or `400` with `{"error": "…"}` naming what is wrong — a body
with any field it should not have is refused whole — `413` when the body is
too large, `411` without a `Content-Length`, `429` beyond the rate limit,
`404` elsewhere. `GET /health` answers `{"ok": true}`. The tests
are `tests/test_api.py`.

- **`POST /reflections`**: a round's summary, `{"summary": TEXT, "round":
  DATE}` (`round` optional; the summary non-empty, at most 20,000
  characters; the body at most 80 KB). Kept in `reflections`.
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

  Kept in `usage`: the project id and schema as columns (indexed by
  project, to count projects), the report as JSON.

The rate limit is the server's: per client address, 6 requests a minute with
a burst of 5, one limit across both endpoints (a project sends a usage report
at most weekly, a retry at most daily, and a summary per round); beyond it,
`429` with `{"error": …}` and `Retry-After`. It is a token bucket per address
held in memory only, each address forgotten once its bucket has refilled
(under a minute), never written to the database or a log. The client address
is the first `X-Forwarded-For` entry when the peer is `127.0.0.1` (Caddy),
else the peer.

It runs on Logika's box (Debian 13, its `python3`, Caddy in front):

- **The code**: `api/reflections.py` copied to `/srv/nock-api/`, owned by
  root, read-only to the service.
- **The unit**: `api/nock-api.service` as
  `/etc/systemd/system/nock-api.service`: the system user `nock-api`, the
  database in `/var/lib/nock-api/reflections.db` (its `StateDirectory`, the
  only place it may write), sandboxed (`ProtectSystem=strict`,
  `NoNewPrivileges`, `PrivateTmp`), listening on `127.0.0.1:8610`, restarted
  on failure. It makes its tables on start.
- **Caddy**: `api/Caddyfile.snippet` as `/etc/caddy/sites/nock-api.caddy`
  (the box's Caddyfile imports `/etc/caddy/sites/*.caddy`): TLS for
  `api.nock.dev`, the security headers, bodies at most 128 KB, forwarding to
  `127.0.0.1:8610`, no access log. Stock Caddy cannot rate-limit, hence the
  server's own limit.
- **DNS**: on Cloudflare, an `A` (and `AAAA`) record for `api.nock.dev` to
  the box, DNS only (not proxied), so Caddy gets its certificate and sees the
  sender's address.

`nock share` posts to `https://api.nock.dev/reflections` (the
`endpoints.reflections` setting), the usage reports go to
`https://api.nock.dev/usage` (`endpoints.usage`). To run it elsewhere:
`python3 reflections.py --database PATH --port 8610`.
