---
term: guide.permissions
aliases: [guide.agents]
description: The permissions nock writes, and what its own agents may and may not do
---

# What nock's agents may do

nock never bypasses Claude Code's permission checks: no code path passes
`--dangerously-skip-permissions` or `--permission-mode bypassPermissions`,
and nock refuses an `agent.command` that does (or that sets the permission
flags nock sets itself). A test holds the package, the evals and the
scripts to it.

**In your sessions,** the rules `nock init` writes into
`.claude/settings.json` are all there is, one per command, nothing that
runs arbitrary shell:

- `allow`: `.nock/nock` (it lists the tools) and each of the toolbox's
  commands, nock's and the project's, which read, record in `.nock/`, or
  run the project's own committed tools and checks;
- `ask`: every `confirm=True` command, the project's and nock's own:
  `init` (it rewrites these rules), `upgrade` (it fetches and merges code;
  the one exception is the clean upgrade a session start runs by itself,
  which the owner made the default and `upgrade.auto = false` turns off)
  `share` (it sends a summary out) and `report` (it sends what you wrote
  to nock's makers). Claude Code asks about these even
  in bypass mode; `permissions.confirm = "allow"` in `.nock/config.toml`
  moves them to `allow` and leaves nock no `ask` rule, and the agents are
  told to run them only when the owner's request calls for them;
- no rule for `run`, which runs any command: Claude Code asks about it as
  it would about the command itself.

Re-running `nock init` replaces nock's own rules and keeps everyone else's;
it removes the blanket `Bash(.nock/nock:*)` earlier versions wrote, which
`nock-wiring` flags until then.

**The agents nock dispatches** (`claude -p`, no human in the session) run
in `dontAsk`: each has the Claude Code tools and allow rules its brief
needs and nothing else, and anything else is refused, never prompted, so
a run cannot hang on a question. The project's and the checkout's own
Claude Code settings are not loaded (`--setting-sources user`), so the
project's allow rules never widen a seat (nor are the project's CLAUDE.md,
skills, hooks or MCP servers: the brief carries what the seat needs).
Reading files in the directory it runs in needs no rule.

| seat | tools | may run |
|---|---|---|
| consultant | Read, Grep, Glob, Bash | `.nock/nock topics list`, `topics show`, `items list`, `items show`, `docs`, `advise` |
| asker | Read, Grep, Glob, Bash | `.nock/nock topics list`, `topics show`, `items list`, `items show`, `topics answer`; `git log`, `git show` |
| sharer | Read, Grep, Glob, Bash | `git log` |

`git log` and `git show` are allowed without `--output` (or any
abbreviation of it git accepts, down to `--ou`), which a deny rule refuses:
it would write their output to a file.

None can edit a file, reach the network or run any other command. What
Claude Code refused comes back with the session: in the consultation's
record and its failure, in the asker's log, in the vetted summary's
record and the share's failure, and in the run's log.
The owner's user-level Claude Code settings still apply to these sessions:
they are the owner's.

**A round's parts** are subagents of the session running the round, so
the session's permissions apply, narrowed by the subagent types nock
installs in `.claude/agents/`: the toolbox part (`nock-reflect-toolbox`)
reads, edits and runs commands, and its brief keeps it to `.nock/`; the map
part (`nock-reflect-map`) reads and edits the map; the nock part
(`nock-reflect-nock`) and the logika round's parts (`nock-logika-rules`,
`nock-logika-analytics`) only read and run commands, with no tool that
edits a file. A refused call is reported, not worked around.
