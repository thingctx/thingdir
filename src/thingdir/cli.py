"""Run the thingdir TDD server.

    thingdir ./things/                      # serve a folder of *.td.json
    thingdir ./things/ --port 8080
    thingdir postgresql://host/db --rdf     # serve from a SQL store

Each flag can also be set with an environment variable:

    THINGDIR_STORE         a folder, or a SQLAlchemy URL (contains "://")
    THINGDIR_WRITE_TOKEN   require Authorization: Bearer <token> on writes
    THINGDIR_DEFAULT_TTL   seconds applied to a registration with no ttl
    THINGDIR_MAX_TTL       upper bound clamped onto any requested ttl
    THINGDIR_SWEEP_INTERVAL  seconds between sweeps of expired TDs
    THINGDIR_READ_CACHE    seconds of Cache-Control on reads (CDN serves them)
    THINGDIR_RDF           "1" to enable SPARQL search (needs [rdf])
    HOST, PORT             bind address (PORT defaults to 8080)
"""

from __future__ import annotations

import os


def _env_float(name: str) -> float | None:
    v = os.environ.get(name)
    return float(v) if v else None


def _build_store(source: str):
    """Build a SqlStore from a SQLAlchemy URL or an FsStore from a path."""
    if "://" in source:
        from thingdir.stores import SqlStore

        return SqlStore(source)
    from thingdir import FileStore

    return FileStore(source)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(
        prog="thingdir", description="Run a W3C Thing Description Directory."
    )
    p.add_argument(
        "source",
        nargs="?",
        default=os.environ.get("THINGDIR_STORE"),
        help="folder of *.td.json, or a SQLAlchemy URL",
    )
    p.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    p.add_argument(
        "--rdf",
        action="store_true",
        default=os.environ.get("THINGDIR_RDF") == "1",
        help="enable SPARQL search (needs [rdf])",
    )
    p.add_argument(
        "--write-token",
        default=os.environ.get("THINGDIR_WRITE_TOKEN"),
        help="require a bearer token on POST/PUT/DELETE",
    )
    p.add_argument(
        "--default-ttl",
        type=float,
        default=_env_float("THINGDIR_DEFAULT_TTL"),
        help="seconds applied to a registration with no ttl",
    )
    p.add_argument(
        "--max-ttl",
        type=float,
        default=_env_float("THINGDIR_MAX_TTL"),
        help="upper bound clamped onto any requested ttl",
    )
    p.add_argument(
        "--sweep-interval",
        type=float,
        default=_env_float("THINGDIR_SWEEP_INTERVAL") or 0.0,
        help="seconds between sweeps of expired TDs (0 disables)",
    )
    p.add_argument(
        "--read-cache",
        type=float,
        default=_env_float("THINGDIR_READ_CACHE") or 0.0,
        help="seconds of Cache-Control on reads, so a CDN serves them (0 off)",
    )
    args = p.parse_args()

    if not args.source:
        p.error("a store is required (a folder, a SQLAlchemy URL, or THINGDIR_STORE)")

    # The HTTP stack is the [server] extra, so the base install can embed the
    # directory without it. Say which extra is missing rather than surfacing a
    # bare ModuleNotFoundError from three frames down.
    try:
        import uvicorn

        from thingdir import build_app
    except ImportError as e:
        raise SystemExit(
            f"thingdir: the server needs the [server] extra ({e.name} is missing).\n"
            '  pip install "thingdir[server]"'
        ) from e

    rdf = None
    if args.rdf:
        from thingdir import RdfIndex

        rdf = RdfIndex()
    app = build_app(
        _build_store(args.source),
        rdf=rdf,
        write_token=args.write_token,
        default_ttl=args.default_ttl,
        max_ttl=args.max_ttl,
        sweep_interval=args.sweep_interval,
        read_cache=args.read_cache,
    )
    print(f"thingdir serving {args.source} at http://{args.host}:{args.port}/things")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
