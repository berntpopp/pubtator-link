from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def extract_validation_details(
    parameters: Mapping[str, Any],
    validation_errors: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract compact retry guidance from an MCP tool parameter schema."""
    properties = _schema_properties(parameters)
    details: dict[str, Any] = {
        "valid_params": sorted(properties),
    }

    valid_values_for = {
        name: values for name, schema in properties.items() if (values := _enum_values(schema))
    }
    if valid_values_for:
        details["valid_values_for"] = dict(sorted(valid_values_for.items()))

    missing_params, unexpected_params = _params_from_errors(validation_errors)
    if missing_params:
        details["missing_params"] = missing_params
    if unexpected_params:
        details["unexpected_params"] = unexpected_params
    return details


def _schema_properties(parameters: Mapping[str, Any]) -> Mapping[str, Any]:
    properties = parameters.get("properties")
    if isinstance(properties, Mapping):
        return properties
    nested = parameters.get("parameters")
    if isinstance(nested, Mapping):
        nested_properties = nested.get("properties")
        if isinstance(nested_properties, Mapping):
            return nested_properties
    return {}


def _enum_values(schema: Any) -> list[Any]:
    if not isinstance(schema, Mapping):
        return []

    values: list[Any] = []
    enum = schema.get("enum")
    if isinstance(enum, list):
        _extend_unique(values, enum)
    if "const" in schema:
        _extend_unique(values, [schema["const"]])

    for nested_key in ("anyOf", "oneOf"):
        nested_schemas = schema.get(nested_key)
        if isinstance(nested_schemas, list):
            for nested_schema in nested_schemas:
                _extend_unique(values, _enum_values(nested_schema))
    return values


def _params_from_errors(
    validation_errors: Iterable[Mapping[str, Any]] | None,
) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    unexpected: list[str] = []
    for error in validation_errors or ():
        field = _field_from_error(error)
        if field is None:
            continue
        error_type = str(error.get("type", ""))
        if error_type in {
            "missing",
            "missing_argument",
            "missing_keyword_only_argument",
            "missing_positional_only_argument",
        }:
            _append_unique(missing, field)
        elif error_type == "unexpected_keyword_argument":
            _append_unique(unexpected, field)
    return sorted(missing), sorted(unexpected)


def _field_from_error(error: Mapping[str, Any]) -> str | None:
    location = error.get("loc")
    if isinstance(location, tuple | list) and location:
        field = location[0]
        if isinstance(field, str) and field:
            return field
    return None


def _extend_unique(values: list[Any], additions: Iterable[Any]) -> None:
    for value in additions:
        if value not in values:
            values.append(value)


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
