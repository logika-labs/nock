# From questions to analytics

Logika already keeps numbers for every declared event and every numeric
param: how many, how often they fail, how slow, the sums and the shape of
each value. What it cannot guess is anything about people or combinations:
which param is someone worth following, which is worth breaking down by,
which events form a sequence the owner cares about. That is declared in the
ledger, and this part proposes it, so the owner's questions are answered
from real captures instead of from a query someone writes later.

Logika's docs are the authority on syntax: never write a form from memory.
Run `logika docs analytics` and its children (`analytics.series`,
`analytics.breakdown`, `analytics.actives`, `analytics.funnel`), then
`logika docs ledger.params`, `ledger.funnels` and `ledger.views`, and
`query.analytics` for what is kept. Declared late, a flag, funnel or
milestone is filled in from the last 30 days, so nothing here is urgent and
nothing is lost by asking first.

Take the system one flow at a time, through the steps below.

## 1. Find what the owner would ask

Read the material's params and events, the code behind them, the README and
the product's own words. For each flow (signing up, buying, publishing,
paying, inviting), write the questions someone running the product asks:
how many people do it, do they come back, how many who start it finish it,
how long it takes them, which plans, regions or channels dominate. Logika's
numbers already answer how much, how often it fails and how slow: don't
propose those again.

## 2. Map each question to a declaration

- **An identity**: a param that names someone or something worth following
  over time (a user, an account, a tenant, a device). It is what actives,
  retention, funnels and milestones count. One per kind of someone; mark
  the one the events already carry, never a per-request id.
- **A dimension**: a small, stable set worth breaking down by (a plan, a
  method, a reason, a region). Never an id, never free text, never a value
  with more than a few dozen distinct values in the data.
- **A funnel**: steps that the same identity takes in order, within a time
  (`within`): each step an event and the same identity param.
- **A milestone**: the time from one event to another, for the same
  identity: how long until someone first does X after Y.
- **A view**: the panels the owner would open first, grouped by flow.

## 3. Check it against real captures

With `logika show query`, bounded by `_environment` and `_start`, confirm
that each event a declaration names occurs, that the identity param is
there on every step and means the same someone on each, and that a
dimension's distinct values are few and stable. A funnel whose steps carry
different ids for the same person, or a dimension with hundreds of values,
is wrong, however reasonable it looks. Say in the change's `tested` which
captures showed it.

## 4. When the data isn't there, propose instrumentation

If a question needs something the code doesn't emit — the identity on a
step, a step as an event of its own, the plan as a param — propose the
instrumentation instead of a declaration that would stay empty. Each
proposal becomes a todo tagged `logika` and `instrumentation`, naming the
event, its params, where in the code it goes, and the question it would
answer.

## Keeping it honest

- A person's identity is personal data: mark it `pii` when it is one (`logika
  docs pii`), and never make free text a dimension.
- Fewer, sharper funnels beat one per page: each should answer a question
  the owner said they have.
- Reuse a param that already means the thing before adding one.
- Ask the owner what they want to measure before declaring it; a guess here
  costs their attention every time they open a view.

## What you change

Only `logika.json`: params' `identity` and `dimension` flags, `funnels`,
`milestones` and `views`. Change nothing else, not the code and not
`.nock/`, except by recording decisions and todos. Commit
nothing: `.nock/nock reflect logika finish` commits.
