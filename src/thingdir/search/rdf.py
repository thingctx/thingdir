"""Project TDs to RDF for SPARQL search with Oxigraph.

The index uses the official W3C TD JSON-LD context and JSON-LD to RDF
conversion. The context maps affordance names, such as ``flowRate``, to RDF.
It is bundled so conversion works offline.
"""

from __future__ import annotations

import functools
import json
import logging
import pathlib
from typing import Any

_log = logging.getLogger("thingdir")

_TD_VOCAB = "https://www.w3.org/2019/wot/td#"
_REMOTE_CONTEXTS = {
    "https://www.w3.org/2022/wot/td/v1.1",
    "https://www.w3.org/2019/wot/td/v1",
    "http://www.w3.org/ns/td",
}
_TD_CONTEXT_FILE = pathlib.Path(__file__).parent.parent / "vocabularies" / "td-context-1.1.jsonld"
_TD_CONTEXT: Any = None


def _td_context() -> Any:
    """The official TD 1.1 @context value (the inner object), loaded once."""
    global _TD_CONTEXT
    if _TD_CONTEXT is None:
        doc = json.loads(_TD_CONTEXT_FILE.read_bytes())
        _TD_CONTEXT = doc["@context"]
    return _TD_CONTEXT


def _localize_context(td: dict) -> dict:
    """Use the bundled WoT context and preserve extension contexts."""
    out = dict(td)
    ctx = out.get("@context")
    extensions = []
    if ctx is not None:
        for item in ctx if isinstance(ctx, list) else [ctx]:
            if isinstance(item, str) and item in _REMOTE_CONTEXTS:
                continue  # drop the remote WoT URL (use the vendored one)
            extensions.append(item)  # keep inline dicts / extension URLs
    out["@context"] = [_td_context(), *extensions]
    return out


# A TD may give these terms any JSON value (TD 1.1, 5.3.2.1), but the TD context does not
# mark them @json, so JSON-LD reads an object value as a node and its "type" key as @type.
_DATA_TERMS = frozenset({"const", "default", "enum"})


@functools.cache
def _name_maps() -> frozenset[str]:
    """Terms the TD context declares as index maps (``"@container": "@index"``), such as
    ``properties``: a key inside one is a name, never a term."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, dict) and value.get("@container") == "@index":
                    found.add(key)
                walk(value)

    walk(_td_context())
    return frozenset(found)


def _json_literal(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return {"@value": value, "@type": "@json"}
    return value


def _with_json_literals(node: Any) -> Any:
    """A copy of ``node`` with each object or array value of a data term written as a
    JSON-LD JSON literal, so it projects to one rdf:JSON value."""
    if isinstance(node, list):
        return [_with_json_literals(item) for item in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "enum" and isinstance(value, list):
            out[key] = [_json_literal(item) for item in value]
        elif key in _DATA_TERMS:
            out[key] = _json_literal(value)
        elif key in _name_maps() and isinstance(value, dict):
            out[key] = {name: _with_json_literals(item) for name, item in value.items()}
        else:
            out[key] = _with_json_literals(value)
    return out


class RdfIndex:
    """An embedded Oxigraph RDF index.

    The index is in memory by default. Pass ``path`` for persistent storage.
    """

    def __init__(self, *, path: str | None = None) -> None:
        self._path = path
        self._store: Any = None
        self._cursor = 0  # last store change seq applied (sync)

    async def sync(self, store) -> int:
        """Apply store changes since this index's cursor.

        A cursor of zero rebuilds the index. Repeating a sync is safe. A TD that
        cannot be projected is left out of the index and logged; it stays in the
        store, and the cursor moves past it, so it cannot fail every later sync.
        """
        new_cursor, changes = await store.changes_since(self._cursor)
        for td_id, td, _seq in changes:
            if td is None:
                self.remove(td_id)
                continue
            try:
                self.insert(td_id, td)
            except (SyntaxError, ValueError) as e:
                self.remove(td_id)
                _log.warning("thingdir: %s is stored but not searchable by SPARQL: %s", td_id, e)
        self._cursor = new_cursor
        return new_cursor

    def _store_(self):
        if self._store is not None:
            return self._store
        try:
            import pyoxigraph
        except ImportError as e:
            raise ImportError("RdfIndex needs pyoxigraph: pip install 'thingdir[rdf]'") from e
        self._store = pyoxigraph.Store(self._path) if self._path else pyoxigraph.Store()
        return self._store

    def insert(self, td_id: str, td: dict) -> None:
        """Project a TD to RDF in the named graph keyed by ``td_id``,
        replacing any prior triples for it."""
        import pyoxigraph

        store = self._store_()
        graph = pyoxigraph.NamedNode(td_id)
        self.remove(td_id)
        doc = _localize_context(_with_json_literals({**td, "id": td_id}))
        store.load(
            json.dumps(doc).encode(),
            format=pyoxigraph.RdfFormat.JSON_LD,
            to_graph=graph,
            lenient=True,
        )

    def remove(self, td_id: str) -> None:
        import pyoxigraph

        store = self._store_()
        try:
            store.remove_graph(pyoxigraph.NamedNode(td_id))
        except Exception:  # graph absent; idempotent
            pass

    def load_vocabulary(self, vocab) -> None:
        """Load vocabulary RDF for type hierarchy queries.

        ``vocab`` can provide ``data`` and ``format`` attributes or be a
        ``(data, format)`` tuple. The RDF is loaded into a shared graph.
        """
        import pyoxigraph

        data, fmt = (vocab.data, vocab.format) if hasattr(vocab, "data") else vocab
        self._store_().load(
            data,
            format=getattr(pyoxigraph.RdfFormat, fmt),
            to_graph=pyoxigraph.NamedNode("urn:thingdir:vocab"),
        )

    def find_by_type(self, type_iri: str, *, include_subtypes: bool = True):
        """Return TD ids with ``type_iri`` or one of its subtypes.

        Subtype matching uses a loaded vocabulary. Vocabulary nodes are
        excluded from results.
        """
        sub = "<http://www.w3.org/2000/01/rdf-schema#subClassOf>*"
        if include_subtypes:
            # the TD's `a ?t` triple is in its own graph; the subClassOf* walk
            # spans the default-graph union (which includes the vocab). Bind
            # ?id only from a non-vocab graph so vocabulary nodes never match.
            where = (
                f"GRAPH ?g {{ ?id a ?t }} "
                f"FILTER(?g != <urn:thingdir:vocab>) "
                f"?t {sub} <{type_iri}> ."
            )
        else:
            where = f"GRAPH ?g {{ ?id a <{type_iri}> }} FILTER(?g != <urn:thingdir:vocab>)"
        rows = self.query(f"SELECT DISTINCT ?id WHERE {{ {where} }}")
        return sorted({r["id"] for r in rows})

    def query_serialized(self, sparql: str) -> tuple[str, bytes]:
        """Run any SPARQL query and serialize the result the way the protocol
        says, returning ``(media_type, body)``.

        SELECT and ASK serialize to the SPARQL 1.1 Query Results JSON Format;
        CONSTRUCT and DESCRIBE return a graph, so they serialize to JSON-LD.
        Oxigraph owns both serializations, so the shapes are the standard ones
        rather than something assembled here.
        """
        import pyoxigraph as ox  # noqa: PLC0415 (the [rdf] extra, imported on use)

        results = self._store_().query(sparql, use_default_graph_as_union=True)
        if isinstance(results, ox.QueryTriples):
            return "application/ld+json", results.serialize(format=ox.RdfFormat.JSON_LD)
        return "application/json", results.serialize(format=ox.QueryResultsFormat.JSON)

    def query(self, sparql: str) -> list[dict]:
        """Run a SPARQL query across the fleet's named graphs, as Python values.

        SELECT returns binding dictionaries, ASK returns ``[{"_ask": bool}]``,
        and a graph query returns one ``{"_term": ...}`` per triple. For the
        wire format a client expects, use :meth:`query_serialized`.
        """
        import pyoxigraph as ox  # noqa: PLC0415 (the [rdf] extra, imported on use)

        results = self._store_().query(sparql, use_default_graph_as_union=True)
        # A boolean result is a QueryBoolean, not a bool, so an isinstance
        # check against bool silently falls through to the triple branch and
        # raises "not iterable" on every ASK.
        if isinstance(results, ox.QueryBoolean):
            return [{"_ask": bool(results)}]
        if hasattr(results, "variables"):
            variables = list(results.variables)
            out = []
            for soln in results:
                row = {}
                for var in variables:
                    term = soln[var]
                    if term is not None:
                        row[var.value] = getattr(term, "value", str(term))
                out.append(row)
            return out
        return [{"_term": str(t)} for t in results]
