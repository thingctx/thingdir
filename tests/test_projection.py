"""Test that standard TD to RDF projection supports SPARQL queries."""

from __future__ import annotations

import pytest

pytest.importorskip("pyoxigraph")
from thingdir.search import RdfIndex

TD = "https://www.w3.org/2019/wot/td#"

RICH = {
    "@context": ["https://www.w3.org/2022/wot/td/v1.1", {"schema": "https://schema.org/"}],
    "id": "urn:pump:1",
    "title": "Coolant Pump",
    "@type": "schema:Product",
    "properties": {
        "flowRate": {
            "type": "number",
            "@type": "schema:QuantitativeValue",
            "forms": [{"href": "http://dev/flow"}],
        },
        "status": {"type": "string"},
    },
    "actions": {"setSpeed": {"forms": [{"href": "http://dev/speed"}]}},
    "events": {"overheat": {"forms": [{"href": "http://dev/evt"}]}},
    "securityDefinitions": {"basic_sc": {"scheme": "basic"}},
    "security": ["basic_sc"],
}


@pytest.fixture
def idx():
    i = RdfIndex()
    i.insert("urn:pump:1", RICH)
    return i


def _ids(idx, where):
    return sorted(
        {r["id"] for r in idx.query(f"SELECT DISTINCT ?id WHERE {{ GRAPH ?g {{ {where} }} }}")}
    )


def test_query_by_type(idx):
    assert _ids(idx, "?id a <https://schema.org/Product>") == ["urn:pump:1"]


def test_query_by_property_affordance_name(idx):
    # the formerly-impossible query: Things with a 'flowRate' property
    assert _ids(idx, f'?id <{TD}hasPropertyAffordance> ?a . ?a <{TD}name> "flowRate"') == [
        "urn:pump:1"
    ]
    assert _ids(idx, f'?id <{TD}hasActionAffordance> ?a . ?a <{TD}name> "setSpeed"') == [
        "urn:pump:1"
    ]
    assert _ids(idx, f'?id <{TD}hasEventAffordance> ?a . ?a <{TD}name> "overheat"') == [
        "urn:pump:1"
    ]


def test_query_affordance_kinds_distinct(idx):
    # property/action/event are distinct relations , not all lumped together
    assert _ids(idx, f'?id <{TD}hasPropertyAffordance> ?a . ?a <{TD}name> "setSpeed"') == []


def test_query_by_form_target(idx):
    assert _ids(
        idx,
        f"?id <{TD}hasPropertyAffordance> ?a . ?a <{TD}hasForm> ?f . "
        f"?f <https://www.w3.org/2019/wot/hypermedia#hasTarget> ?h . "
        f'FILTER(CONTAINS(STR(?h), "flow"))',
    ) == ["urn:pump:1"]


def test_query_by_security_scheme(idx):
    assert _ids(
        idx,
        f"?id <{TD}definesSecurityScheme> ?s . "
        f"?s a <https://www.w3.org/2019/wot/security#BasicSecurityScheme>",
    ) == ["urn:pump:1"]


def test_query_by_title(idx):
    assert _ids(idx, f'?id <{TD}title> ?t . FILTER(STR(?t) = "Coolant Pump")') == ["urn:pump:1"]


def test_semantic_annotation_on_property_survives(idx):
    # a property's @type (schema:QuantitativeValue) is queryable. NOTE:
    # schema.org normalizes to its canonical http: namespace in JSON-LD, so
    # the projected IRI is http://schema.org/... (a well-known schema.org
    # http/https quirk) , match by local name to be scheme-agnostic.
    assert _ids(
        idx,
        f"?id <{TD}hasPropertyAffordance> ?a . ?a a ?t . "
        f'FILTER(CONTAINS(STR(?t), "schema.org/QuantitativeValue"))',
    ) == ["urn:pump:1"]


def test_nothing_dropped():
    # every affordance NAME in the source TD appears as a td:name triple
    idx = RdfIndex()
    idx.insert("urn:pump:1", RICH)
    names = {r["n"] for r in idx.query(f"SELECT ?n WHERE {{ GRAPH ?g {{ ?a <{TD}name> ?n }} }}")}
    expected = set(RICH["properties"]) | set(RICH["actions"]) | set(RICH["events"])
    assert expected <= names, f"dropped: {expected - names}"
