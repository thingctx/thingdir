"""Summarize the types and affordances in a directory.

The summary is derived from stored TDs. A loaded vocabulary adds type
hierarchy information.

A TD declares its own affordances, so no vocabulary is needed to list them.

    tds = await store.list()
    shape = fleet_shape(tds)                  # types + induced properties + counts
    things_with_property(tds, "temperature")  # which Things expose it
    build_fleet_ontology(tds, rdf)            # the unified graph, as Turtle
"""

from __future__ import annotations

from collections import Counter, defaultdict


def _types(td: dict) -> list[str]:
    t = td.get("@type", [])
    types = t if isinstance(t, list) else [t]
    return [x for x in types if isinstance(x, str) and x != "tm:ThingModel"]


def _affordances(td: dict) -> set[str]:
    out: set[str] = set()
    for kind in ("properties", "actions", "events"):
        v = td.get(kind)
        if isinstance(v, dict):
            out.update(v.keys())
    return out


def fleet_shape(tds: list[dict]) -> dict:
    """Return a summary derived from the TDs.

    The result includes the total count, counts by type, and the union of
    affordances observed for each type.
    """
    type_counts: Counter = Counter()
    props_by_type: dict[str, set] = defaultdict(set)
    for td in tds:
        affs = _affordances(td)
        for ty in _types(td):
            type_counts[ty] += 1
            props_by_type[ty].update(affs)
    return {
        "count": len(tds),
        "types": dict(type_counts),
        "properties_by_type": {k: sorted(v) for k, v in props_by_type.items()},
    }


def things_with_property(tds: list[dict], name: str) -> list[str]:
    """The ids of Things that expose an affordance named ``name``."""
    return sorted(td["id"] for td in tds if "id" in td and name in _affordances(td))


def types_in_use(tds: list[dict]) -> set[str]:
    """Return every ``@type`` referenced by the TDs."""
    out: set[str] = set()
    for td in tds:
        out.update(_types(td))
    return out


def build_fleet_ontology(tds: list[dict], rdf, *, fmt: str = "turtle") -> bytes:
    """Serialize the RDF index as one document.

    The document includes projected TDs and any loaded vocabulary. Use
    ``fmt="nquads"`` to preserve named graphs.
    """
    import pyoxigraph as ox

    # the index stores named graphs (a dataset). For a single-document export
    # we flatten every graph's triples into one default-graph store, then dump
    # to a triples format (Turtle/OWL); pass fmt="nquads" to keep the graphs.
    if fmt == "nquads":
        return rdf._store_().dump(format=ox.RdfFormat.N_QUADS)
    fmt_map = {
        "turtle": ox.RdfFormat.TURTLE,
        "ntriples": ox.RdfFormat.N_TRIPLES,
        "rdfxml": ox.RdfFormat.RDF_XML,
    }
    flat = ox.Store()
    for q in rdf._store_():
        flat.add(ox.Quad(q.subject, q.predicate, q.object))
    return flat.dump(format=fmt_map[fmt], from_graph=ox.DefaultGraph())
