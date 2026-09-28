"""Test vocabulary validation, TD projection, and SPARQL query consistency."""

from __future__ import annotations

import hashlib
import os

import pytest

pytest.importorskip("pyoxigraph")

from thingdir.search import RdfIndex
from thingdir.vocab import Vocab, VocabEntry, get

TD = "https://www.w3.org/2019/wot/td#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#Class"


# ---------------------------------------------------------------------------
# 1. validate() across vocabularies
# ---------------------------------------------------------------------------


def _vocab_from(data: bytes, fmt: str) -> Vocab:
    e = VocabEntry(
        name="x",
        prefix="x",
        base="x:",
        sha256=hashlib.sha256(data).hexdigest(),
        vendored="",
        source_url="",
        format=fmt,
    )
    return Vocab(e, data)


def _all_classes(v: Vocab) -> set:
    rows = v._store.query(f"""SELECT DISTINCT ?c WHERE {{
        {{ ?c a <{RDFS}Class> }} UNION {{ ?c a <{OWL}> }}
        UNION {{ ?c <{RDFS}subClassOf> ?x }} UNION {{ ?x <{RDFS}subClassOf> ?c }} }}""")
    return {r["c"].value for r in rows if r["c"].value.startswith("http")}


@pytest.mark.parametrize("name", ["schema.org", "saref"])
def test_validate_bundled_vocab(name):
    v = get(name)
    classes = list(_all_classes(v))
    assert classes, f"{name}: no classes found"
    # every real class validates
    rejected = [c for c in classes if not v.validate(c)]
    assert not rejected, f"{name}: real classes rejected: {rejected[:3]}"
    # junk never validates
    assert not v.validate(f"{v.entry.base}NoSuchClass_ZZZ999")
    assert not v.validate("https://nonexistent.invalid/Nope")


# live vocabularies (network); skip if offline
LIVE = {
    "QUDT": ("https://qudt.org/2.1/schema/qudt", "TURTLE"),
    "SOSA": ("https://www.w3.org/ns/ssn/", "TURTLE"),
    "FOAF": ("http://xmlns.com/foaf/spec/index.rdf", "RDF_XML"),
}


@pytest.mark.skipif(os.getenv("THINGDIR_NO_NET"), reason="network disabled")
@pytest.mark.parametrize("name", list(LIVE))
def test_validate_live_vocab(name):
    import urllib.request

    url, fmt = LIVE[name]
    try:
        data = urllib.request.urlopen(url, timeout=30).read()
    except Exception as e:
        pytest.skip(f"{name} unreachable: {e}")
    v = _vocab_from(data, fmt)
    classes = list(_all_classes(v))
    assert classes
    rejected = [c for c in classes if not v.validate(c)]
    assert not rejected, f"{name}: rejected real classes: {rejected[:3]}"
    assert not v.validate("https://nonexistent.invalid/Nope")


# ---------------------------------------------------------------------------
# 2. the projection drops nothing across many TD shapes
# ---------------------------------------------------------------------------


def _td(**over):
    base = {
        "@context": "https://www.w3.org/2022/wot/td/v1.1",
        "id": "urn:t:1",
        "title": "T",
        "securityDefinitions": {"nosec_sc": {"scheme": "nosec"}},
        "security": ["nosec_sc"],
        "properties": {},
        "actions": {},
        "events": {},
    }
    base.update(over)
    return base


def _prop(name, **extra):
    return {name: {"type": "number", "forms": [{"href": f"http://d/{name}"}], **extra}}


# a corpus of real-world-shaped TDs
CORPUS = [
    # string context
    _td(properties=_prop("temp")),
    # list context with an extension vocabulary
    _td(
        **{
            "@context": [
                "https://www.w3.org/2022/wot/td/v1.1",
                {"saref": "https://saref.etsi.org/core/"},
            ],
            "@type": "saref:Sensor",
            "properties": _prop("temp", **{"@type": "saref:Temperature"}),
        }
    ),
    # multiple @type
    _td(
        **{
            "@context": [
                "https://www.w3.org/2022/wot/td/v1.1",
                {"saref": "https://saref.etsi.org/core/"},
            ],
            "@type": ["saref:Actuator", "saref:Sensor"],
        }
    ),
    # actions + events with names
    _td(
        actions={"setSpeed": {"forms": [{"href": "http://d/s"}]}},
        events={"overheat": {"forms": [{"href": "mqtt://d/e", "op": "subscribeevent"}]}},
    ),
    # nested dataschema (object property with sub-properties)
    _td(
        properties={
            "reading": {
                "type": "object",
                "properties": {"v": {"type": "number"}},
                "forms": [{"href": "http://d/r"}],
            }
        }
    ),
    # multiple forms / transports on one property
    _td(
        properties={
            "x": {
                "type": "number",
                "forms": [
                    {"href": "http://d/x", "op": "readproperty"},
                    {"href": "mqtt://d/x", "op": "observeproperty"},
                ],
            }
        }
    ),
    # many affordances at once
    _td(
        properties={**_prop("a"), **_prop("b"), **_prop("c")},
        actions={"act1": {"forms": [{"href": "http://d/a1"}]}},
    ),
]


@pytest.mark.parametrize("i", range(len(CORPUS)))
def test_projection_drops_nothing(i):
    td = CORPUS[i]
    idx = RdfIndex()
    idx.insert(td["id"], td)
    names_in = (
        set(td.get("properties", {})) | set(td.get("actions", {})) | set(td.get("events", {}))
    )
    names_out = {r["n"] for r in idx.query(f"SELECT ?n WHERE {{ ?a <{TD}name> ?n }}")}
    assert names_in <= names_out, f"corpus[{i}] dropped: {names_in - names_out}"
    # the title always survives
    if "title" in td:
        titles = {str(r["t"]) for r in idx.query(f"SELECT ?t WHERE {{ ?s <{TD}title> ?t }}")}
        assert any(td["title"] in t for t in titles), f"corpus[{i}] lost title"


@pytest.mark.parametrize("i", range(len(CORPUS)))
def test_every_affordance_is_typed_by_kind(i):
    td = CORPUS[i]
    idx = RdfIndex()
    idx.insert(td["id"], td)
    for kind, rel in [
        ("properties", "hasPropertyAffordance"),
        ("actions", "hasActionAffordance"),
        ("events", "hasEventAffordance"),
    ]:
        for name in td.get(kind, {}):
            hit = idx.query(
                f'SELECT ?id WHERE {{ GRAPH ?g {{ ?id <{TD}{rel}> ?a . ?a <{TD}name> "{name}" }} }}'
            )
            assert hit, f"corpus[{i}] {kind}/{name} not reachable via {rel}"


# ---------------------------------------------------------------------------
# 3. in-process query == HTTP endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inprocess_equals_endpoint():
    import tempfile

    import httpx

    from thingdir import build_app
    from thingdir.stores import FsStore

    td = _td(
        **{
            "@context": [
                "https://www.w3.org/2022/wot/td/v1.1",
                {"saref": "https://saref.etsi.org/core/"},
            ],
            "id": "urn:dev:pump:1",
            "@type": "saref:Actuator",
            "properties": _prop("rpm"),
        }
    )

    rdf = RdfIndex()
    app = build_app(FsStore(tempfile.mkdtemp()), rdf=rdf, sync_interval=0)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tdd"
    ) as c:
        r = await c.post("/things", json=td)
        assert r.status_code in (201, 204), r.text  # the TD is valid + stored

        q = "SELECT ?id WHERE { ?id a <https://saref.etsi.org/core/Actuator> }"
        # the endpoint answers in the SPARQL 1.1 Query Results JSON Format, so a
        # binding is {"type": ..., "value": ...}; query() gives Python values.
        body = (await c.get("/search/sparql", params={"query": q})).json()
        endpoint = [{k: v["value"] for k, v in b.items()} for b in body["results"]["bindings"]]
        inprocess = rdf.query(q)
        assert endpoint == inprocess == [{"id": "urn:dev:pump:1"}]
