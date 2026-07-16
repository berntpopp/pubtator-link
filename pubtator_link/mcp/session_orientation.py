from __future__ import annotations

from typing import Any, cast

from pubtator_link.mcp.input_normalization import InputNormalizationError
from pubtator_link.services.research_session import ResearchSessionInputError


async def research_session_status_payload(
    *, service: Any, review_id: str | None, session_id: str
) -> dict[str, Any]:
    try:
        response = await (
            service.get_status(review_id=review_id, session_id=session_id)
            if review_id
            else service.get_status_by_session_id(session_id=session_id)
        )
    except LookupError:
        # Fixed message only; the caller-supplied session_id is never echoed back
        # (it can carry hostile prose / control-code points).
        return {
            "success": False,
            "manifest": None,
            "error_code": "not_found",
            "message": "Research session not found.",
        }
    except ValueError:
        return {
            "success": False,
            "manifest": None,
            "error_code": "invalid_input",
            "message": "Research session request was invalid or ambiguous.",
        }
    return cast(dict[str, Any], response.model_dump(by_alias=True))


async def research_sessions_payload(
    *, service: Any, review_id: str | None, limit: int, cursor: str | None
) -> dict[str, Any]:
    try:
        response = await service.list_sessions(review_id=review_id, limit=limit, cursor=cursor)
    except ResearchSessionInputError:
        field = "cursor" if cursor is not None else "limit"
        raise InputNormalizationError(
            field_errors=[{"field": field, "message": f"Invalid {field} parameter."}],
            recovery_hint=(
                "Request the first page without cursor."
                if cursor is not None
                else "Use a limit between 1 and 20."
            ),
        ) from None
    return cast(dict[str, Any], response.model_dump(by_alias=True))
