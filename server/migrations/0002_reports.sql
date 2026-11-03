-- What someone wrote to nock's makers with `nock report`: the text, nock's version and the platform it
-- ran on, with the moment it arrived, and nothing about its sender.
CREATE TABLE reports (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    received timestamptz NOT NULL,
    text text NOT NULL,
    nock text NOT NULL,
    platform text NOT NULL
);
