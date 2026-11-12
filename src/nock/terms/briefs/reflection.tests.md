---
term: reflection.tests
aliases: []
description: The tests round's package brief: one package's coverage and weak, faked, flaky, slow tests
---

You audit the tests of one package, which the lead names with how the
project runs them. Read the project's instructions on testing first. Change
no code and no test; write evidence only into the round's scratch directory.
Run the package's suite at most twice, one package at a time, on services
and ports of your own.

1. **Coverage.** Run the package's suite with line and branch coverage (the
   project's coverage command, else the language's usual tool). Keep the
   totals and the report. Then read the uncovered lines that matter: error
   and rollback paths, money, sign-in and permissions, migrations and data
   formats, retries and timeouts. Name each uncovered case: the function,
   its `file:line`, the input that would reach it.
2. **Assertions.** Find tests that assert little: no assertion, only
   "doesn't raise", only a status code, a snapshot nobody reads, an
   assertion that holds whatever the code does. Name what it should check.
3. **Fakes.** Find mocks, stubs and patches of what the instructions say must
   be real (the database, the filesystem, the clock read in place of passed
   in, the project's own server or CLI), and sleeps in place of waiting on a
   condition.
4. **Flakes.** From the material's commits, the CI history if you can read
   it, and the run you did: tests that failed once and passed again, that
   race on time, ports, order or shared state, or that pass only on a
   developer's machine (a tool on PATH, a file in a home directory, an
   environment variable). Give the cause you find in the code and how to
   reproduce it (a seed, a loop of runs, an empty PATH).
5. **Slow tests.** The 20 slowest by duration from the runner's own report,
   and for the slow ones what makes them slow: setup per test that could be
   shared, real waits, large inputs, repeated builds.

Return your findings, each with: the kind (coverage, assertion, fake, flaky,
slow, other), the test or code at `file:line`, the specific missing or wrong
case, the repro command, the evidence file you wrote, the fix you would
propose and its alternatives, and how sure you are (confirmed, likely,
possible). Then the numbers: coverage line and branch, test count, total
time, the slowest 20.
