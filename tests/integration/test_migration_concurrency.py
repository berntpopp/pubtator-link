"""Migration runner must be safe under concurrent invocation."""

from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest

from pubtator_link.db.migrate import apply_migrations


@pytest.mark.asyncio
@pytest.mark.integration
async def test_parallel_apply_migrations_applies_each_file_exactly_once() -> None:
    dsn = os.environ.get("PUBTATOR_LINK_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("PUBTATOR_LINK_TEST_DATABASE_URL not set")

    if "test" not in dsn.lower() and not os.environ.get("PUBTATOR_LINK_ALLOW_DESTRUCTIVE_TEST"):
        pytest.skip(
            "refusing to DROP SCHEMA on a DSN that does not contain 'test' "
            "(set PUBTATOR_LINK_ALLOW_DESTRUCTIVE_TEST=1 to override)"
        )

    boot = await asyncpg.connect(dsn)
    try:
        await boot.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        await boot.close()

    results = await asyncio.gather(
        apply_migrations(dsn),
        apply_migrations(dsn),
        apply_migrations(dsn),
        apply_migrations(dsn),
    )

    flat = sorted(version for batch in results for version in batch)
    deduped = sorted(set(flat))
    assert flat == deduped, f"a migration was applied by more than one worker: {flat!r}"

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch("select version from schema_migrations order by version")
    finally:
        await conn.close()
    applied = [row["version"] for row in rows]
    assert applied == deduped, "schema_migrations diverges from apply_migrations returns"
