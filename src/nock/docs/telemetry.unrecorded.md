---
term: telemetry.unrecorded
aliases: [nock-unrecorded, nested, test-calls]
description: A nock call made while another nock command runs is not recorded
---

Every nock command sets `NOCK_UNRECORDED=1` for whatever it starts, so a nock call made while another runs — a test suite under `check`, `run` or a test tool calling `.nock/nock` — is not recorded, and tests never pollute the project's telemetry. A call an agent makes directly is recorded, as are those of agents nock dispatches. Set `NOCK_UNRECORDED=1` yourself to keep anything else out.
