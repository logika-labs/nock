# The performance audit

Find what makes the project slow or costly, with numbers, and put each
finding before the owner as a proposal. You change no code: you measure and
record. You do the measuring yourself, one thing at a time, because timings
taken side by side on one machine skew each other.

Done when every hot path below that the project has is measured, each real
finding is a proposal with its evidence, `report.md` ranks them, and
`.nock/nock reflect --submit` has recorded the round.

1. Read the material: the proposals earlier rounds left in the round's
   task, `round-audit-performance` (`.nock/local/views/round-audit-performance.md`).
   A finding that is still there, accepted and not fixed, is measured again
   and kept, not recorded twice; one the owner rejected is dropped unless
   the numbers changed. Starting the round opened the task (or revived it).
2. Learn the project before you time it: the docs that say what it must
   handle (sizes, rates, budgets), its benchmarks and their baseline, how
   it runs locally. Work against the local stack, never production, and
   on a port of your own; start only processes you stop again.
3. Name the hot paths, and for each what a user waits for or what it
   costs:
   - requests: latency per route, at the sizes the docs name;
   - ingestion and jobs: throughput, and the duration and peak memory of
     each scheduled pass at a realistic volume;
   - queries: N+1 patterns (count the queries a request makes),
     sequential scans on large tables (`EXPLAIN ANALYZE` on the dev
     database), reads with no bound on rows or bytes;
   - start-up: each process's time to ready and its import time
     (`python -X importtime`, `node --cpu-prof`, `hyperfine` on a CLI);
   - the web app: bundle size per route, compressed, and first load
     (a production build, then the browser's network panel or Lighthouse).
4. Measure each. Run the benchmarks against their baseline and say which
   moved. Repeat a timing until it is stable (at least five runs; give the
   median and the spread) and note what else loaded the machine. Measure;
   don't speculate: a cost you only read in the code is a lead to measure,
   not a finding.
5. A finding is a cost that breaks a stated budget, grows faster than its
   input, or is large next to the work it does. For each, record a
   proposal in the round's task (`.nock/nock docs topics.items files.item`):
   - the title says the fix and what it brings ("Index orders by account:
     the list drops from 900 to 40 ms");
   - `means`: the problem in a line or two, with file:line and the
     numbers, its severity (critical, high, medium, low: how many users
     wait and for how long, or what it costs) and how confident you are;
   - `takes`: roughly what the fix takes;
   - assets in the task: the repro command or script, its output, a
     profile, each a derived file with its recipe (`.nock/nock docs
     topics.derived`), so the owner can run it again.
6. Write `report.md` for the owner: the findings, worst first, each in a
   line with its number and its item; then the paths you measured that are
   fine, with their numbers; then what you could not measure and why.
   Submitting puts it in the task's review with the proposals; add a
   `table` or `chart` block of the numbers where they say more
   (`.nock/nock docs review`).
7. Submit, one change per finding (kinds latency, throughput, query,
   memory, startup, bundle, other): its `target` the file:line, its `why`
   the numbers, its `expect` what the next round should measure once it
   is fixed.
