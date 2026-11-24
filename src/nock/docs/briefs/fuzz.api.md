---
term: fuzz.api
aliases: []
description: "The fuzz.api lead's brief: edge-case inputs to every API route on a local server, each break told"
---

# The fuzz.api subround

Start the run with `.nock/nock reflect fuzz.api`, or pick up the one under way: it prints the run's material, its agents with their briefs, the files to write and the submit.

The subround sends edge-case inputs to every route of the project's API and
reports what breaks. It changes no code: each finding goes to the owner,
with the fix it proposes.

Set aside whatever this session was doing: the subround works from the API's
description, a local server and its material (below): what earlier runs
found.

1. **Find the surface.** Read the project's instructions and the API's
   description (an OpenAPI document, else the route table in the code),
   and every other door that takes input: ingest or webhook endpoints,
   uploads, wire formats with their fixtures. List the routes, how each
   authenticates and what it owns (a project, an account, a user).
2. **Run it locally.** Start the project's dev services and the API on a
   port of your own, with two accounts or tenants (a seed, or two fresh
   sign-ups), so every id of one can be tried as the other. Never send
   traffic to production, never print a secret, and stop only what you
   started.
3. **Script the fuzzing.** Write one script that the next run reruns:
   schemathesis or Hypothesis against the OpenAPI document where there is
   one, plus the cases a schema can't generate. Start from the last
   run's script when this machine has it (in its scratch directory,
   `.nock/local/reflections/fuzz.api/`). For each
   route, send:
   - empty bodies, missing and extra fields, nulls, wrong types;
   - empty, huge and Unicode strings (RTL, combining marks, NUL, lone
     surrogates), negative numbers, zero, the boundaries of each limit and
     one past them;
   - duplicate JSON keys, deep nesting, a wrong or missing content type;
   - injection strings (SQL, path traversal, header CRLF, template syntax);
   - no credentials, a revoked or malformed one, and the other tenant's
     credentials on this tenant's ids;
   - the same write sent many times at once.
   For each ingest or wire endpoint, mutate the format's fixtures: cut
   short, wrong version, oversized, wrong compression, wrong encoding,
   fields of the wrong type.
4. **Judge the replies.** A finding is a 5xx; a 2xx that should have been
   refused; anything of one tenant visible or changeable from the other; a
   request that hangs past a timeout; or state that is inconsistent
   afterwards (a duplicate row, a half-written write, a counter off).
   Check state through the API, and the database when the API can't show
   it. A 4xx with a clear message is the API working.
5. **Confirm each finding** by hand with a single request, and cut it to
   the smallest repro. Read the code that handled it and name the line.
   Drop what you can't reproduce, or report it as unconfirmed.
6. **Write each finding** in `report.md`: a title that says the fix; what
   breaks, with its file:line and severity (critical: a leak or a write
   across tenants; high: a 5xx or wrong acceptance a client can trigger at
   will; medium: a hang, or a broken state; low: the rest) and how
   confident you are; what the fix takes; the evidence (the repro command
   or file, the server log of the failure). One finding per root cause,
   however many routes it breaks. A finding an earlier run reported that
   still holds is said to be still open, not reported as new.
7. **Keep the script** in the run's scratch directory, beside the report,
   with how to start the server and the accounts and the command that runs
   it.
8. Finish `report.md` for the owner with the routes and requests covered
   and what the run could not reach. Submit with one change per finding
   (kinds error, accepted, leak, hang, state, other).
9. Report the subround in your final message, to the session that ran it: the
   findings by severity, a line each, what needs the owner, and where
   `report.md` and the script are.
