-- nock's docs as published with `scripts/publish_docs.py`: the newest signed bundle for each oldest nock
-- it is for, exactly as it was sent, with its version and the moment it arrived.
CREATE TABLE docs (
    min_cli text PRIMARY KEY,
    version bigint NOT NULL,
    bundle text NOT NULL,
    received timestamptz NOT NULL
);
