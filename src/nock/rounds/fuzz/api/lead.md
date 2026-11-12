# The API fuzzing round

The round sends edge-case inputs to every route of the project's API and
records what breaks. It changes no code: each finding becomes a decision
the owner gives a verdict on.

Set aside whatever this session was doing: the round works from the API's
description, a local server and its material (below), the topic
`fuzz-api` as the last round left it.

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
3. **Script the fuzzing.** Write one script that the next round reruns:
   schemathesis or Hypothesis against the OpenAPI document where there is
   one, plus the cases a schema can't generate. Start from the last
   round's script (its asset in `fuzz-api`) when there is one. For each
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
   Drop what you can't reproduce, or record it as unconfirmed.
6. **Record each finding as a decision** in the topic `fuzz-api`
   (`.nock/nock docs topics.items`): the title says what breaks; the
   problem with its file:line and severity (critical: a leak or a write
   across tenants; high: a 5xx or wrong acceptance a client can trigger
   at will; medium: a hang, or a broken state; low: the rest) and how
   confident you are; the proposed fix as the answer and the others as
   alternatives. Attach the evidence as assets: the repro command or file,
   the server log of the failure, a screenshot as a derived file with its
   recipe when a page shows it. One decision per root cause, however many
   routes it breaks. A finding the last round recorded and still holds is
   a new version of that item, not a new one.
7. **Keep the script** as a file item in the topic, with its recipe: how
   to start the server and the accounts, and the command that runs it.
8. Write `report.md` for the owner: the routes and requests covered, the
   findings by severity with their items, what the round could not reach.
   Submit with one change per finding (kinds error, accepted, leak, hang,
   state, other).
