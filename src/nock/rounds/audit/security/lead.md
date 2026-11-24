# The audit.security subround

The subround finds and reports; it fixes nothing. Work against a local or
development copy of the system, never production: read production config
freely, send it no traffic. Never print a secret; name the file and key.

1. Map the attack surface from the code, the docs and the deployment. The
   usual areas, each kept only where the project has it:
   - authentication and sessions: sign-in, tokens, their lifetime, revocation;
   - authorisation: every route or command against every role, across
     accounts and tenants (the permission matrix);
   - tenant isolation in storage and queries: every query, file path and
     cache key that holds another tenant's data;
   - each boundary that takes outside input: public endpoints, uploads,
     webhooks, queues; sizes, rates, parsing, abuse;
   - payments and webhooks: signatures, replay, idempotence;
   - secrets and logs: where secrets live, what logs, traces and errors
     carry (secrets, personal data);
   - what the project installs on users' machines: CLIs, hooks, tokens on
     disk, auto-update;
   - the client: XSS, CSRF, CSP, cookies, what the browser stores;
   - the deployment: proxy and TLS, open ports, service users, sudo,
     service hardening, backups;
   - dependencies: the ecosystems' advisory audits (`pip-audit`,
     `cargo audit`, `pnpm audit`, `npm audit`, `govulncheck`, …).
2. Dispatch one `audit-security` subagent per area, with the material
   (below), the area, the files and docs that bear on it and how to run the
   system locally. Small projects may need two or three; do a tiny area
   yourself. If one fails, say so in the report; don't redo its part.
3. Check each finding the parts return: drop what you cannot reproduce or
   point at in the code, merge duplicates, and rank them by severity
   (critical, high, medium, low, info) with how confident you are (proven
   by a repro, read in the code, suspected).
4. Write `report.md` for the owner: the findings ranked, top first, each
   with the fix you propose as its title; the problem in a line or two,
   with the severity, the confidence and the evidence (file:line, the
   repro command and what it printed); what the fix takes. Then the areas
   covered and those not, and what blocked the parts. Put nothing
   exploitable against production in it: describe the class and the local
   repro.
5. Submit with one change per finding (kind risk, target the finding's
   file:line, why its severity) and kind other for an area left uncovered.
6. Report the subround in your final message, to the session that ran it: the
   findings ranked, a line each with its severity and confidence, what
   needs the owner, and where `report.md` is.
