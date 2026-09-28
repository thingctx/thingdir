"""Project TDs to RDF for SPARQL search with Oxigraph.

The index uses the official W3C TD JSON-LD context and JSON-LD to RDF
conversion. The context maps affordance names, such as ``flowRate``, to RDF.
It is bundled so conversion works offline.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

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

        A cursor of zero rebuilds the index. Repeating a sync is safe.
        """
        new_cursor, changes = await store.changes_since(self._cursor)
        for td_id, td, _seq in changes:
            if td is None:
                self.remove(td_id)
            else:
                self.insert(td_id, td)
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
        doc = _localize_context({**td, "id": td_id})
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
