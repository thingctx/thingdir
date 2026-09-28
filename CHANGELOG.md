# Changelog

## 0.1.0 - 2026-09-27

First release.

### Added

- The W3C Discovery Directory Service API: the Things API (7.3.2.1), the Events API over Server Sent Events (7.3.2.2), JSONPath search (7.3.2.3.1), and SPARQL search (7.3.2.3.3).
- Registration expiry per 7.3.1.2: the server computes `expires` from a `ttl` and ignores any client value. Expiry applies lazily on read, so the directory is correct with no background loop; a sweep interval and `POST /admin/prune` reclaim the space.
- Four store backends behind one protocol: files or object storage over fsspec, any SQLAlchemy engine, the MongoDB API, and the Redis family.
- A change log on every backend: each assigns a monotonic sequence to every write and delete and keeps tombstones, so a derived index or a one way replica tails it and resumes from a cursor. `changes_since(0)` is a full rebuild.
- SPARQL over the standard TD to RDF projection: the official W3C TD 1.1 context through the JSON-LD 1.1 to RDF algorithm, one named graph per Thing. `SELECT` and `ASK` answer the SPARQL 1.1 Query Results JSON Format, `CONSTRUCT` and `DESCRIBE` answer JSON-LD, and `POST /search/sparql` accepts both SPARQL 1.1 Protocol bodies for a query that outgrows a URL.
- Fleet semantics induced from the stored documents: `fleet_shape`, `things_with_property`, `types_in_use`, and `build_fleet_ontology`.
- Hash pinned vocabularies with schema.org and SAREF bundled for offline use, and type hierarchy queries through `find_by_type`.
- `GET /things/stream`, an NDJSON walk of the fleet that holds one page in memory.
- Optional write authorization: with a write token set, `POST`, `PUT`, `DELETE` and `POST /admin/prune` require a bearer token. Reads stay open.
- Optional TD validation on write against the W3C TD 1.1 schema, behind the `validate` extra.
- `Cache-Control` on reads, so a CDN absorbs the hot path and the origin can scale to zero between writes.
- Keyset pagination with a `next` Link header, so page cost stays flat at any depth.

### Notes

- The HTTP stack is the `server` extra. The base install has no HTTP dependency, because every part is importable on its own and the directory embeds with no FastAPI loaded.
- The `next` Link header carries a keyset cursor where 7.3.2.1.5 describes a zero-based offset. Follow the link rather than building the next URL and the difference does not reach you.
- The PyPI badge is added to the README with the first published release, not before, so it never renders red.
