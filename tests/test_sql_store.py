"""Test SqlStore with SQLite and any configured SQL databases."""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
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


@pytest.fixture
def store(tmp_path):
    return SqlStore(f"sqlite:///{tmp_path / 't.db'}")


@pytest.mark.asyncio
async def test_crud(store):
    assert await store.put("urn:a", _td("urn:a")) is True
    assert await store.put("urn:a", _td("urn:a", "X")) is False  # replace
    assert (await store.get("urn:a"))["title"] == "X"
    await store.put("urn:b", _td("urn:b"))
    assert await store.count() == 2
    assert {t["id"] for t in await store.list()} == {"urn:a", "urn:b"}
    assert await store.delete("urn:a") is True
    assert await store.get("urn:a") is None


@pytest.mark.asyncio
async def test_jsonpath_search(store):
    await store.put("urn:pump", _td("urn:pump", properties={"rpm": {"type": "integer"}}))
    await store.put("urn:lamp", _td("urn:lamp"))
    hits = await store.search("$.properties.rpm")
    assert [t["id"] for t in hits] == ["urn:pump"]


@pytest.mark.asyncio
async def test_changes_since_and_tombstones(store):
    await store.put("urn:a", _td("urn:a"))
    cur, ch = await store.changes_since(0)
    assert [c[0] for c in ch] == ["urn:a"]
    await store.delete("urn:a")
    _, ch2 = await store.changes_since(cur)
    assert ch2 == [("urn:a", None, ch2[0][2])]
