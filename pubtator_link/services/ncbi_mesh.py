from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

from pubtator_link.models.discovery import MeshDescriptor

QueryParams = dict[str, str]
GetPath = Callable[[str, QueryParams], Awaitable[httpx.Response]]


async def lookup_mesh_descriptors(
    *,
    get: GetPath,
    query: str,
    limit: int,
    exact: bool,
) -> list[MeshDescriptor]:
    term = f'"{query}"[MeSH Terms]' if exact else query
    search_response = await get(
        "esearch.fcgi",
        {
            "db": "mesh",
            "term": term,
            "retmode": "json",
            "retmax": str(limit),
            "tool": "pubtator-link",
        },
    )
    search_payload = search_response.json()
    if not isinstance(search_payload, dict):
        return []

    idlist = _mesh_ids(search_payload)
    if not idlist:
        return []

    summary_payload = search_payload
    if "result" not in summary_payload:
        summary_response = await get(
            "esummary.fcgi",
            {
                "db": "mesh",
                "id": ",".join(idlist),
                "retmode": "json",
                "tool": "pubtator-link",
            },
        )
        summary_json = summary_response.json()
        summary_payload = summary_json if isinstance(summary_json, dict) else {}

    result_payload = summary_payload.get("result")
    results = result_payload if isinstance(result_payload, dict) else {}
    descriptors: list[MeshDescriptor] = []
    for mesh_id in idlist:
        item = results.get(mesh_id)
        if not isinstance(item, dict):
            continue
        descriptors.append(_mesh_descriptor(mesh_id, item))
    return descriptors


def _mesh_ids(payload: dict[str, object]) -> list[str]:
    esearch_result = payload.get("esearchresult")
    idlist_payload = esearch_result.get("idlist", []) if isinstance(esearch_result, dict) else []
    return [str(mesh_id) for mesh_id in idlist_payload]


def _mesh_descriptor(mesh_id: str, item: dict[str, object]) -> MeshDescriptor:
    uid = _optional_str(item.get("uid")) or mesh_id
    mesh_terms = _string_list(item.get("ds_meshterms"))
    name = mesh_terms[0] if mesh_terms else _optional_str(item.get("title")) or uid
    return MeshDescriptor(
        ui=_optional_str(item.get("ds_meshui")) or uid,
        name=name,
        scope_note=_optional_str(item.get("ds_scopenote")),
        entry_terms=mesh_terms[1:],
        tree_numbers=_mesh_tree_numbers(item),
        search_terms=[f"{name}[MeSH Terms]"],
    )


def _mesh_tree_numbers(item: dict[str, object]) -> list[str]:
    values = item.get("ds_treenumbers") or item.get("ds_tree")
    if isinstance(values, list | tuple):
        tree_numbers = [str(value) for value in values if str(value).strip()]
        if tree_numbers:
            return tree_numbers
    idx_links = item.get("ds_idxlinks")
    if isinstance(idx_links, list | tuple):
        return [
            str(link.get("treenum"))
            for link in idx_links
            if isinstance(link, dict) and str(link.get("treenum") or "").strip()
        ]
    return []


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [str(item) for item in value if str(item).strip()]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
