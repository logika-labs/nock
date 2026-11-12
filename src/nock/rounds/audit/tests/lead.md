# The tests audit

The audit records; it changes no code and no test. Read the project's
instructions first (its CLAUDE.md or AGENTS.md, its testing guide or skill):
they say what must be real in a test, how to run the suites, and what
matters most.

1. Bring up only what the tests need, on ports of your own, never against
   production. Other agents may share the machine and its services: run one
   package at a time and stop what you started.
2. Dispatch one `audit-tests-package` subagent per package with its own test
   runner (its material lists where the tests are), with the package's path
   and how the project runs its tests, and one `audit-tests-promises`
   subagent with the project's specification documents. Each returns
   findings and writes their evidence into the round's scratch directory;
   none changes the project. If one fails, say so in the report; don't do
   its part yourself.
3. Check each finding before you keep it: run its repro once, open the file
   at its line. Drop what doesn't reproduce or what a test elsewhere already
   covers. Merge findings that share a cause.
4. Rank what is left by severity: **high** a defect could ship unseen in
   money, access, data or migrations, or the gate fails at random; **medium**
   an error path, a promise or a slow suite that costs every run; **low**
   the rest. Give each a confidence: confirmed (reproduced), likely (read in
   the code), or possible.
5. Record each finding as a decision in the round's topic (`audit-tests`;
   `.nock/nock docs topics.decisions`): the title says the problem and where
   ("Billing's refund path has no test"); the answer is the fix you propose,
   with the severity, the confidence, the test or code at `file:line` and the
   case that is missing; the alternatives are the other fixes, "don't" among
   them where it is a real choice. Its derived files are the evidence, each
   with its recipe: a coverage excerpt, a log of a flaky run, a repro script,
   a duration table, a screenshot.
6. Write `report.md`: the findings in order of severity, one line each with
   its item, then the numbers (coverage per package, the slowest tests, the
   flakes seen). Submit it as a file in the topic too, then submit the round
   with one change per finding (kinds coverage, assertion, fake, flaky, slow,
   gap, other).
