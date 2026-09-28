"""Serving a directory of files that were already there.

Every other store test writes through `put` first, so the whole path from
"point the server at a folder someone handed you" was never exercised. All
three failures below came from that gap: `_scan` learned the ids but nothing
else learned anything.
"""

from __future__ import annotations

import json
import pathlib
import shutil

import httpx
import pytest

from thingdir.app import build_app
from thingdir.stores.fs import FsStore

EXAMPLES = pathlib.Path(__file__).parent.parent / "examples" / "things"


@pytest.fixture
def fleet(tmp_path):
    """A directory of hand named TD files, as a user would hand one over."""
    for p in EXAMPLES.glob("*.json"):
        shutil.copy(p, tmp_path)
    return tmp_path


async def test_documents_already_on_disk_are_readable(fleet):
    """A file keeps the name it arrived with. Reading by id has to follow the
    path the scan found, not a name derived from the id."""
    store = FsStore(str(fleet))
    ids = sorted(store._ids)
    assert len(ids) == 2, ids
    assert await store.count() == 2
    listed = await store.list()
    assert len(listed) == 2, "scan found the ids but list returned nothing"
    assert sorted(td["id"] for td in listed) == ids
    for tid in ids:
        assert (await store.get(tid)) is not None, f"{tid} indexed but unreadable"


async def test_page_and_search_see_them_too(fleet):
    store = FsStore(str(fleet))
    tds, _ = await store.page(limit=100)
    assert len(tds) == 2
    assert len(await store.search("$.title")) == 2


async def test_a_write_still_lands_and_reads_back(fleet):
    """The canonical name is still used for documents this store creates, and
    a replace of a discovered document stays at the path it came from."""
    store = FsStore(str(fleet))
    existing = sorted(store._ids)[0]
    before = store._paths[existing]

    await store.put(existing, {"id": existing, "title": "replaced"})
    assert store._paths[existing] == before, "a replace moved the file"
    assert (await store.get(existing))["title"] == "replaced"

    await store.put("urn:new:1", {"id": "urn:new:1", "title": "new"})
    assert (await store.get("urn:new:1"))["title"] == "new"
    assert (fleet / "urn_new_1.td.json").exists()

    assert await store.delete(existing) is True
    assert (await store.get(existing)) is None


async def test_the_change_log_includes_what_was_already_there(fleet):
    """A derived index replays from changes_since(0). A document that was on
    disk before the process started has to appear in that replay."""
    store = FsStore(str(fleet))
    _, changes = await store.changes_since(0)
    assert len(changes) == 2, "the index would never learn these exist"
    assert all(td is not None for _, td, _ in changes)
    assert sorted(cid for cid, _, _ in changes) == sorted(store._ids)


async def test_sparql_answers_over_a_directory_pointed_at(fleet):
    """The end of that chain: point the server at a folder, ask SPARQL."""
    pytest.importorskip("pyoxigraph")
    from thingdir.search import RdfIndex

    store = FsStore(str(fleet))
    rdf = RdfIndex()
    await rdf.sync(store)
    rows = rdf.query("SELECT ?id WHERE { ?id <https://www.w3.org/2019/wot/td#title> ?t }")
    assert len(rows) == 2, "the index is empty although the directory is not"


async def test_http_serves_a_directory_it_did_not_write(fleet):
    store = FsStore(str(fleet))
    app = build_app(store, sync_interval=0)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://d") as c:
        r = await c.get("/things")
        assert r.status_code == 200
        assert len(r.json()) == 2, "GET /things is empty for a pre-populated folder"
        tid = r.json()[0]["id"]
        assert (await c.get(f"/things/{tid}")).status_code == 200


def test_validate_extra_actually_validates():
    """`thingdir[validate]` has to pull thingctx WITH its own validate extra.
    Plain thingctx has no jsonschema, so validate_td raises ImportError and
    app._validate swallows it, leaving the extra inert."""
    pyproject = (pathlib.Path(__file__).parent.parent / "pyproject.toml").read_text()
    assert 'validate = ["thingctx[validate]' in pyproject, (
        "the validate extra must request thingctx[validate], not bare thingctx"
    )


async def test_invalid_td_is_refused_when_validation_is_installed(fleet):
    jsonschema = pytest.importorskip("jsonschema")  # noqa: F841
    pytest.importorskip("thingctx")
    store = FsStore(str(fleet))
    app = build_app(store, sync_interval=0)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://d") as c:
        r = await c.post("/things", json={"id": "urn:bad:1", "title": "no security"})
        assert r.status_code == 400
        assert "problems" in json.dumps(r.json())
