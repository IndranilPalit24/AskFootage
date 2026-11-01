"""Contract drift: the app's own OpenAPI document must match contract/openapi.yaml.

contract/openapi.yaml is written in JSON syntax (valid YAML 1.2), so json reads it. Each
check returns a list of differences, so a failure names every drift at once. The last
tests feed the checks a deliberately drifted copy to prove they notice.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from api_fakes import CONTRACT_DIR, InMemoryLibrary, load_example
from api_support import TODAY
from pydantic import BaseModel, TypeAdapter

from askfootage.application.library import Library
from askfootage.interfaces.api import schemas
from askfootage.interfaces.api.app import API_VERSION, create_app

Spec = dict[str, Any]
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
CONSTRAINT_KEYS = (
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "pattern",
    "format",
)
# Point is an array schema the app writes inline as a tuple type; Zone's points cover it.
SCHEMAS_NOT_COMPONENTS = {"Point"}


def _load_contract() -> Spec:
    return json.loads((CONTRACT_DIR / "openapi.yaml").read_text(encoding="utf-8"))


CONTRACT = _load_contract()


@pytest.fixture(scope="module")
def app_spec() -> Spec:
    """The app's generated OpenAPI document (no disk, no settings needed)."""
    app = create_app(library=Library.from_store(InMemoryLibrary()), today=lambda: TODAY)
    return app.openapi()


# --- Helpers ----------------------------------------------------------------------------------


def _resolve(spec: Spec, node: Any) -> Any:
    while isinstance(node, dict) and "$ref" in node:
        target: Any = spec
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        node = target
    return node


def _operations(spec: Spec) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (method.upper(), path): operation
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    }


def _non_null(schema: dict[str, Any]) -> dict[str, Any]:
    """The non-null branch of an `anyOf: [X, null]`, or the schema itself."""
    branches = [b for b in schema.get("anyOf", []) if b.get("type") != "null"]
    return branches[0] if len(branches) == 1 else schema


def _types(spec: Spec, schema: dict[str, Any]) -> frozenset[str]:
    """A schema's type, normalised: object refs by name, arrays as array<item types>."""
    if "$ref" in schema:
        target = _resolve(spec, schema)
        if target.get("type") == "object":
            return frozenset({schema["$ref"].rsplit("/", 1)[-1]})
        return _types(spec, target)
    if "anyOf" in schema:
        return frozenset().union(*(_types(spec, branch) for branch in schema["anyOf"]))
    declared = schema.get("type")
    names = set(declared) if isinstance(declared, list) else {declared} if declared else set()
    if "array" in names:
        items = schema.get("prefixItems") or [schema.get("items", {})]
        item_types = frozenset().union(*(_types(spec, item) for item in items))
        names.discard("array")
        names.add(f"array<{'|'.join(sorted(item_types))}>")
    return frozenset(names)


def _enum(schema: dict[str, Any]) -> frozenset[Any] | None:
    schema = _non_null(schema)
    if "enum" in schema:
        return frozenset(schema["enum"])
    if "const" in schema:
        return frozenset({schema["const"]})
    return None


def _content_shapes(spec: Spec, holder: dict[str, Any]) -> dict[str, frozenset[str]]:
    content = _resolve(spec, holder).get("content", {})
    return {media: _types(spec, entry.get("schema", {})) for media, entry in content.items()}


# --- The checks, each returning the differences it finds -------------------------------------


def operation_differences(app: Spec, contract: Spec) -> list[str]:
    """(a) The same (method, path) operations, with the same operationIds."""
    app_ops, contract_ops = _operations(app), _operations(contract)
    problems = [f"missing from the app: {op}" for op in sorted(contract_ops.keys() - app_ops)]
    problems += [f"not in the contract: {op}" for op in sorted(app_ops.keys() - contract_ops)]
    for key in sorted(app_ops.keys() & contract_ops.keys()):
        app_id, contract_id = app_ops[key].get("operationId"), contract_ops[key]["operationId"]
        if app_id != contract_id:
            problems.append(f"{key}: operationId {app_id!r} != {contract_id!r}")
    return problems


def status_code_differences(app: Spec, contract: Spec) -> list[str]:
    """(b) Per operation, the same set of response status codes and response bodies."""
    app_ops, contract_ops = _operations(app), _operations(contract)
    problems = []
    for key in sorted(app_ops.keys() & contract_ops.keys()):
        app_responses, contract_responses = (
            app_ops[key]["responses"],
            contract_ops[key]["responses"],
        )
        if set(app_responses) != set(contract_responses):
            problems.append(
                f"{key}: statuses {sorted(app_responses)} != {sorted(contract_responses)}"
            )
            continue
        for status in sorted(contract_responses):
            app_shape = _content_shapes(app, app_responses[status])
            contract_shape = _content_shapes(contract, contract_responses[status])
            if app_shape != contract_shape:
                problems.append(f"{key} {status}: body {app_shape} != {contract_shape}")
    return problems


def parameter_differences(app: Spec, contract: Spec) -> list[str]:
    """The same parameters (name, place, required) with the same type rules."""
    app_ops, contract_ops = _operations(app), _operations(contract)
    problems = []
    for key in sorted(app_ops.keys() & contract_ops.keys()):

        def params(spec: Spec, operation: dict[str, Any]) -> dict[tuple[str, str], Any]:
            resolved = (_resolve(spec, p) for p in operation.get("parameters", []))
            return {(p["name"], p["in"]): p for p in resolved}

        app_params, contract_params = params(app, app_ops[key]), params(contract, contract_ops[key])
        if set(app_params) != set(contract_params):
            problems.append(f"{key}: parameters {sorted(app_params)} != {sorted(contract_params)}")
            continue
        for name, contract_param in contract_params.items():
            app_param = app_params[name]
            if app_param.get("required", False) != contract_param.get("required", False):
                problems.append(f"{key} {name}: required differs")
            app_schema = _non_null(app_param["schema"])
            for rule in CONSTRAINT_KEYS:
                if contract_param["schema"].get(rule) != app_schema.get(rule):
                    problems.append(f"{key} {name}: {rule} differs")
    return problems


def request_body_differences(app: Spec, contract: Spec) -> list[str]:
    """The same request bodies: media types, schemas and whether they are required."""
    app_ops, contract_ops = _operations(app), _operations(contract)
    problems = []
    for key in sorted(app_ops.keys() & contract_ops.keys()):
        app_body, contract_body = (
            app_ops[key].get("requestBody"),
            contract_ops[key].get("requestBody"),
        )
        if (app_body is None) != (contract_body is None):
            problems.append(f"{key}: request body present in only one document")
            continue
        if app_body is None:
            continue
        if bool(app_body.get("required")) != bool(contract_body.get("required")):
            problems.append(f"{key}: request body required differs")
        if _content_shapes(app, app_body) != _content_shapes(contract, contract_body):
            problems.append(f"{key}: request body schema differs")
    return problems


def schema_differences(app: Spec, contract: Spec) -> list[str]:
    """(c) Every contract schema but Point exists in the app with the same properties.

    Same property names, the same required list, the same types (a contract
    ["string", "null"] equals the app's anyOf [string, null]), the same enums and the
    same constraints (lengths, ranges, patterns, formats). The app has no extra schemas.
    """
    app_schemas = app.get("components", {}).get("schemas", {})
    contract_schemas = contract["components"]["schemas"]
    expected = set(contract_schemas) - SCHEMAS_NOT_COMPONENTS
    problems = [
        f"schema missing from the app: {name}" for name in sorted(expected - set(app_schemas))
    ]
    problems += [
        f"schema not in the contract: {name}" for name in sorted(set(app_schemas) - expected)
    ]
    for name in sorted(expected & set(app_schemas)):
        app_schema, contract_schema = app_schemas[name], contract_schemas[name]
        app_props, contract_props = app_schema.get("properties", {}), contract_schema["properties"]
        if set(app_props) != set(contract_props):
            problems.append(f"{name}: properties {sorted(app_props)} != {sorted(contract_props)}")
            continue
        if sorted(app_schema.get("required", [])) != sorted(contract_schema.get("required", [])):
            problems.append(f"{name}: required {app_schema.get('required')} differs")
        for prop, contract_prop in contract_props.items():
            app_prop = app_props[prop]
            if _types(app, app_prop) != _types(contract, contract_prop):
                problems.append(f"{name}.{prop}: type differs")
            if _enum(contract_prop) is not None and _enum(app_prop) != _enum(contract_prop):
                problems.append(f"{name}.{prop}: enum differs")
            for rule in CONSTRAINT_KEYS:
                if rule in contract_prop and _non_null(app_prop).get(rule) != contract_prop[rule]:
                    problems.append(f"{name}.{prop}: {rule} differs")
    return problems


def upload_form_differences(app: Spec, contract: Spec) -> list[str]:
    """(d) The multipart upload form has the same fields, required list and rules."""

    def form(spec: Spec) -> dict[str, Any]:
        body = spec["paths"]["/api/recordings"]["post"]["requestBody"]
        return body["content"]["multipart/form-data"]["schema"]

    app_form, contract_form = form(app), form(contract)
    problems = []
    if set(app_form["properties"]) != set(contract_form["properties"]):
        problems.append(f"upload fields {sorted(app_form['properties'])} differ")
    if sorted(app_form.get("required", [])) != sorted(contract_form.get("required", [])):
        problems.append("upload required fields differ")
    for name, contract_field in contract_form["properties"].items():
        if app_form["properties"].get(name) != contract_field:
            problems.append(f"upload field {name} differs")
    return problems


ALL_CHECKS = (
    operation_differences,
    status_code_differences,
    parameter_differences,
    request_body_differences,
    schema_differences,
    upload_form_differences,
)


# --- The tests --------------------------------------------------------------------------------


def test_the_contract_has_the_twenty_two_operations_the_api_serves() -> None:
    assert len(_operations(CONTRACT)) == 22
    assert _operations(CONTRACT)[("GET", "/api/clips/{id}/snapshot")]["operationId"] == (
        "getClipSnapshot"
    )
    assert _operations(CONTRACT)[("POST", "/api/recordings/{id}/index")]["operationId"] == (
        "indexRecording"
    )


def test_the_app_serves_the_contracts_version(app_spec: Spec) -> None:
    assert CONTRACT["info"]["version"] == "1.4.0"
    assert app_spec["info"]["version"] == API_VERSION == CONTRACT["info"]["version"]


@pytest.mark.parametrize("check", ALL_CHECKS, ids=lambda check: check.__name__)
def test_the_app_matches_the_contract(check: Any, app_spec: Spec) -> None:
    assert check(app_spec, CONTRACT) == []


def test_upload_form_has_file_day_and_camera(app_spec: Spec) -> None:
    body = app_spec["paths"]["/api/recordings"]["post"]["requestBody"]
    form = body["content"]["multipart/form-data"]["schema"]
    assert set(form["properties"]) == {"file", "day", "camera"}
    assert sorted(form["required"]) == ["camera", "day", "file"]


def _property_names(node: Any) -> set[str]:
    """Every property name anywhere inside a schema."""
    found: set[str] = set()
    if isinstance(node, dict):
        found.update(node.get("properties", {}))
        for value in node.values():
            found |= _property_names(value)
    elif isinstance(node, list):
        for value in node:
            found |= _property_names(value)
    return found


def test_the_password_is_write_only_and_in_no_other_schema(app_spec: Spec) -> None:
    schemas_by_name = app_spec["components"]["schemas"]
    assert schemas_by_name["CameraCreate"]["properties"]["password"]["writeOnly"] is True
    others = {name: schema for name, schema in schemas_by_name.items() if name != "CameraCreate"}
    assert not {name for name in _property_names(others) if "pass" in name.lower()}
    assert not {name for name in _property_names(app_spec["paths"]) if "pass" in name.lower()}


def test_camera_ids_in_a_camera_follow_the_contracts_pattern(app_spec: Spec) -> None:
    camera = app_spec["components"]["schemas"]["Camera"]
    assert camera["properties"]["id"]["pattern"] == "^CAM-[0-9]{3,}$"


def test_the_app_never_adds_fastapis_own_validation_schemas(app_spec: Spec) -> None:
    assert "HTTPValidationError" not in app_spec["components"]["schemas"]
    assert "ValidationError" not in app_spec["components"]["schemas"]


def test_the_index_operation_has_no_body_and_answers_202_with_index_accepted(
    app_spec: Spec,
) -> None:
    operation = app_spec["paths"]["/api/recordings/{id}/index"]["post"]
    assert "requestBody" not in operation
    accepted = operation["responses"]["202"]["content"]["application/json"]["schema"]
    assert accepted == {"$ref": "#/components/schemas/IndexAccepted"}
    assert set(operation["responses"]) == {"202", "404", "409", "422", "500", "503"}


def test_the_api_document_is_served_under_api(client: Any) -> None:
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    assert operation_differences(response.json(), CONTRACT) == []


# --- The checks notice drift --------------------------------------------------------------------


def _drifted(app_spec: Spec, change: Any) -> Spec:
    spec = copy.deepcopy(app_spec)
    change(spec)
    return spec


@pytest.mark.parametrize(
    ("check", "change"),
    [
        (operation_differences, lambda s: s["paths"]["/api/status"].pop("get")),
        (operation_differences, lambda s: s["paths"]["/api/status"].update(post={})),
        (
            operation_differences,
            lambda s: s["paths"]["/api/clips/{id}"]["get"].update(operationId="fetchClip"),
        ),
        (
            status_code_differences,
            lambda s: s["paths"]["/api/zones"]["post"]["responses"].pop("409"),
        ),
        (
            status_code_differences,
            lambda s: s["paths"]["/api/clips/{id}"]["get"]["responses"]["200"]["content"][
                "application/json"
            ].update(schema={"$ref": "#/components/schemas/Zone"}),
        ),
        (
            parameter_differences,
            lambda s: s["paths"]["/api/days"]["get"]["parameters"][0].update(required=True),
        ),
        (
            schema_differences,
            lambda s: s["components"]["schemas"]["Clip"]["properties"].pop("zone"),
        ),
        (
            schema_differences,
            lambda s: s["components"]["schemas"]["SavedClipCreate"].update(
                required=["clipId", "note"]
            ),
        ),
        (
            schema_differences,
            lambda s: s["components"]["schemas"]["SearchRequest"]["properties"]["question"].update(
                maxLength=500
            ),
        ),
        (
            schema_differences,
            lambda s: s["components"]["schemas"]["Evidence"]["properties"]["kind"].update(
                enum=["carrying"]
            ),
        ),
        (schema_differences, lambda s: s["components"]["schemas"].update(Extra={})),
        (
            upload_form_differences,
            lambda s: s["paths"]["/api/recordings"]["post"]["requestBody"]["content"][
                "multipart/form-data"
            ]["schema"]["properties"].pop("camera"),
        ),
        (
            request_body_differences,
            lambda s: s["paths"]["/api/search"]["post"].pop("requestBody"),
        ),
        (
            status_code_differences,
            lambda s: s["paths"]["/api/cameras"]["post"]["responses"].pop("409"),
        ),
        (
            operation_differences,
            lambda s: s["paths"]["/api/cameras/{id}"]["patch"].update(operationId="setCamera"),
        ),
        (
            schema_differences,
            lambda s: s["components"]["schemas"]["CameraCreate"]["properties"]["ip"].update(
                pattern="^.*$"
            ),
        ),
        (
            schema_differences,
            lambda s: s["components"]["schemas"]["CameraCreate"]["properties"][
                "acknowledgeCost"
            ].update(const=False),
        ),
        (
            schema_differences,
            lambda s: s["components"]["schemas"]["Camera"]["properties"].update(
                password={"type": "string"}
            ),
        ),
        (
            schema_differences,
            lambda s: s["components"]["schemas"]["SearchRequest"].update(
                required=["question", "day", "camera"]
            ),
        ),
        (
            upload_form_differences,
            lambda s: s["paths"]["/api/recordings"]["post"]["requestBody"]["content"][
                "multipart/form-data"
            ]["schema"].update(required=["file", "day"]),
        ),
        (
            status_code_differences,
            lambda s: s["paths"]["/api/recordings/{id}/index"]["post"]["responses"].pop("503"),
        ),
        (
            schema_differences,
            lambda s: s["components"]["schemas"]["IndexAccepted"]["properties"]["status"].update(
                enum=["waiting"]
            ),
        ),
        (
            request_body_differences,
            lambda s: s["paths"]["/api/recordings/{id}/index"]["post"].update(
                requestBody={"content": {"application/json": {"schema": {"type": "object"}}}}
            ),
        ),
    ],
)
def test_each_check_reports_drift(check: Any, change: Any, app_spec: Spec) -> None:
    assert check(_drifted(app_spec, change), CONTRACT) != []


# --- The contract's examples fit the API's models ----------------------------------------------


@pytest.mark.parametrize(
    ("example", "model"),
    [
        ("status.json", schemas.Status),
        ("cameras.json", list[schemas.Camera]),
        ("camera.json", schemas.Camera),
        ("days.json", list[schemas.DaySummary]),
        ("recordings.json", list[schemas.Recording]),
        ("recording-accepted.json", schemas.RecordingAccepted),
        ("index-accepted.json", schemas.IndexAccepted),
        ("index-not-configured.json", schemas.Error),
        ("clip-detail.json", schemas.Clip),
        ("search-response.json", schemas.SearchResponse),
        ("zones.json", list[schemas.Zone]),
        ("saved-clips.json", list[schemas.SavedClip]),
        ("error.json", schemas.Error),
    ],
)
def test_each_example_round_trips_through_its_model(example: str, model: Any) -> None:
    data = load_example(example)
    adapter: TypeAdapter[Any] = TypeAdapter(model)
    parsed = adapter.validate_python(data)
    assert adapter.dump_python(parsed, mode="json", by_alias=True) == data
    if isinstance(parsed, BaseModel):
        assert parsed.model_dump(mode="json") == data
