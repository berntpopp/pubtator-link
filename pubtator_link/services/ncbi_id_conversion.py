from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence

import httpx

from pubtator_link.models.discovery import ArticleIdConversionRecord, ArticleIdKind

QueryParamValue = str | int | float | bool | None
GetAbsolute = Callable[[str, Mapping[str, QueryParamValue]], Awaitable[httpx.Response]]


async def convert_article_ids_individually(
    *,
    ids: Sequence[str],
    source: ArticleIdKind,
    url: str,
    get_absolute: GetAbsolute,
) -> list[ArticleIdConversionRecord]:
    records: list[ArticleIdConversionRecord] = []
    for article_id in ids:
        params = {"ids": article_id, "format": "json", "tool": "pubtator-link"}
        if source != "auto":
            params["idtype"] = source
        try:
            response = await get_absolute(url, params)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400:
                records.append(
                    ArticleIdConversionRecord(
                        input_id=article_id,
                        input_kind=source,
                        status="failed",
                        reason="upstream_rejected_identifier",
                    )
                )
                continue
            raise
        records.extend(conversion_records_from_response([article_id], source, response))
    return records


def conversion_records_from_response(
    ids: Sequence[str],
    source: ArticleIdKind,
    response: httpx.Response,
) -> list[ArticleIdConversionRecord]:
    payload = response.json()
    records_payload = payload.get("records", []) if isinstance(payload, dict) else []

    records_by_requested_id: dict[str, ArticleIdConversionRecord] = {}
    for item in records_payload:
        if not isinstance(item, dict):
            continue

        pmid = _optional_str(item.get("pmid"))
        pmcid = _optional_str(item.get("pmcid"))
        doi = _optional_str(item.get("doi"))
        requested_id = _optional_str(item.get("requested-id")) or pmcid or pmid or doi
        if requested_id is None:
            continue

        resolved = pmid is not None or pmcid is not None or doi is not None
        records_by_requested_id[requested_id] = ArticleIdConversionRecord(
            input_id=requested_id,
            input_kind=source,
            status="resolved" if resolved else "unresolved",
            pmid=pmid,
            pmcid=pmcid,
            doi=doi,
            reason=None if resolved else "not_found",
        )

    return [
        records_by_requested_id.get(
            requested,
            ArticleIdConversionRecord(
                input_id=requested,
                input_kind=source,
                status="unresolved",
                reason="not_found",
            ),
        )
        for requested in ids
    ]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
