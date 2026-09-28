"""The W3C Thing Description Directory (TDD) HTTP API over a Store."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from thingdir.stores.base import Store

# /things is always bounded; clients walk pages via the Link header.
DEFAULT_PAGE = 100
MAX_PAGE = 1000


def _validate(td: dict) -> None:
    """Validate a TD if the optional thingctx package is installed."""
    try:
        import thingctx

        problems = thingctx.validate_td(td)
    except ImportError:
        return  # validation not installed; skip
    if problems:
        raise HTTPException(400, detail={"error": "invalid TD", "problems": problems[:10]})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _expires_at(td: dict) -> datetime | None:
    """Return the registration expiry time, or None if it is unset."""
    exp = (td.get("registration") or {}).get("expires")
    return _parse(exp) if exp else None


def _is_expired(td: dict, *, at: datetime | None = None) -> bool:
    exp = _expires_at(td)
    return exp is not None and exp < (at or _now())


def build_app(
    store: Store,
    *,
    rdf=None,
    sync_interval: float = 1.0,
    write_token: str | None = None,
    default_ttl: float | None = None,
    max_ttl: float | None = None,
    sweep_interval: float = 0.0,
    read_cache: float = 0.0,
) -> FastAPI:
    """Build a TDD API over a Store.

    Pass an RdfIndex as ``rdf`` to enable SPARQL search.
    Set ``sync_interval=0`` to disable background polling.

    Optional controls include write authentication, TTL limits, expiry sweeps,
    and response caching. ``default_ttl`` sets the default lifetime; None means
    no expiry. ``max_ttl`` caps requested lifetimes. ``sweep_interval`` controls
    background cleanup, and zero disables sweeps. ``read_cache`` sets the
    response cache lifetime, and zero disables caching.
      write_token     if set, POST/PUT/DELETE require Authorization: Bearer <token>.
    Reads still hide expired TDs when background sweeps are disabled.

    An external scheduler can remove expired TDs with POST /admin/prune.
    """
    app = FastAPI(title="thingdir", description="A W3C Thing Description Directory.")

    async def _sync():
        if rdf is not None:
            await rdf.sync(store)

    def _resolve_ttl(requested: float | None) -> float | None:
        ttl = requested if requested is not None else default_ttl
        if ttl is None:
            return None
        ttl = float(ttl)
        if max_ttl is not None:
            ttl = min(ttl, float(max_ttl))
        return ttl

    def _stamp(td: dict, prev: dict | None, ttl: float | None) -> dict:
        """Set registration timestamps and expiry while preserving creation time."""
        reg = dict((prev or {}).get("registration") or {})
        now = _now()
        reg["created"] = reg.get("created") or _iso(now)
        reg["modified"] = _iso(now)
        if ttl is not None:
            reg["ttl"] = ttl
            reg["expires"] = _iso(now + timedelta(seconds=ttl))
        else:
            reg.pop("ttl", None)
            reg.pop("expires", None)
        td["registration"] = reg
        return td

    def _check_write(request: Request) -> None:
        if write_token is None:
            return
        if request.headers.get("authorization", "") != f"Bearer {write_token}":
            raise HTTPException(401, detail="write requires a bearer token")

    def _read_headers(extra: dict | None = None) -> dict:
        h = dict(extra or {})
        if read_cache and read_cache > 0:
            n = int(read_cache)
            h["Cache-Control"] = f"public, max-age={n}, stale-while-revalidate={n}"
        return h

    async def _drop_if_expired(td: dict) -> bool:
        """Delete an expired TD and return whether it was expired."""
        if not _is_expired(td):
            return False
        await store.delete(td["id"])
        return True

    async def _sweep_once() -> int:
        after = None
        removed = 0
        while True:
            tds, after = await store.page(after=after, limit=DEFAULT_PAGE)
            now = _now()
            for td in tds:
                if _is_expired(td, at=now):
                    await store.delete(td["id"])
                    removed += 1
            if after is None:
                break
        if removed:
            await _sync()
        return removed

    if rdf is not None:

        @app.on_event("startup")
        async def _startup():
            await _sync()  # rebuild
            if sync_interval > 0:

                async def _poller():
                    while True:
                        await asyncio.sleep(sync_interval)
                        try:
                            await _sync()
                        except Exception:  # self-heals next tick
                            pass

                app.state._poller = asyncio.create_task(_poller())

    if sweep_interval and sweep_interval > 0:

        @app.on_event("startup")
        async def _sweeper():
            async def _loop():
                while True:
                    await asyncio.sleep(sweep_interval)
                    try:
                        await _sweep_once()
                    except Exception:  # self-heals next tick
                        pass

            app.state._sweeper = asyncio.create_task(_loop())

    # --- Things API ---

    @app.get("/things")
    async def list_things(
        limit: int = Query(DEFAULT_PAGE, ge=1, le=MAX_PAGE),
        after: str | None = Query(None, description="keyset cursor: the last id seen"),
    ):
        # keyset pagination, always bounded; next cursor in the Link header.
        tds, nxt = await store.page(after=after, limit=limit)
        now = _now()
        live, swept = [], False
        for td in tds:
            if _is_expired(td, at=now):
                await store.delete(td["id"])
                swept = True
            else:
                live.append(td)
        if swept:
            await _sync()
        headers = _read_headers()
        if nxt is not None:
            headers["Link"] = f'</things?after={nxt}&limit={limit}>; rel="next"'
        return JSONResponse(live, headers=headers)

    @app.get("/things/stream")
    async def stream_things():
        # NDJSON: one page in memory at a time; scales to any fleet size.
        async def gen():
            after = None
            while True:
                tds, after = await store.page(after=after, limit=DEFAULT_PAGE)
                now = _now()
                for td in tds:
                    if not _is_expired(td, at=now):
                        yield json.dumps(td) + "\n"
                if after is None:
                    break

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    @app.get("/things/{td_id:path}")
    async def get_thing(td_id: str):
        td = await store.get(td_id)
        if td is None:
            raise HTTPException(404, detail=f"no TD with id {td_id!r}")
        if await _drop_if_expired(td):
            await _sync()
            raise HTTPException(404, detail=f"no TD with id {td_id!r}")
        return JSONResponse(td, headers=_read_headers())

    @app.put("/things/{td_id:path}")
    async def put_thing(
        td_id: str,
        request: Request,
        ttl: float | None = Query(None, ge=0, description="registration lifetime in seconds"),
    ):
        _check_write(request)
        td = await request.json()
        td["id"] = td_id  # the URL id is authoritative
        _validate(td)
        requested = ttl if ttl is not None else (td.get("registration") or {}).get("ttl")
        prev = await store.get(td_id)
        _stamp(td, prev, _resolve_ttl(requested))
        created = await store.put(td_id, td)
        await _sync()
        return Response(status_code=201 if created else 204)

    @app.post("/things")
    async def register_thing(
        request: Request,
        ttl: float | None = Query(None, ge=0, description="registration lifetime in seconds"),
    ):
        _check_write(request)
        td = await request.json()
        td_id = td.get("id")
        if not td_id:
            raise HTTPException(400, detail="TD must have an 'id'")
        _validate(td)
        requested = ttl if ttl is not None else (td.get("registration") or {}).get("ttl")
        prev = await store.get(td_id)
        _stamp(td, prev, _resolve_ttl(requested))
        await store.put(td_id, td)
        await _sync()
        return Response(status_code=201, headers={"Location": f"/things/{td_id}"})

    @app.delete("/things/{td_id:path}")
    async def delete_thing(td_id: str, request: Request):
        _check_write(request)
        if not await store.delete(td_id):
            raise HTTPException(404, detail=f"no TD with id {td_id!r}")
        await _sync()
        return Response(status_code=204)

    @app.post("/admin/prune")
    async def prune(request: Request):
        # Reclaim expired TDs on demand, so an external scheduler can prune
        # without a warm background loop that would keep the origin awake.
        _check_write(request)
        return {"removed": await _sweep_once()}

    # --- Search API ---

    @app.get("/search/jsonpath")
    async def search_jsonpath(query: str = Query(..., description="a JSONPath expression")):
        try:
            hits = await store.search(query)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, detail=f"bad JSONPath: {e}") from e
        now = _now()
        live = [td for td in hits if not _is_expired(td, at=now)]
        return JSONResponse(live, headers=_read_headers())

    def _sparql(query: str) -> Response:
        """Run a SPARQL query and answer in the protocol's own formats.

        Discovery 7.3.2.3.3: SELECT and ASK answer application/json, CONSTRUCT
        and DESCRIBE answer application/ld+json, and anything that is not one
        of those four is a 400.
        """
        if rdf is None:
            raise HTTPException(
                501,
                detail="SPARQL search not enabled "
                "(build the app with an RdfIndex; needs the [rdf] extra)",
            )
        try:
            media_type, body = rdf.query_serialized(query)
        except Exception as e:  # noqa: BLE001 (any parse or evaluation failure is a bad query)
            raise HTTPException(400, detail=f"bad SPARQL: {e}") from e
        return Response(content=body, media_type=media_type, headers=_read_headers())

    @app.get("/search/sparql")
    async def search_sparql(query: str = Query(..., description="a SPARQL query")):
        return _sparql(query)

    @app.post("/search/sparql")
    async def search_sparql_post(request: Request):
        """POST is OPTIONAL in Discovery 7.3.2.3.3 and exists because a real
        query outgrows a URL. Both SPARQL 1.1 Protocol bodies are accepted:
        application/sparql-query carries the query directly, and a form body
        carries it in a `query` field."""
        ctype = request.headers.get("content-type", "").split(";")[0].strip()
        raw = await request.body()
        if ctype == "application/sparql-query":
            query = raw.decode("utf-8")
        elif ctype == "application/x-www-form-urlencoded":
            query = parse_qs(raw.decode("utf-8")).get("query", [""])[0]
        else:
            raise HTTPException(
                415,
                detail="send application/sparql-query, or "
                "application/x-www-form-urlencoded with a query field",
            )
        if not query.strip():
            raise HTTPException(400, detail="empty SPARQL query")
        return _sparql(query)

    # --- Events API (SSE lifecycle) ---

    @app.get("/events")
    async def events():
        async def stream():
            async for evt in store.events():
                yield f"event: {evt['event']}\ndata: {json.dumps(evt)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app
