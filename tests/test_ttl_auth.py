"""Test registration TTL, expiry, pruning, and write authentication."""

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


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tdd")


@pytest.mark.asyncio
async def test_registration_info_is_stamped(tmp_path):
    async with _client(build_app(FileStore(str(tmp_path)))) as c:
        await c.post("/things", json=_td("urn:a"))
        reg = (await c.get("/things/urn:a")).json()["registration"]
        assert reg["created"] and reg["modified"]
        # no ttl requested and no default, so the entry is permanent
        assert "expires" not in reg


@pytest.mark.asyncio
async def test_ttl_sets_expiry_and_lazy_expiry_hides_it(tmp_path):
    async with _client(build_app(FileStore(str(tmp_path)))) as c:
        # a ttl of zero seconds is already expired the moment it is read
        await c.post("/things?ttl=0", json=_td("urn:ephemeral"))
        assert (await c.get("/things/urn:ephemeral")).status_code == 404
        # and it is gone from the store, not just hidden
        assert (await c.get("/things")).json() == []


@pytest.mark.asyncio
async def test_default_ttl_applies_when_none_requested(tmp_path):
    app = build_app(FileStore(str(tmp_path)), default_ttl=0)
    async with _client(app) as c:
        await c.post("/things", json=_td("urn:x"))
        assert (await c.get("/things/urn:x")).status_code == 404


@pytest.mark.asyncio
async def test_max_ttl_clamps_a_long_request(tmp_path):
    app = build_app(FileStore(str(tmp_path)), max_ttl=0)
    async with _client(app) as c:
        await c.post("/things?ttl=99999", json=_td("urn:y"))
        # clamped down to zero, so it reads as expired
        assert (await c.get("/things/urn:y")).status_code == 404


@pytest.mark.asyncio
async def test_live_entry_survives_alongside_expired_ones(tmp_path):
    async with _client(build_app(FileStore(str(tmp_path)))) as c:
        await c.post("/things?ttl=0", json=_td("urn:dead"))
        await c.post("/things?ttl=3600", json=_td("urn:alive"))
        ids = [t["id"] for t in (await c.get("/things")).json()]
        assert ids == ["urn:alive"]


@pytest.mark.asyncio
async def test_expired_is_filtered_from_search(tmp_path):
    async with _client(build_app(FileStore(str(tmp_path)))) as c:
        await c.post(
            "/things?ttl=0",
            json=_td(
                "urn:p", properties={"rpm": {"type": "integer", "forms": [{"href": "http://x"}]}}
            ),
        )
        r = await c.get("/search/jsonpath", params={"query": "$.properties.rpm"})
        assert r.status_code == 200 and r.json() == []


@pytest.mark.asyncio
async def test_writes_require_token_when_set(tmp_path):
    app = build_app(FileStore(str(tmp_path)), write_token="secret")
    async with _client(app) as c:
        assert (await c.post("/things", json=_td("urn:z"))).status_code == 401
        assert (await c.put("/things/urn:z", json=_td("urn:z"))).status_code == 401
        assert (await c.delete("/things/urn:z")).status_code == 401
        # reads stay open
        assert (await c.get("/things")).status_code == 200


@pytest.mark.asyncio
async def test_writes_pass_with_correct_token(tmp_path):
    app = build_app(FileStore(str(tmp_path)), write_token="secret")
    h = {"Authorization": "Bearer secret"}
    async with _client(app) as c:
        assert (await c.post("/things", json=_td("urn:ok"), headers=h)).status_code == 201
        assert (await c.get("/things/urn:ok")).status_code == 200
        assert (await c.delete("/things/urn:ok", headers=h)).status_code == 204


@pytest.mark.asyncio
async def test_read_cache_header_lets_a_cdn_serve_reads(tmp_path):
    app = build_app(FileStore(str(tmp_path)), read_cache=60)
    async with _client(app) as c:
        await c.post("/things", json=_td("urn:c"))
        for path in ("/things", "/things/urn:c", "/search/jsonpath?query=$.id"):
            cc = (await c.get(path)).headers.get("cache-control", "")
            assert "max-age=60" in cc and "public" in cc


@pytest.mark.asyncio
async def test_no_cache_header_by_default(tmp_path):
    async with _client(build_app(FileStore(str(tmp_path)))) as c:
        await c.post("/things", json=_td("urn:d"))
        assert "cache-control" not in (await c.get("/things")).headers


@pytest.mark.asyncio
async def test_admin_prune_reclaims_expired(tmp_path):
    async with _client(build_app(FileStore(str(tmp_path)))) as c:
        await c.post("/things?ttl=0", json=_td("urn:gone"))
        await c.post("/things?ttl=3600", json=_td("urn:stay"))
        r = await c.post("/admin/prune")
        assert r.status_code == 200 and r.json() == {"removed": 1}


@pytest.mark.asyncio
async def test_admin_prune_requires_token_when_set(tmp_path):
    app = build_app(FileStore(str(tmp_path)), write_token="secret")
    async with _client(app) as c:
        assert (await c.post("/admin/prune")).status_code == 401
        ok = await c.post("/admin/prune", headers={"Authorization": "Bearer secret"})
        assert ok.status_code == 200
