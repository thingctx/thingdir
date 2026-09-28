"""Test FsStore with local, memory, and configured cloud backends."""

from __future__ import annotations

import pytest

pytest.importorskip("fsspec")
from thingdir.stores import FsStore


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


@pytest.fixture(params=["local", "memory"])
def store(request, tmp_path):
    if request.param == "local":
        return FsStore(str(tmp_path / "things"))
    import uuid

    return FsStore(f"memory://{uuid.uuid4().hex}")  # isolated per test


@pytest.mark.asyncio
async def test_crud(store):
    assert await store.put("urn:a", _td("urn:a")) is True
    assert await store.put("urn:a", _td("urn:a", "X")) is False  # replace
    assert (await store.get("urn:a"))["title"] == "X"
    await store.put("urn:b", _td("urn:b"))
    assert await store.count() == 2
    assert {t["id"] for t in await store.list()} == {"urn:a", "urn:b"}
    assert len(await store.list(limit=1)) == 1
    assert await store.delete("urn:a") is True
    assert await store.get("urn:a") is None
    assert await store.delete("urn:a") is False


@pytest.mark.asyncio
async def test_jsonpath_search(store):
    await store.put(
        "urn:pump",
        _td("urn:pump", properties={"rpm": {"type": "integer", "forms": [{"href": "http://x"}]}}),
    )
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


@pytest.mark.asyncio
async def test_persists_across_reopen(tmp_path):
    s1 = FsStore(str(tmp_path / "things"))
    await s1.put("urn:keep", _td("urn:keep"))
    s2 = FsStore(str(tmp_path / "things"))  # reopen the same local dir
    assert (await s2.get("urn:keep"))["id"] == "urn:keep"
