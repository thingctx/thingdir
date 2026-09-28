"""Test that SQL operations behave consistently across database engines.

SQLite always runs. Set these environment variables to test other engines:

    THINGDIR_PG_URL=postgresql+psycopg://...
    THINGDIR_MSSQL_URL=mssql+pyodbc://...
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import text

from thingdir.stores import SqlStore


def _td(tid, title="T", **e):
    return {
        "@context": "https://www.w3.org/2022/wot/td/v1.1",
        "id": tid,
        "title": title,
        "securityDefinitions": {"nosec_sc": {"scheme": "nosec"}},
        "security": ["nosec_sc"],
        "actions": {},
        **e,
    }


def _engines(tmp_path):
    urls = [("sqlite", f"sqlite:///{tmp_path / 't.db'}")]
    if os.getenv("THINGDIR_PG_URL"):
        urls.append(("postgres", os.environ["THINGDIR_PG_URL"]))
    if os.getenv("THINGDIR_MSSQL_URL"):
        urls.append(("mssql", os.environ["THINGDIR_MSSQL_URL"]))
    return urls


@pytest.mark.asyncio
async def test_same_behaviour_on_every_engine(tmp_path):
    for label, url in _engines(tmp_path):
        s = SqlStore(url)
        # clean slate
        with s._engine.begin() as c:
            c.execute(text("DELETE FROM things"))
            c.execute(text("DELETE FROM thing_tombstones"))
            c.execute(text("UPDATE thing_seq SET n = 0"))

        # CRUD
        assert (
            await s.put(
                "urn:pump", _td("urn:pump", "Pump", properties={"rpm": {"type": "integer"}})
            )
            is True
        ), label
        assert (
            await s.put(
                "urn:pump", _td("urn:pump", "Pump2", properties={"rpm": {"type": "integer"}})
            )
            is False
        ), label  # replace
        assert (await s.get("urn:pump"))["title"] == "Pump2", label
        await s.put("urn:lamp", _td("urn:lamp", "Lamp"))
        assert await s.count() == 2, label
        assert {t["id"] for t in await s.list()} == {"urn:pump", "urn:lamp"}, label
        assert len(await s.list(limit=1)) == 1, label

        # JSONPath search , the part that differs per dialect MUST agree
        hits = await s.search("$.properties.rpm")
        assert [t["id"] for t in hits] == ["urn:pump"], f"{label}: search"

        # change log + tombstones
        cur, ch = await s.changes_since(0)
        assert {c[0] for c in ch} == {"urn:pump", "urn:lamp"}, label
        assert await s.delete("urn:lamp") is True, label
        _, ch2 = await s.changes_since(cur)
        assert ch2 == [("urn:lamp", None, ch2[0][2])], f"{label}: tombstone"
