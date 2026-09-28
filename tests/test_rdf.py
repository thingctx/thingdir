"""Test RDF projection, named graph isolation, and SPARQL search."""

from __future__ import annotations

import httpx
import pytest

pytest.importorskip("pyoxigraph")

from thingdir import FileStore, build_app
from thingdir.search import RdfIndex

_SEC = {"securityDefinitions": {"nosec_sc": {"scheme": "nosec"}}, "security": ["nosec_sc"]}
PUMP = {
    "@context": "https://www.w3.org/2022/wot/td/v1.1",
    "id": "urn:dev:pump:1",
    "@type": "https://saref.etsi.org/core/Actuator",
    "title": "Pump",
    "properties": {"rpm": {"type": "integer", "forms": [{"href": "http://pump/rpm"}]}},
    **_SEC,
}
LAMP = {
    "@context": "https://www.w3.org/2022/wot/td/v1.1",
    "id": "urn:dev:lamp:1",
    "@type": "https://saref.etsi.org/core/LightSwitch",
    "title": "Lamp",
    **_SEC,
}

TITLE = "https://www.w3.org/2019/wot/td#title"
PUMP_T = "https://saref.etsi.org/core/Actuator"  # SAREF core has no Pump; a pump is an Actuator


def test_projection_produces_title_and_type():
    idx = RdfIndex()
    idx.insert("urn:dev:pump:1", PUMP)
    titles = idx.query(f"SELECT ?t WHERE {{ ?id <{TITLE}> ?t }}")
    assert titles == [{"t": "Pump"}]
    typed = idx.query(f"SELECT ?id WHERE {{ ?id a <{PUMP_T}> }}")
    assert typed == [{"id": "urn:dev:pump:1"}]


def test_semantic_query_filters_by_type():
    idx = RdfIndex()
    idx.insert("urn:dev:pump:1", PUMP)
    idx.insert("urn:dev:lamp:1", LAMP)
    # the query JSONPath cannot express: "Things of type Pump"
    hits = idx.query(f"SELECT ?id WHERE {{ ?id a <{PUMP_T}> }}")
    assert [h["id"] for h in hits] == ["urn:dev:pump:1"]


def test_delete_isolates_one_graph():
    idx = RdfIndex()
    idx.insert("urn:dev:pump:1", PUMP)
    idx.insert("urn:dev:lamp:1", LAMP)
    idx.remove("urn:dev:lamp:1")
    titles = {r["t"] for r in idx.query(f"SELECT ?t WHERE {{ ?id <{TITLE}> ?t }}")}
    assert titles == {"Pump"}  # lamp gone, pump untouched


def test_update_replaces_only_that_graph():
    idx = RdfIndex()
    idx.insert("urn:dev:pump:1", PUMP)
    idx.insert("urn:dev:lamp:1", LAMP)
    idx.insert("urn:dev:pump:1", {**PUMP, "title": "Pump v2"})
    titles = {r["t"] for r in idx.query(f"SELECT ?t WHERE {{ ?id <{TITLE}> ?t }}")}
    assert titles == {"Pump v2", "Lamp"}  # only the pump's title changed


@pytest.mark.asyncio
async def test_sparql_endpoint_end_to_end(tmp_path):
    app = build_app(FileStore(str(tmp_path)), rdf=RdfIndex())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tdd"
    ) as c:
        await c.post("/things", json=PUMP)
        await c.post("/things", json=LAMP)
        r = await c.get(
            "/search/sparql", params={"query": f"SELECT ?id WHERE {{ ?id a <{PUMP_T}> }}"}
        )
        assert r.status_code == 200
        assert r.json()["results"]["bindings"] == [
            {"id": {"type": "uri", "value": "urn:dev:pump:1"}}
        ]
        # deleting reflects in SPARQL
        await c.delete("/things/urn:dev:pump:1")
        r = await c.get(
            "/search/sparql", params={"query": f"SELECT ?id WHERE {{ ?id a <{PUMP_T}> }}"}
        )
        assert r.json()["results"]["bindings"] == []


@pytest.mark.asyncio
async def test_sparql_501_without_rdf(tmp_path):
    app = build_app(FileStore(str(tmp_path)))  # no rdf index
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tdd"
    ) as c:
        r = await c.get("/search/sparql", params={"query": "SELECT * WHERE {?s ?p ?o}"})
        assert r.status_code == 501
