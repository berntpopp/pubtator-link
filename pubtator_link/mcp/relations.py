from __future__ import annotations

import json
from typing import Any, Literal

from pubtator_link.models.responses import RelatedEntity, RelationsResponse

RelationResponseMode = Literal["compact", "standard", "full"]


def shape_entity_relations(
    *,
    entity_id: str,
    api_results: list[dict[str, Any]],
    relation_type: str | None,
    target_entity_type: str | None,
    limit: int,
    response_mode: RelationResponseMode,
    max_response_chars: int,
) -> dict[str, Any]:
    incident_entities = [
        related
        for item in api_results
        if (
            related := _related_entity(item, query_entity_id=entity_id, response_mode=response_mode)
        )
        is not None
    ]
    related_entities = incident_entities[:limit]
    response_size_class: str = response_mode
    omitted_count = max(0, len(incident_entities) - len(related_entities))
    while related_entities:
        projected = _relations_response(
            entity_id=entity_id,
            related_entities=related_entities,
            total_relations=len(incident_entities),
            relation_type=relation_type,
            target_entity_type=target_entity_type,
            omitted_count=omitted_count,
            response_size_class=response_size_class,
        ).model_dump()
        if len(json.dumps(projected, separators=(",", ":"), default=str)) <= max_response_chars:
            break
        omitted_count += 1
        related_entities.pop()
        response_size_class = "truncated"
    return _relations_response(
        entity_id=entity_id,
        related_entities=related_entities,
        total_relations=len(incident_entities),
        relation_type=relation_type,
        target_entity_type=target_entity_type,
        omitted_count=omitted_count,
        response_size_class=response_size_class,
    ).model_dump()


def _related_entity(
    item: dict[str, Any], *, query_entity_id: str, response_mode: RelationResponseMode
) -> RelatedEntity | None:
    source = str(item.get("source") or "")
    target = str(item.get("target") or "")
    if source == query_entity_id and target and target != query_entity_id:
        related = target
    elif target == query_entity_id and source and source != query_entity_id:
        related = source
    else:
        return None
    return RelatedEntity(
        entity_id=related,
        entity_name=item.get("entity_name") or item.get("name"),
        entity_type=item.get("entity_type") or item.get("type_name"),
        relation_type=str(item.get("type") or ""),
        confidence=item.get("confidence"),
        pmids=[] if response_mode == "compact" else list(item.get("pmids") or []),
        source=source,
        target=target,
        publications=item.get("publications"),
    )


def _relations_response(
    *,
    entity_id: str,
    related_entities: list[RelatedEntity],
    total_relations: int,
    relation_type: str | None,
    target_entity_type: str | None,
    omitted_count: int,
    response_size_class: str,
) -> RelationsResponse:
    return RelationsResponse(
        success=True,
        primary_entity=entity_id,
        related_entities=related_entities,
        total_relations=total_relations,
        relation_filter=relation_type,
        entity_filter=target_entity_type,
        omitted_count=omitted_count,
        response_size_class=response_size_class,
    )
