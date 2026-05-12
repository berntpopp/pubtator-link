from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import asyncpg
from pydantic import BaseModel, ValidationError

from pubtator_link.benchmarks.log_parser import ToolCallEvent
from pubtator_link.benchmarks.models import (
    BenchmarkCase,
    BenchmarkMode,
    BenchmarkScore,
    PredictionJsonPayload,
    PredictionRecord,
    RunManifest,
)


def validate_jsonb(model_type: type[BaseModel], payload: dict[str, Any]) -> dict[str, Any]:
    if "_schema_version" not in payload:
        raise ValidationError.from_exception_data(
            model_type.__name__,
            [{"type": "missing", "loc": ("_schema_version",), "input": payload}],
        )
    validated = model_type.model_validate(payload)
    return validated.model_dump(by_alias=True, mode="json")


def jsonb_payload(model_type: type[BaseModel], payload: BaseModel) -> dict[str, Any]:
    validated = model_type.model_validate(payload.model_dump(by_alias=True))
    return validated.model_dump(
        by_alias=True,
        mode="json",
    )


class BenchmarkStorage:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    async def _connect(self) -> asyncpg.Connection:
        return await asyncpg.connect(self.database_url)

    async def insert_run(self, manifest: RunManifest) -> None:
        conn = await self._connect()
        try:
            await conn.execute(
                """
                insert into benchmark_runs(
                    run_id, suite, dataset, dataset_version, mode, sample_seed,
                    answer_model, prompt_template_hash, prompt_resolved_hash, manifest
                )
                values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)
                on conflict (run_id) do nothing
                """,
                manifest.run_id,
                manifest.suite,
                manifest.dataset,
                manifest.dataset_version,
                manifest.mode.value,
                manifest.sample_seed,
                manifest.model_settings.requested_model,
                manifest.prompt_template_hash,
                manifest.prompt_resolved_hash,
                json.dumps(jsonb_payload(RunManifest, manifest)),
            )
        finally:
            await conn.close()

    async def insert_cases(
        self,
        run_id: str,
        cases: list[BenchmarkCase],
        mode: BenchmarkMode = BenchmarkMode.NO_TOOLS,
    ) -> None:
        conn = await self._connect()
        try:
            for index, case in enumerate(cases):
                await conn.execute(
                    """
                    insert into benchmark_run_cases(run_id, case_id, case_order, prompt_context)
                    values($1,$2,$3,$4::jsonb)
                    on conflict do nothing
                    """,
                    run_id,
                    case.case_id,
                    index,
                    json.dumps(case.to_prompt_context(mode).model_dump(mode="json")),
                )
        finally:
            await conn.close()

    async def insert_predictions(self, run_id: str, predictions: list[PredictionRecord]) -> None:
        conn = await self._connect()
        try:
            for prediction in predictions:
                await conn.execute(
                    """
                    insert into benchmark_predictions(run_id, case_id, prediction)
                    values($1,$2,$3::jsonb)
                    """,
                    run_id,
                    prediction.case_id,
                    json.dumps(
                        jsonb_payload(
                            PredictionJsonPayload,
                            PredictionJsonPayload(prediction=prediction),
                        )
                    ),
                )
        finally:
            await conn.close()

    async def insert_scores(self, run_id: str, scores: BenchmarkScore) -> None:
        conn = await self._connect()
        try:
            await conn.execute(
                """
                insert into benchmark_scores(run_id, dataset, scores)
                values($1,$2,$3::jsonb)
                """,
                run_id,
                scores.dataset,
                json.dumps(jsonb_payload(BenchmarkScore, scores)),
            )
        finally:
            await conn.close()

    async def insert_log_events(self, run_id: str, events: Sequence[Mapping[str, Any]]) -> None:
        if not events:
            return
        conn = await self._connect()
        try:
            for event in events:
                event_type = str(event.get("event_type") or event.get("type") or "event")
                tool_name_value = event.get("tool_name") or event.get("name")
                tool_name = str(tool_name_value) if tool_name_value is not None else None
                await conn.execute(
                    """
                    insert into benchmark_log_events(run_id, event_type, tool_name, payload)
                    values($1,$2,$3,$4::jsonb)
                    """,
                    run_id,
                    event_type,
                    tool_name,
                    json.dumps(event, sort_keys=True),
                )
        finally:
            await conn.close()

    async def insert_tool_calls(self, run_id: str, tool_calls: list[ToolCallEvent]) -> None:
        if not tool_calls:
            return
        conn = await self._connect()
        try:
            for tool_call in tool_calls:
                await conn.execute(
                    """
                    insert into benchmark_tool_calls(run_id, tool_name, status, payload)
                    values($1,$2,$3,$4::jsonb)
                    """,
                    run_id,
                    tool_call.tool_name,
                    tool_call.status or "unknown",
                    json.dumps(tool_call.model_dump(mode="json"), sort_keys=True),
                )
        finally:
            await conn.close()

    async def count_predictions(self, run_id: str) -> int:
        conn = await self._connect()
        try:
            return int(
                await conn.fetchval(
                    "select count(*) from benchmark_predictions where run_id = $1",
                    run_id,
                )
            )
        finally:
            await conn.close()
