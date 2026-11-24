---
term: errors
aliases: [fail, failed, raise, crash]
description: Fail by raising: the error's class sets the exit code
---

`raise nock.Failed("why", evidence)`: exit 1, the answer is no; the evidence prints like a return value. `nock.UsageError` is 40, called wrong; `nock.PreconditionError` 42, the machine or the state is not ready; `nock.NotFoundError` 44. Returning `False` is a plain no. A crash (50) prints the tool's own lines with the values they held, and is recorded. `.nock/nock docs exit-codes` has them all.
