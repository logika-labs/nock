"""The piece that replaces a dependency: schemas."""

from __future__ import annotations

import pytest

from nock.errors import UsageError
from nock.schema import check_schema, validate


def test_schemas_validate_the_subset_and_refuse_the_rest() -> None:
    schema = {
        "type": "object",
        "required": ["code"],
        "additionalProperties": False,
        "properties": {
            "code": {"type": "integer", "minimum": 100},
            "tags": {"type": "array", "items": {"enum": ["a", "b"]}, "uniqueItems": True},
            "name": {"anyOf": [{"type": "string", "pattern": "^[a-z]+$"}, {"type": "null"}]},
        },
    }
    check_schema(schema)
    validate({"code": 404, "tags": ["a"], "name": None}, schema)
    with pytest.raises(UsageError) as raised:
        validate({"code": 99, "tags": ["a", "a", "c"], "name": "X", "extra": 1}, schema)
    message = str(raised.value)
    for expected in ("less than 100", "repeated", "'c' is not one of", "none of", "unexpected"):
        assert expected in message
    with pytest.raises(UsageError, match="not of type"):
        validate({"code": True}, schema)
    with pytest.raises(UsageError, match=r"'\$ref' is not supported"):
        check_schema({"type": "object", "properties": {"a": {"$ref": "#/x"}}})
