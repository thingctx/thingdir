"""Test the TDD API with FileStore and thingctx."""

from __future__ import annotations

import httpx
import pytest

from thingdir import FileStore, build_app


def _td(tid, **extra):
    return {
        "@context": "https://www.w3.org/2022/wot/td/v1.1",
        "id": tid,
        "title": "T",
        "securityDefinitions": {"nosec_sc": {"scheme": "nosec"}},
        "security": ["nosec_sc"],
        "actions": {},
        **extra,
    }


def _client(tmp_path):
    app = build_app(FileStore(str(tmp_path)))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tdd")


@pytest.mark.asyncio
async def test_register_list_get_delete(tmp_path):
    async with _client(tmp_path) as c:
        r = await c.post("/things", json=_td("urn:a"))
        assert r.status_code == 201 and r.headers["location"] == "/things/urn:a"

        r = await c.get("/things")
        assert r.status_code == 200 and len(r.json()) == 1

        r = await c.get("/things/urn:a")
        assert r.status_code == 200 and r.json()["id"] == "urn:a"

        assert (await c.delete("/things/urn:a")).status_code == 204
        assert (await c.get("/things/urn:a")).status_code == 404


@pytest.mark.asyncio
async def test_put_by_id_sets_id(tmp_path):
    async with _client(tmp_path) as c:
        # PUT with a body whose id differs , the URL id wins
        r = await c.put("/things/urn:real", json=_td("urn:wrong"))
        assert r.status_code == 201
        assert (await c.get("/things/urn:real")).json()["id"] == "urn:real"


@pytest.mark.asyncio
async def test_search_jsonpath(tmp_path):
    async with _client(tmp_path) as c:
        await c.post(
            "/things",
            json=_td(
                "urn:pump", properties={"rpm": {"type": "integer", "forms": [{"href": "http://x"}]}}
            ),
        )
        await c.post("/things", json=_td("urn:lamp"))
        r = await c.get("/search/jsonpath", params={"query": "$.properties.rpm"})
        assert r.status_code == 200 and [t["id"] for t in r.json()] == ["urn:pump"]


@pytest.mark.asyncio
async def test_thingctx_reads_from_the_directory(tmp_path):
    thingctx = pytest.importorskip("thingctx")
    async with _client(tmp_path) as c:
        await c.post(
            "/things",
            json=_td(
                "urn:dev:pump:1", actions={"set_speed": {"forms": [{"href": "https://api.x/set"}]}}
            ),
        )
        things = (await c.get("/things")).json()
    # thingctx builds a working client straight from the directory's output.
    # The names here are thingctx's, not ours: it namespaces an affordance by
    # its Thing so a fleet cannot collide, and asserting the shape it actually
    # produces is the only version of this check worth having.
    client = thingctx.ThingClient(tds=things, bindings=[thingctx.HttpBinding()])
    names = [spec["function"]["name"] for spec in client.list_actions()]
    assert "pump__set_speed" in names, names
