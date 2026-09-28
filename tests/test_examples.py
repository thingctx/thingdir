"""Test that example TDs use valid vocabulary types and hierarchy."""

from __future__ import annotations

import json
import pathlib

import pytest

pytest.importorskip("pyoxigraph")
from thingdir.search import RdfIndex
from thingdir.vocab import get

_EX = pathlib.Path(__file__).parent.parent / "examples" / "things"
SAREF = "https://saref.etsi.org/core/"
TD = "https://www.w3.org/2019/wot/td#"


def _load(name):
    return json.loads((_EX / name).read_text())


def test_example_types_are_real():
    saref, schema = get("saref"), get("schema.org")
    assert saref.validate(SAREF + "Actuator")
    assert saref.validate(SAREF + "Pressure")
    assert saref.validate(SAREF + "ActuatingFunction")
    assert schema.validate("https://schema.org/WebAPI")
    assert schema.validate("https://schema.org/QuantitativeValue")


def test_pump_is_grouped_under_saref_device():
    pump = _load("pump.td.json")
    idx = RdfIndex()
    idx.insert(pump["id"], pump)
    idx.load_vocabulary(get("saref"))
    # the pump is both an Actuator and a Sensor, so a Device
    assert idx.find_by_type(SAREF + "Device") == ["urn:dev:pump:coolant-7"]
    assert idx.find_by_type(SAREF + "Actuator") == ["urn:dev:pump:coolant-7"]
    assert idx.find_by_type(SAREF + "Sensor") == ["urn:dev:pump:coolant-7"]


def test_pump_queryable_by_measured_property():
    pump = _load("pump.td.json")
    idx = RdfIndex()
    idx.insert(pump["id"], pump)
    r = idx.query(
        f"SELECT DISTINCT ?id WHERE {{ GRAPH ?g {{ "
        f"?id <{TD}hasPropertyAffordance> ?a . ?a a <{SAREF}Pressure> }} }}"
    )
    assert [x["id"] for x in r] == ["urn:dev:pump:coolant-7"]


def test_validate_handles_all_class_declaration_styles():
    """Accept declared classes and types used only in hierarchy statements."""
    schema, saref = get("schema.org"), get("saref")
    assert schema.validate("https://schema.org/Recipe")  # rdfs:Class
    assert saref.validate("https://saref.etsi.org/core/Actuator")  # owl:Class
    # a SAREF class used as a subClassOf target (Device is a parent of many)
    assert saref.validate("https://saref.etsi.org/core/Device")
    # typos rejected in both
    assert not schema.validate("https://schema.org/Recpe")
    assert not saref.validate("https://saref.etsi.org/core/Acutator")
