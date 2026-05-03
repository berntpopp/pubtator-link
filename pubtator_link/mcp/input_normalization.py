from __future__ import annotations

from typing import Any


class InputNormalizationError(ValueError):
    def __init__(self, field_errors: list[dict[str, str]], recovery_hint: str) -> None:
        super().__init__("invalid MCP arguments")
        self.field_errors = field_errors
        self.recovery_hint = recovery_hint


def _warning(field: str, normalized_to: str, message: str) -> dict[str, str]:
    return {"field": field, "normalized_to": normalized_to, "message": message}


def _field_error(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def _normalize_alias(
    normalized: dict[str, Any],
    warnings: list[dict[str, str]],
    *,
    target: str,
    aliases: tuple[str, ...],
) -> list[dict[str, str]]:
    present_aliases = [
        alias for alias in aliases if alias in normalized and normalized[alias] is not None
    ]
    if not present_aliases:
        return []
    present_targets = [target] if target in normalized and normalized[target] is not None else []
    if len(present_aliases) + len(present_targets) > 1:
        fields = ", ".join([*present_targets, *present_aliases])
        return [_field_error(target, f"Ambiguous arguments: provide only one of {fields}.")]

    alias = present_aliases[0]
    normalized[target] = normalized.pop(alias)
    warnings.append(
        _warning(alias, target, f"Normalized '{alias}' alias to '{target}'."),
    )
    return []


def _normalize_singleton_lists(
    normalized: dict[str, Any],
    warnings: list[dict[str, str]],
    fields: tuple[str, ...],
) -> None:
    for field in fields:
        if isinstance(normalized.get(field), str):
            normalized[field] = [normalized[field]]
            warnings.append(
                _warning(field, field, f"Normalized string '{field}' to a one-item list."),
            )


def _normalize_enum_casing(
    normalized: dict[str, Any],
    warnings: list[dict[str, str]],
    *,
    field: str,
    allowed_values: set[str],
) -> list[dict[str, str]]:
    value = normalized.get(field)
    if not isinstance(value, str):
        return []
    lowered = value.lower()
    if lowered not in allowed_values:
        return [
            _field_error(
                field,
                f"Unsupported value '{value}'. Expected one of {', '.join(sorted(allowed_values))}.",
            )
        ]
    if lowered == value:
        return []
    normalized[field] = lowered
    warnings.append(_warning(field, field, f"Normalized '{field}' enum casing."))
    return []


def normalize_retrieve_review_context_batch_args(
    args: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    normalized = dict(args)
    warnings: list[dict[str, str]] = []
    field_errors: list[dict[str, str]] = []

    field_errors.extend(
        _normalize_alias(normalized, warnings, target="queries", aliases=("query", "question"))
    )
    field_errors.extend(
        _normalize_alias(
            normalized, warnings, target="max_total_passages", aliases=("limit", "size")
        )
    )
    _normalize_singleton_lists(
        normalized,
        warnings,
        ("queries", "pmids", "entity_ids", "sections", "prioritize_pmids"),
    )
    field_errors.extend(
        _normalize_enum_casing(
            normalized,
            warnings,
            field="response_mode",
            allowed_values={"compact", "merged_only", "full", "diagnostics", "quotes"},
        )
    )
    field_errors.extend(
        _normalize_enum_casing(
            normalized,
            warnings,
            field="budget_strategy",
            allowed_values={"query_fair", "source_fair", "scarcity_first"},
        )
    )
    field_errors.extend(
        _normalize_enum_casing(
            normalized,
            warnings,
            field="table_mode",
            allowed_values={"off", "preview", "full"},
        )
    )
    field_errors.extend(
        _normalize_enum_casing(
            normalized,
            warnings,
            field="section_policy",
            allowed_values={"evidence_first", "original_order"},
        )
    )

    if field_errors:
        raise InputNormalizationError(
            field_errors=field_errors,
            recovery_hint="Provide one canonical MCP argument per field and use documented enum values.",
        )
    return normalized, warnings


def attach_normalization_meta(
    result: dict[str, Any],
    warnings: list[dict[str, str]],
) -> dict[str, Any]:
    if warnings:
        meta = result.setdefault("_meta", {})
        meta["normalized_arguments"] = warnings
    return result
