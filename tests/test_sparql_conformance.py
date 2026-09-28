"""The four SPARQL query forms, and what Discovery 7.3.2.3.3 says each returns.

SELECT and ASK answer application/json, CONSTRUCT and DESCRIBE answer
application/ld+json, anything else is a 400. Only SELECT was right before:
ASK raised because a boolean result is a QueryBoolean and the isinstance check
was against bool, and the two graph forms came back with the SELECT wrapper
and the wrong media type.
"""

from __future__ import annotations

import json
import pathlib
import shutil

import httpx
import pytest

from thingdir.app import build_app
from thingdir.stores.fs import FsStore

pytest.importorskip("pyoxigraph")

EXAMPLES = pathlib.Path(__file__).parent.parent / "examples" / "things"
PUMP = "urn:dev:pump:coolant-7"


@pytest.fixture
async def client(tmp_path):
    from thingdir.search import RdfIndex

    for p in EXAMPLES.glob("*.json"):
        shutil.copy(p, tmp_path)
    store = FsStore(str(tmp_path))
    rdf = RdfIndex()
    await rdf.sync(store)
    app = build_app(store, rdf=rdf, sync_interval=0)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://d") as c:
        c._rdf = rdf
        yield c


def media(r) -> str:
    return r.headers.get("content-type", "").split(";")[0].strip()


async def test_select_returns_the_results_json_format(client):
    r = await client.get("/search/sparql", params={"query": "SELECT ?s WHERE {?s ?p ?o} LIMIT 1"})
    assert r.status_code == 200
    assert media(r) == "application/json"
    body = r.json()
    assert body["head"]["vars"] == ["s"]
    assert body["results"]["bindings"][0]["s"]["value"]


async def test_ask_returns_a_boolean_not_an_error(client):
    r = await client.get("/search/sparql", params={"query": "ASK {?s ?p ?o}"})
    assert r.status_code == 200, r.text
    assert media(r) == "application/json"
    assert r.json() == {"head": {}, "boolean": True}

    r = await client.get("/search/sparql", params={"query": "ASK { <urn:nope> ?p ?o }"})
    assert r.json()["boolean"] is False


@pytest.mark.parametrize(
    "query",
    [
        "CONSTRUCT {?s ?p ?o} WHERE {?s ?p ?o} LIMIT 1",
        f"DESCRIBE <{PUMP}>",
    ],
)
async def test_graph_queries_return_json_ld(client, query):
    r = await client.get("/search/sparql", params={"query": query})
    assert r.status_code == 200, r.text
    assert media(r) == "application/ld+json"
    doc = json.loads(r.content)
    assert isinstance(doc, list) and doc, "expected a JSON-LD document"
    assert "@id" in doc[0]


@pytest.mark.parametrize(
    "query",
    [
        "INSERT DATA { <urn:evil> <urn:p> <urn:o> }",
        "DELETE WHERE { ?s ?p ?o }",
        "DROP ALL",
        "NOT SPARQL AT ALL",
    ],
)
async def test_anything_that_is_not_a_query_is_refused(client, query):
    before = len(client._rdf.query("SELECT ?s WHERE {?s ?p ?o}"))
    r = await client.get("/search/sparql", params={"query": query})
    assert r.status_code == 400, r.text
    after = len(client._rdf.query("SELECT ?s WHERE {?s ?p ?o}"))
    assert after == before, "an update reached the store through the query endpoint"


async def test_post_accepts_both_protocol_bodies(client):
    """POST is OPTIONAL in 7.3.2.3.3 and exists because a real query outgrows a
    URL. SPARQL 1.1 Protocol defines both of these bodies."""
    r = await client.post(
        "/search/sparql",
        content="SELECT ?s WHERE {?s ?p ?o} LIMIT 1",
        headers={"content-type": "application/sparql-query"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["results"]["bindings"]

    r = await client.post("/search/sparql", data={"query": "ASK {?s ?p ?o}"})
    assert r.status_code == 200, r.text
    assert r.json() == {"head": {}, "boolean": True}


async def test_post_rejects_a_body_it_cannot_read(client):
    r = await client.post("/search/sparql", content="x", headers={"content-type": "text/plain"})
    assert r.status_code == 415
    r = await client.post(
        "/search/sparql", content="  ", headers={"content-type": "application/sparql-query"}
    )
    assert r.status_code == 400


async def test_get_and_post_agree(client):
    q = "SELECT ?s WHERE {?s ?p ?o} LIMIT 3"
    a = await client.get("/search/sparql", params={"query": q})
    b = await client.post(
        "/search/sparql", content=q, headers={"content-type": "application/sparql-query"}
    )
    assert a.json() == b.json()


async def test_sparql_is_501_when_no_index_is_configured(tmp_path):
    app = build_app(FsStore(str(tmp_path)), sync_interval=0)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://d") as c:
        assert (
            await c.get("/search/sparql", params={"query": "ASK {?s ?p ?o}"})
        ).status_code == 501
        r = await c.post(
            "/search/sparql",
            content="ASK {?s ?p ?o}",
            headers={"content-type": "application/sparql-query"},
        )
        assert r.status_code == 501
