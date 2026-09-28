"""Test RedisStore when THINGDIR_REDIS_URL points to Redis with the JSON module."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("redis")
URL = os.getenv("THINGDIR_REDIS_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set THINGDIR_REDIS_URL")

from thingdir.stores import RedisStore


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


@pytest.fixture
def store():
    s = RedisStore(URL)
    s._r.flushdb()
    return s


@pytest.mark.asyncio
async def test_crud_search_changes(store):
    assert (
        await store.put("urn:pump", _td("urn:pump", properties={"rpm": {"type": "integer"}}))
        is True
    )
    assert (
        await store.put("urn:pump", _td("urn:pump", "X", properties={"rpm": {"type": "integer"}}))
        is False
    )
    assert (await store.get("urn:pump"))["title"] == "X"
    await store.put("urn:lamp", _td("urn:lamp"))
    assert await store.count() == 2
    assert [t["id"] for t in await store.search("$.properties.rpm")] == ["urn:pump"]
    cur, ch = await store.changes_since(0)
    assert {c[0] for c in ch} == {"urn:pump", "urn:lamp"}
    assert await store.delete("urn:lamp") is True
    _, ch2 = await store.changes_since(cur)
    assert ch2 == [("urn:lamp", None, ch2[0][2])]  # the delete tombstone


@pytest.mark.asyncio
async def test_rdf_syncs_via_streams(store):
    pytest.importorskip("pyoxigraph")
    from thingdir.search import RdfIndex

    await store.put(
        "urn:pump", _td("urn:pump", "P", **{"@type": "https://saref.etsi.org/core/Actuator"})
    )
    await store.put("urn:lamp", _td("urn:lamp", "L"))
    idx = RdfIndex()
    await idx.sync(store)
    assert idx.query("SELECT ?id WHERE { ?id a <https://saref.etsi.org/core/Actuator> }") == [
        {"id": "urn:pump"}
    ]
    # incremental: delete propagates through the stream cursor
    await store.delete("urn:lamp")
    await idx.sync(store)
    titles = {
        r["t"]
        for r in idx.query("SELECT ?t WHERE { ?id <https://www.w3.org/2019/wot/td#title> ?t }")
    }
    assert titles == {"P"}
