"""Test subtype queries and exclude vocabulary nodes from results."""

from __future__ import annotations

import pytest

pytest.importorskip("pyoxigraph")
from thingdir.search import RdfIndex

# a tiny vocabulary (Device <- Pump, Sensor ; Fixture <- Lamp)
VOCAB = """
@prefix ex:   <https://ex/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
ex:Device  a owl:Class ; rdfs:label "Device" .
ex:Pump    a owl:Class ; rdfs:label "Pump"   ; rdfs:subClassOf ex:Device .
ex:Sensor  a owl:Class ; rdfs:label "Sensor" ; rdfs:subClassOf ex:Device .
ex:Fixture a owl:Class ; rdfs:label "Fixture" .
ex:Lamp    a owl:Class ; rdfs:label "Lamp"   ; rdfs:subClassOf ex:Fixture .
"""


def _td(tid, type_iri):
    return {
        "@context": ["https://www.w3.org/2022/wot/td/v1.1", {"ex": "https://ex/"}],
        "id": tid,
        "title": tid,
        "@type": type_iri,
        "securityDefinitions": {"nosec_sc": {"scheme": "nosec"}},
        "security": ["nosec_sc"],
        "actions": {},
    }


def _idx():
    idx = RdfIndex()
    idx.insert("urn:pump", _td("urn:pump", "ex:Pump"))
    idx.insert("urn:sensor", _td("urn:sensor", "ex:Sensor"))
    idx.insert("urn:lamp", _td("urn:lamp", "ex:Lamp"))
    idx.load_vocabulary((VOCAB.encode(), "TURTLE"))
    return idx


def test_superclass_query():
    idx = _idx()
    assert idx.find_by_type("https://ex/Pump", include_subtypes=False) == ["urn:pump"]
    # Device finds Pump + Sensor (subclasses), not Lamp (other branch)
    assert idx.find_by_type("https://ex/Device") == ["urn:pump", "urn:sensor"]
    assert idx.find_by_type("https://ex/Fixture") == ["urn:lamp"]


def test_returns_only_tds_not_vocab_nodes():
    # querying the very top must return the TDs only, never the vocab classes
    idx = _idx()
    assert idx.find_by_type("https://ex/Device") == ["urn:pump", "urn:sensor"]
    # a CURIE @type still matches (insert went in as ex:Pump)
    assert "urn:pump" in idx.find_by_type("https://ex/Device")
