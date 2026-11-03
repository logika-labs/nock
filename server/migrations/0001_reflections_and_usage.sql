-- What api.nock.dev keeps: each summary or usage report with the moment it arrived, nothing about its
-- sender (no address, no headers).
CREATE TABLE schema_migrations (
    name text PRIMARY KEY,
    applied timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE reflections (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    received timestamptz NOT NULL,
    round text,
    summary text NOT NULL
);

CREATE TABLE usage (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    received timestamptz NOT NULL,
    project uuid NOT NULL,
    schema integer NOT NULL,
    report jsonb NOT NULL
);

-- To count projects.
CREATE INDEX usage_by_project ON usage (project);
