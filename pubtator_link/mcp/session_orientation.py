from __future__ import annotations

from typing import Any, cast


async def research_session_status_payload(
    *, service: Any, review_id: str | None, session_id: str
) -> dict[str, Any]:
    try:
        response = await (
            service.get_status(review_id=review_id, session_id=session_id)
            if review_id
            else service.get_status_by_session_id(session_id=session_id)
        )
    except LookupError as exc:
        return {"success": False, "manifest": None, "error_code": "not_found", "message": str(exc)}
    except ValueError as exc:
        return {
            "success": False,
            "manifest": None,
            "error_code": "validation_failed",
            "message": str(exc),
        }
    return cast(dict[str, Any], response.model_dump(by_alias=True))


async def research_sessions_payload(*, service: Any, review_id: str | None) -> dict[str, Any]:
    response = (
        await service.list_sessions(review_id=review_id)
        if review_id
        else await service.list_sessions_global(limit=20)
    )
    return cast(dict[str, Any], response.model_dump(by_alias=True))
