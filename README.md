# thingdir

[![CI](https://img.shields.io/github/actions/workflow/status/thingctx/thingdir/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/thingctx/thingdir/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square)
[![License](https://img.shields.io/badge/License-Apache--2.0-4c9a2a?style=flat-square)](LICENSE)
![W3C WoT](https://img.shields.io/badge/W3C_WoT-Discovery_TDD-005a9c?style=flat-square)

**A directory for W3C Thing Descriptions. Store and search a fleet through one
API, and query it with SPARQL.**

A [W3C WoT](https://www.w3.org/WoT/) **Thing Description** (TD) describes how
to interact with a device or service. thingdir stores TDs and serves them
through the [WoT Discovery](https://www.w3.org/TR/wot-discovery/) API (TDD).

It supports large fleets, several storage backends, and SPARQL queries.

Any TDD client can read from it, including apps, gateways, and agents.

- **TDD API.** `/things` CRUD, JSONPath and SPARQL search, and an `/events`
  stream.
- **Storage backends.** Use files, SQL, a document database, or Redis.
- **Fleet queries.** TDs are indexed as RDF for SPARQL queries. Load a
  vocabulary to query by type hierarchy.
- **Large fleets.** Keyset pagination and streaming avoid loading every TD at
  once. Pages have flat latency at 100k+ TDs, and search runs in the database.
- **A server or a library.** Every part is importable on its own. A store and
  the RDF index both work in process, with no HTTP and no FastAPI loaded.

## Install

Core, plus the backends you use:

```bash
pip install thingdir                 # the library: stores and search, no HTTP
pip install "thingdir[server]"       # the TDD server and the `thingdir` command
pip install "thingdir[sql]"          # SQLAlchemy (sqlite/postgres/mysql/mssql/Fabric)
pip install "thingdir[mongo]"        # MongoDB / Atlas / Cosmos / DocumentDB
pip install "thingdir[redis]"        # Redis / ElastiCache / Azure Cache / Valkey
pip install "thingdir[rdf]"          # SPARQL search (Oxigraph)
pip install "thingdir[validate]"     # reject a non conformant TD on write
```

Extras stack, so a server with SPARQL is `pip install "thingdir[server,rdf]"`.
The base install has no HTTP dependency at all, because the directory embeds
without one.

```bash
thingdir --help                      # needs [server]
```

## Run a directory

```bash
thingdir ./things/                   # serve a folder of *.td.json (add --rdf for SPARQL)
```

It speaks the standard TDD API, so any client, or plain `curl`, can read it:

```bash
curl localhost:8080/things                                   # list (paginated)
curl 'localhost:8080/search/jsonpath?query=$.properties.temperature'
curl 'localhost:8080/search/sparql?query=SELECT ?id WHERE { ?id a <https://saref.etsi.org/core/Actuator> }'
```

## Use it as a library

The HTTP layer is one consumer of the directory, not the directory. Every part
is importable on its own, and importing a store or the index does not load
FastAPI or start anything.

```python
from thingdir.stores import FsStore     # or SqlStore / MongoStore / RedisStore

store = FsStore("./things")             # a folder, or s3:// az:// gcs:// memory://

await store.put(td["id"], td)           # create or replace
await store.get("urn:dev:pump-42")      # one document, or None
await store.delete("urn:dev:pump-42")
await store.list(limit=50)              # or page(after=..., limit=...) for keyset paging
await store.count()
await store.search("$.properties.temperature")   # JSONPath, per document
store.events()                          # async iterator: created / updated / deleted
await store.changes_since(cursor)       # the change log a derived index tails
```

The semantic side is separate, and optional:

```python
from thingdir.search import RdfIndex
from thingdir.fleet import fleet_shape, things_with_property, build_fleet_ontology

rdf = RdfIndex()
await rdf.sync(store)                   # replays the change log; safe to call any time
rdf.query("SELECT ?id WHERE { ?id a <https://saref.etsi.org/core/Actuator> }")
rdf.find_by_type("https://saref.etsi.org/core/Device")   # walks the type hierarchy

fleet_shape(await store.list())         # types in use, counts, affordances per type
things_with_property(await store.list(), "temperature")
```

`build_app(store)` hands back a plain ASGI app when you do want the REST
surface, so you can mount it inside an application you already have.

## Semantic search

With the `[rdf]` extra, thingdir indexes the fleet as RDF for SPARQL queries:

- Which Things have a `temperature` property?
- Which can I send a `setSpeed` action to?
- Which use `basic` auth?
- Which are reached over MQTT?

TD properties, actions, events, forms, security definitions, and titles are
queryable. Conversion to RDF follows the W3C mapping.

Load a vocabulary to query by type family. A query for a general type returns
TDs with that type or a subtype:

```python
from thingdir.search import RdfIndex
from thingdir.vocab import get

rdf = RdfIndex()
rdf.insert("urn:1", recipe_td)            # a TD typed schema:Recipe
rdf.load_vocabulary(get("schema.org"))    # adds the type hierarchy
rdf.find_by_type("https://schema.org/CreativeWork")   # ["urn:1"] a Recipe is a CreativeWork
```

`get(name)` returns a hash-checked vocabulary. The bundled schema.org and
SAREF vocabularies work offline. `thingdir.fleet` provides `fleet_shape`,
`things_with_property`, and `build_fleet_ontology`.

thingdir does not merge vocabularies. Types from different vocabularies remain
in separate trees unless the vocabularies define links between them.

## Storage backends

The server uses a `Store` interface. Choose a backend for your deployment:

| Store | Backends | Extra |
|--|--|--|
| `FsStore` | **a folder of `*.td.json`**, in-memory, S3, Azure Blob, GCS | none, then `[s3]` / `[azure]` / `[gcs]` |
| `SqlStore` | **one sqlite file**, postgres, mysql, mssql, Microsoft Fabric | `[sql]` plus a driver |
| `MongoStore` | MongoDB, Atlas, Cosmos (Mongo API), DocumentDB, FerretDB | `[mongo]` |
| `RedisStore` | Redis, ElastiCache, Azure Cache, Memorystore, Valkey | `[redis]` |

The two file backed ones need no service at all. A directory of JSON files is
the default and what `thingdir ./things/` uses; point `SqlStore` at
`sqlite:///dir.db` and the whole directory is one file you can copy.

```python
from thingdir import build_app
from thingdir.stores import FsStore, SqlStore     # or MongoStore / RedisStore
from thingdir.search import RdfIndex              # optional SPARQL

FsStore("./things")                               # a folder
FsStore("s3://bucket/things")                     # the same class, object storage
SqlStore("sqlite:///dir.db")                      # one file, no server
SqlStore("postgresql://localhost/things")         # a real database

app = build_app(SqlStore("postgresql://localhost/things"), rdf=RdfIndex())
```

## Replicating a directory

Use the backend's own replication. Postgres streaming replication, a MongoDB
replica set, Redis replication and S3 cross region replication are all durable
and all operated by someone other than you.

When you need a copy in a place the backend cannot reach, every store exposes
a change log:

```python
cursor, changes = await store.changes_since(cursor)
for td_id, td, seq in changes:        # td is None for a delete
    ...                               # PUT it into the other directory
```

The cursor is opaque and resumable, so a consumer that was offline for a week
replays from where it stopped rather than losing the gap. It works between any
two backends, Redis to S3 included, because both ends only have to be a `Store`.

This is one way replication and it assumes one writer per Thing Description,
which is the normal case: a site registers its own devices. Two sites writing
the same description while partitioned needs conflict resolution, which this
does not do.

# The HTTP API

Every endpoint below names the section of
[WoT Discovery](https://www.w3.org/TR/wot-discovery/) it implements, or says
plainly that it is an addition. The base URL is wherever you started the
server; there is no API prefix.

    GET     /things                   list, paginated              7.3.2.1.5
    POST    /things                   register, id from the body   7.3.2.1.1
    GET     /things/{id}              retrieve one                 7.3.2.1.2
    PUT     /things/{id}              create or replace            7.3.2.1.3
    DELETE  /things/{id}              remove                       7.3.2.1.4
    GET     /events                   lifecycle stream (SSE)       7.3.2.2
    GET     /search/jsonpath          syntactic search             7.3.2.3.1
    GET     /search/sparql            semantic search              7.3.2.3.3
    POST    /search/sparql            the same, for a long query   7.3.2.3.3 (optional)
    GET     /things/stream            NDJSON walk of the fleet     addition
    POST    /admin/prune              reclaim expired entries      addition

## Things API

### GET /things

Lists Thing Descriptions, always bounded.

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `limit` | integer, 1 to 1000 | 100 | page size |
| `after` | string | none | keyset cursor: the last id of the previous page |

Returns `200` with a JSON array. When more pages remain, the response carries a
`Link` header with `rel="next"`:

    Link: </things?after=urn:dev:ops:pump-42&limit=100>; rel="next"

Discovery 7.3.2.1.5 requires the `next` link and describes it carrying a
zero-based offset. thingdir uses a keyset cursor instead, so paging cost stays
flat at any depth rather than growing with how far in you are. Follow the link
rather than constructing the next URL yourself and the difference does not
reach you.

Expired registrations are dropped during the walk, so a listing never shows one.

### POST /things

Registers a Thing Description. The `id` comes from the body.

| Parameter | Type | Notes |
|---|---|---|
| `ttl` | number, seconds | optional, overrides `registration.ttl` in the body |

Returns `201` with a `Location: /things/{id}` header. `400` if the body has no
`id`, or if validation is installed and the document is not a conformant TD.
`401` when a write token is configured and the request does not carry it.

### GET /things/{id}

Returns `200` with the document, or `404` if it is absent or its registration
has expired. The id may contain slashes; a URN like `urn:dev:ops:pump-42` needs
no escaping.

### PUT /things/{id}

Creates or replaces. The id in the URL is authoritative and overwrites any `id`
in the body.

| Parameter | Type | Notes |
|---|---|---|
| `ttl` | number, seconds | optional, overrides `registration.ttl` in the body |

Returns `201` when the id was new and `204` when it replaced an existing
document. `400` on an invalid TD, `401` without the write token.

### DELETE /things/{id}

Returns `204`, or `404` if there was nothing to remove. `401` without the write
token.

## Registration and expiry

Every stored document carries a `registration` object, per Discovery 7.3.1.2:

    "registration": {
      "created":  "2026-09-27T10:04:11Z",
      "modified": "2026-09-27T10:04:11Z",
      "ttl": 3600,
      "expires": "2026-09-27T11:04:11Z"
    }

`created` survives a replace; `modified` is stamped on every write. When a `ttl`
applies, the server computes `expires` itself and ignores any client value,
which is what 7.3.1.2 requires. With no ttl in play, both fields are absent and
the registration is permanent.

Expiry is lazy. An expired document is invisible to every read and is deleted
when a read walks over it, so the directory is correct with no background loop
running. Two ways to reclaim the space: set `sweep_interval` for a background
sweep, or call `POST /admin/prune` from an external scheduler.

## Events API

### GET /events

A Server Sent Events stream of lifecycle changes, per Discovery 7.3.2.2.
`Content-Type: text/event-stream`, one event per change:

    event: created
    data: {"event": "created", "id": "urn:dev:ops:pump-42"}

The event name is one of `created`, `updated`, `deleted`.

## Search API

### GET /search/jsonpath

`query` is a JSONPath expression, per Discovery 7.3.2.3.1. Returns `200` with
the matching documents, or `400` with the parse error when the expression is
bad. Expired documents are filtered out.

The expression is evaluated **against each Thing Description in turn**, and a
document is returned when the expression finds anything in it. So write the
path as if the document were the root:

    /search/jsonpath?query=$.title                    every TD that has a title
    /search/jsonpath?query=$.properties.temperature   every TD with that property
    /search/jsonpath?query=$.actions.*.forms[*].href  TDs that declare any form

A collection level filter such as `$[?(@.title)]` matches nothing, because the
root it is given is one document, not the array.

### GET /search/sparql

`query` is a SPARQL query, per Discovery 7.3.2.3.3. Four forms, two answers:

| Query | Status | Content-Type | Body |
|---|---|---|---|
| `SELECT` | 200 | `application/json` | SPARQL 1.1 Query Results JSON |
| `ASK` | 200 | `application/json` | `{"head":{},"boolean":true}` |
| `CONSTRUCT` | 200 | `application/ld+json` | JSON-LD |
| `DESCRIBE` | 200 | `application/ld+json` | JSON-LD |

Anything else, including an `INSERT` or a `DROP`, is a `400`. The endpoint
evaluates queries only; there is no write path through it.

**`501` when the server was built without an RDF index**, which is the default.
Start with `--rdf` (and install the `[rdf]` extra) to enable it.

`POST /search/sparql` does the same thing and exists because a real query
outgrows a URL. Both SPARQL 1.1 Protocol bodies work: `application/sparql-query`
carries the query directly, `application/x-www-form-urlencoded` carries it in a
`query` field. Anything else is a `415`.

The graph is the standard projection: the official W3C TD 1.1 JSON-LD context
through the standard JSON-LD to RDF algorithm, one named graph per Thing. So
every part of a description is queryable by the specification's own mapping,
not an invented one.

## Additions

These are not in the Discovery API. They sit alongside it; nothing in the
standard surface depends on them.

### GET /things/stream

Walks the whole fleet as newline delimited JSON, one page in memory at a time.
`Content-Type: application/x-ndjson`. For exporting a large directory without
paging by hand.

### POST /admin/prune

Deletes expired registrations and returns `{"removed": n}`. Requires the write
token when one is configured. Meant for an external scheduler on a host that
scales to zero, so no warm loop is needed to keep expiry honest.

## Configuration

### Command line

    thingdir <store> [options]

`<store>` is a directory path or an fsspec URL (`s3://`, `az://`, `gcs://`,
`memory://`), or a SQLAlchemy URL (`postgresql://`, `sqlite:///`).

| Flag | Environment | Default | Effect |
|---|---|---|---|
| `--host` | `HOST` | `127.0.0.1` | bind address |
| `--port` | `PORT` | `8080` | bind port |
| `--rdf` | `THINGDIR_RDF=1` | off | enable `/search/sparql`; needs `[rdf]` |
| `--write-token` | `THINGDIR_WRITE_TOKEN` | none | require `Authorization: Bearer <token>` on POST, PUT and DELETE |
| `--default-ttl` | `THINGDIR_DEFAULT_TTL` | none | seconds applied to a registration that asks for no ttl |
| `--max-ttl` | `THINGDIR_MAX_TTL` | none | upper bound clamped onto any requested ttl |
| `--sweep-interval` | `THINGDIR_SWEEP_INTERVAL` | 0 | seconds between background expiry sweeps; 0 disables it |
| `--read-cache` | `THINGDIR_READ_CACHE` | 0 | seconds of `Cache-Control` on reads, so a CDN absorbs the hot path |

`THINGDIR_STORE` supplies `<store>` when no argument is given.

### Embedded

    from thingdir import build_app
    from thingdir.stores import FsStore

    app = build_app(FsStore("./things"), write_token="s3cret", default_ttl=3600)

`build_app(store, *, rdf=None, sync_interval=1.0, write_token=None,
default_ttl=None, max_ttl=None, sweep_interval=0.0, read_cache=0.0)`. Pass an
`RdfIndex` as `rdf` to enable SPARQL; it tails the store's change log rather
than being written to directly, so it recovers from a crash and is safe to run
on several instances over one shared store. `sync_interval=0` turns the
background poll off.

### Authorization

One switch. With `write_token` set, `POST`, `PUT`, `DELETE` and `/admin/prune`
require `Authorization: Bearer <token>` and answer `401` without it. Reads are
always open.

That is the whole model, deliberately. A directory in front of a fleet that
needs per caller authorization belongs behind a gateway that does it properly;
Discovery 7.1.2 leaves the mechanism to the deployment, and a single shared
secret is honest about being the floor rather than pretending to be more.

### Caching

With `read_cache` set to N seconds, every read carries

    Cache-Control: public, max-age=N, stale-while-revalidate=N

so a CDN serves the hot path and the origin can scale to zero between writes.

## Contributing

A new storage backend is one class that implements `Store`. See
[CONTRIBUTING.md](CONTRIBUTING.md). Sign commits with `git commit -s` (DCO).

## License

Apache-2.0. Copyright 2026 The thingdir Authors.
