# The logika instrument round

You instrument one area of the code, the one you were given, with
everything beneath it. Read `logika docs instrument` and `logika docs
rules` and do both, in one pass over every unit of work in the area.

Then measure with `logika map <area>`. Close each item it lists, or give it
a one-line reason. The material below is the whole repository's map when
the round started: read your area's lines, and the reasons earlier rounds
gave (`left:`), which you keep or close.

Then the noise check: `logika test "<command>"` over the area's tests, and
`logika replay '{"on": "capture"}'` over that capture. Fix what fires on
normal behaviour. `logika check` passes.

Report one line each: each rule you added, each event you added, and each
reason you gave, by its item: `silent <file> <function>` (the file from the
repository root), `verdicts <event>` or `unread <event>`. Then the rules
relating your events to another area's. The agent that sent you submits the
round: each reason a change of kind `reason`, its item the target and the
reason its `why`.
