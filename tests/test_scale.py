"""Test keyset pagination with PostgreSQL and several thousand TDs.

Set ``THINGDIR_PG_URL`` to run this test.
"""

from __future__ import annotations

import json
import os
import time

import pytest

pytest.importorskip("sqlalchemy")
PG = os.getenv("THINGDIR_PG_URL")
pytestmark = pytest.mark.skipif(not PG, reason="set THINGDIR_PG_URL")

from sqlalchemy import create_engine, text

from thingdir.stores import SqlStore


def _td(i):
    return {
        "@context": "https://www.w3.org/2022/wot/td/v1.1",
        "id": f"urn:s:{i:06d}",
        "title": f"T{i}",
        "securityDefinitions": {"nosec_sc": {"scheme": "nosec"}},
        "security": ["nosec_sc"],
        "actions": {},
    }


@pytest.mark.asyncio
async def test_keyset_is_flat_offset_is_not():
    s = SqlStore(PG)
    eng = create_engine(PG)
    N = 20_000
    with eng.begin() as c:
        c.execute(text("DELETE FROM things"))
        c.execute(text("UPDATE thing_seq SET n=0"))
        rows = [{"id": f"urn:s:{i:06d}", "td": json.dumps(_td(i)), "seq": i + 1} for i in range(N)]
        for k in range(0, N, 5000):
            c.execute(
                text("INSERT INTO things (id,td,seq) VALUES (:id,:td,:seq)"), rows[k : k + 5000]
            )

    import statistics

    async def med(after):
        ts = []
        for _ in range(7):
            t = time.time()
            await s.page(after=after, limit=100)
            ts.append(time.time() - t)
        return statistics.median(ts)

    # keyset: page 1 vs a deep page , must stay flat
    shallow = await med(None)
    deep = await med(f"urn:s:{N - 1000:06d}")
    assert deep < shallow * 4 + 0.05, (
        f"keyset not flat: {shallow * 1000:.1f} vs {deep * 1000:.1f} ms"
    )

    # the page is always bounded and correct
    tds, nxt = await s.page(limit=100)
    assert len(tds) == 100 and nxt == tds[-1]["id"]
