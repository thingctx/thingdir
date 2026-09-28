"""Load verified vocabularies for type hierarchy queries.

A TD declares its own affordances, but its type hierarchy is defined by a
vocabulary such as schema.org or SAREF. This module verifies vocabulary data
against a pinned hash and passes its RDF to ``RdfIndex.load_vocabulary``.

    from thingdir.vocab import get
    schema = get("schema.org")              # verified, parsed
    schema.validate("https://schema.org/Recipe")          # True
    schema.types_under("https://schema.org/CreativeWork") # the menu
    rdf.load_vocabulary(schema)             # into the RDF index

Bundled vocabularies are stored under ``thingdir/vocabularies``, so ``get``
works offline.
"""

from __future__ import annotations

import hashlib
import pathlib
from dataclasses import dataclass

_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_SUB = _RDFS + "subClassOf"
_VENDOR = pathlib.Path(__file__).parent / "vocabularies"


@dataclass
class VocabEntry:
    name: str
    prefix: str
    base: str
    sha256: str
    vendored: str  # the bundled filename (offline default)
    source_url: str  # the official upstream (re-pin from this)
    format: str = "TURTLE"


REGISTRY: dict[str, VocabEntry] = {
    "schema.org": VocabEntry(
        name="schema.org",
        prefix="schema",
        base="https://schema.org/",
        sha256="320938f0945d717fc317f822c707f10944e7a7a0097018665a3b95dcf475b39d",
        vendored="schemaorg-current-https.ttl",
        source_url="https://schema.org/version/latest/schemaorg-current-https.ttl",
    ),
    "saref": VocabEntry(
        name="saref",
        prefix="saref",
        base="https://saref.etsi.org/core/",
        sha256="e16efbb0f4fa9a940c7238646c0d872de4fcd6dcbdeeb61351f7ea107ebea7de",
        vendored="saref-core-v3.1.1.ttl",
        source_url="https://saref.etsi.org/core/v3.1.1/saref.ttl",
    ),
}


class Vocab:
    """A verified vocabulary with RDF data and type helpers."""

    def __init__(self, entry: VocabEntry, data: bytes) -> None:
        import pyoxigraph as ox

        self.entry = entry
        self.data = data  # raw RDF , RdfIndex.load_vocabulary takes this
        self.format = entry.format
        self.context = {entry.prefix: entry.base}
        self._store = ox.Store()
        self._store.load(data, format=getattr(ox.RdfFormat, entry.format))

    def validate(self, type_iri: str) -> bool:
        """Return whether ``type_iri`` is used as a class in the vocabulary.

        Vocabularies declare classes in different ways. This accepts IRIs
        declared as classes or used in a class position, including as a
        ``subClassOf`` subject or object, a domain or range, or an instance
        type.
        """
        owl = "http://www.w3.org/2002/07/owl#Class"
        sub = f"{_RDFS}subClassOf"
        dom = f"{_RDFS}domain"
        rng = f"{_RDFS}range"
        i = f"<{type_iri}>"
        return bool(
            self._store.query(f"""ASK {{ {{ {i} a <{_RDFS}Class> }}
            UNION {{ {i} a <{owl}> }}
            UNION {{ {i} <{sub}> ?x }} UNION {{ ?x <{sub}> {i} }}
            UNION {{ ?p <{dom}> {i} }} UNION {{ ?p <{rng}> {i} }}
            UNION {{ ?s a {i} }} }}""")
        )

    def types_under(self, root_iri: str) -> list[str]:
        """Return classes at or below ``root_iri`` in the hierarchy."""
        rows = self._store.query(f"SELECT ?c WHERE {{ ?c <{_SUB}>* <{root_iri}> }}")
        return sorted({r["c"].value for r in rows})


def _verify(entry: VocabEntry, data: bytes) -> bytes:
    got = hashlib.sha256(data).hexdigest()
    if got != entry.sha256:
        raise ValueError(
            f"{entry.name}: hash mismatch (pinned {entry.sha256[:12]}, "
            f"got {got[:12]}); review the file before updating the pinned hash."
        )
    return data


def get(name: str, *, data: bytes | None = None) -> Vocab:
    """Load a catalogued vocabulary and verify its hash.

    Uses the bundled copy by default. Pass ``data`` to verify a downloaded file.
    """
    if name not in REGISTRY:
        raise KeyError(f"unknown vocabulary {name!r}; known: {sorted(REGISTRY)}")
    entry = REGISTRY[name]
    if data is None:
        data = (_VENDOR / entry.vendored).read_bytes()
    return Vocab(entry, _verify(entry, data))
