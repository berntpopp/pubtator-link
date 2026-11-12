from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from contextvars import ContextVar
from typing import Any

# Declared parameter names of the tool currently executing; set by the egress wrapper so a
# service-layer ``ValueError`` can be mapped back onto the argument(s) it is about (D4).
CURRENT_TOOL_PARAMS: ContextVar[frozenset[str]] = ContextVar(
    "pubtator_current_tool_params", default=frozenset()
)

_MISSING_TYPES = frozenset(
    {
        "missing",
        "missing_argument",
        "missing_keyword_only_argument",
        "missing_positional_only_argument",
    }
)
# pydantic error types whose ``msg`` can embed the caller's input (custom validator text,
# discriminator tags): replaced by a fixed reason so no caller value is reflected.
_INPUT_ECHOING_TYPES = frozenset(
    {"value_error", "assertion_error", "union_tag_invalid", "union_tag_not_found"}
)
_INVALID_VALUE = "invalid value; check this parameter's constraints in the input schema."
_CONFLICTING_VALUES = (
    "conflicts with {others} (e.g. a minimum above its maximum, or mutually exclusive "
    "arguments); check their descriptions in the input schema."
)


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


def tool_param_names(parameters: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(_schema_properties(parameters))


def pydantic_field_errors(errors: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """One ``field_errors`` entry per offending argument, for EVERY pydantic error type.

    Type, constraint and union failures are named too, not only missing/unexpected ones.
    """
    field_errors: list[dict[str, str]] = []
    seen: set[str] = set()
    for error in errors:
        field = _field_from_error(error) or "arguments"
        if field in seen:  # a union reports one error per branch; name the field once
            continue
        seen.add(field)
        error_type = str(error.get("type", ""))
        if error_type in _MISSING_TYPES:
            reason = "required parameter is missing"
        elif error_type == "unexpected_keyword_argument":
            reason = "argument is not accepted by this tool"
        elif error_type in _INPUT_ECHOING_TYPES:
            reason = _INVALID_VALUE
        else:
            reason = str(error.get("msg") or _INVALID_VALUE)
        field_errors.append({"field": field, "reason": reason})
    return field_errors


def message_field_errors(message: str, params: Collection[str]) -> list[dict[str, str]]:
    """Name the declared parameters a server-side ``ValueError`` message refers to.

    Only declared (server-authored) names are emitted and the reason is fixed text, so the
    message itself -- which may interpolate a caller value -- never reaches the wire. A message
    naming no parameter is a server-side fault, not an argument error: return ``[]``.
    """
    tokens = dict.fromkeys(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", message))
    fields = [token for token in tokens if token in params]
    if len(fields) == 1:
        return [{"field": fields[0], "reason": _INVALID_VALUE}]
    return [
        {
            "field": field,
            "reason": _CONFLICTING_VALUES.format(others=", ".join(f for f in fields if f != field)),
        }
        for field in fields
    ]


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
        if error_type in _MISSING_TYPES:
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
