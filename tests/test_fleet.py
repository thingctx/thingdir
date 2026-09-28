"""Test fleet summaries and ontology export from stored TDs."""

from __future__ import annotations

import pytest

from thingdir.fleet import build_fleet_ontology, fleet_shape, things_with_property, types_in_use


def _td(tid, ty, props=()):
    return {
        "@context": ["https://www.w3.org/2022/wot/td/v1.1", {"schema": "https://schema.org/"}],
        "id": tid,
        "@type": ty,
        "properties": {p: {"type": "number"} for p in props},
        "securityDefinitions": {"nosec_sc": {"scheme": "nosec"}},
        "security": ["nosec_sc"],
        "actions": {},
    }


FLEET = [
    _td("urn:1", "schema:Movie", ["duration", "contentRating"]),
    _td("urn:2", "schema:Movie", ["duration"]),
    _td("urn:3", "schema:Recipe", ["cookTime"]),
]


def test_fleet_shape_induced_from_tds():
    s = fleet_shape(FLEET)
    assert s["count"] == 3
    assert s["types"] == {"schema:Movie": 2, "schema:Recipe": 1}
    # the union of affordances actually seen on Movies
    assert s["properties_by_type"]["schema:Movie"] == ["contentRating", "duration"]
    assert s["properties_by_type"]["schema:Recipe"] == ["cookTime"]


def test_things_with_property():
    assert things_with_property(FLEET, "duration") == ["urn:1", "urn:2"]
    assert things_with_property(FLEET, "cookTime") == ["urn:3"]
    assert things_with_property(FLEET, "nope") == []


def test_types_in_use():
    assert types_in_use(FLEET) == {"schema:Movie", "schema:Recipe"}


def test_tm_marker_excluded_from_types():
    s = fleet_shape([_td("urn:m", ["tm:ThingModel", "schema:Movie"])])
    assert "tm:ThingModel" not in s["types"]
    assert "schema:Movie" in s["types"]


@pytest.mark.asyncio
async def test_fleet_ontology_export_and_grouping():
    pytest.importorskip("pyoxigraph")
    from thingdir.search import RdfIndex
    from thingdir.vocab import get

    idx = RdfIndex()
    for td in FLEET:
        idx.insert(td["id"], td)
    idx.load_vocabulary(get("schema.org"))
    # vocabulary grouping: all three are CreativeWorks
    assert idx.find_by_type("https://schema.org/CreativeWork") == ["urn:1", "urn:2", "urn:3"]
    # the unified graph exports as one Turtle document
    ttl = build_fleet_ontology(FLEET, idx)
    assert len(ttl) > 1000 and b"schema.org" in ttl


def test_vocab_get_offline_and_hash():
    from thingdir.vocab import get

    s = get("schema.org")
    assert s.validate("https://schema.org/Recipe") is True
    assert s.validate("https://schema.org/Recpe") is False
