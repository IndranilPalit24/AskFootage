"""contract/openapi.yaml describes POST /api/auth/demo-code the way the spec asks."""

from __future__ import annotations

import json
import re
from pathlib import Path

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contract" / "openapi.yaml").read_text(encoding="utf-8")
)
OPERATION = CONTRACT["paths"]["/api/auth/demo-code"]["post"]
SCHEMAS = CONTRACT["components"]["schemas"]


def test_the_only_method_is_post() -> None:
    assert set(CONTRACT["paths"]["/api/auth/demo-code"]) == {"post"}
    assert OPERATION["operationId"] == "checkDemoCode"


def test_the_body_is_six_digits_and_nothing_else() -> None:
    ref = OPERATION["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    schema = SCHEMAS[ref.rsplit("/", 1)[1]]
    assert schema["required"] == ["code"]
    assert schema["additionalProperties"] is False
    pattern = schema["properties"]["code"]["pattern"]
    assert pattern == "^[0-9]{6}$"
    assert re.fullmatch(pattern, "012345") and not re.fullmatch(pattern, "12345a")


def test_the_answers_are_200_401_422_429_500() -> None:
    assert set(OPERATION["responses"]) == {"200", "401", "422", "429", "500"}
    ok = OPERATION["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    accepted = SCHEMAS[ok.rsplit("/", 1)[1]]
    assert list(accepted["properties"]) == ["ok"]
    assert accepted["properties"]["ok"]["const"] is True
    assert "Retry-After" in OPERATION["responses"]["429"]["headers"]


def test_every_error_uses_the_one_error_body() -> None:
    for status in ("401", "422", "429", "500"):
        response = OPERATION["responses"][status]
        schema = response.get("content", {}).get("application/json", {}).get("schema", {})
        assert schema == {"$ref": "#/components/schemas/Error"}, status
    assert "token" not in json.dumps(SCHEMAS["DemoCodeAccepted"]).lower()
