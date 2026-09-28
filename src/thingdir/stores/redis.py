"""Store TDs in Redis and record changes in a Redis Stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

_KEY = "thingdir:td:"  # per-TD JSON key prefix
_STREAM = "thingdir:changes"  # the change log
_IDX = "thingdir:idx"  # the RediSearch index


def _dotpath(jsonpath: str) -> str | None:
    p = jsonpath.strip()
    if not p.startswith("$"):
        return None
    p = p[1:].lstrip(".")
    if any(c in p for c in "[]?*()@ "):
        return None
    return p or None


class RedisStore:
    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.from_url(url, decode_responses=True)
        self._subscribers: list[asyncio.Queue] = []

    def _key(self, td_id: str) -> str:
        return _KEY + td_id

    def _log(self, op: str, td_id: str) -> str:
        # the stream id is the cursor (monotonic, exclusive-range capable).
        return self._r.xadd(_STREAM, {"op": op, "id": td_id})

    def _emit(self, event: str, td_id: str) -> None:
        for q in list(self._subscribers):
            q.put_nowait({"event": event, "id": td_id})

    async def _run(self, fn):
        return await asyncio.to_thread(fn)

    async def put(self, td_id: str, td: dict) -> bool:
        def _do():
            existed = self._r.exists(self._key(td_id)) == 1
            self._r.json().set(self._key(td_id), "$", td)
            self._log("put", td_id)
            return not existed

        created = await self._run(_do)
        self._emit("created" if created else "updated", td_id)
        return created

    async def get(self, td_id: str) -> dict | None:
        def _do():
            v = self._r.json().get(self._key(td_id))
            return v

        return await self._run(_do)

    async def delete(self, td_id: str) -> bool:
        def _do():
            n = self._r.delete(self._key(td_id))
            if n:
                self._log("del", td_id)
            return n > 0

        removed = await self._run(_do)
        if removed:
            self._emit("deleted", td_id)
        return removed

    async def list(self, *, limit: int | None = None, offset: int = 0) -> list[dict]:
        def _do():
            keys = sorted(self._r.scan_iter(match=_KEY + "*"))
            keys = keys[offset : offset + limit if limit is not None else None]
            return [self._r.json().get(k) for k in keys]

        return await self._run(_do)

    async def page(self, *, after=None, limit: int = 100):
        def _do():
            plen = len(_KEY)
            ids = sorted(k[plen:] for k in self._r.scan_iter(match=_KEY + "*"))
            if after is not None:
                ids = [i for i in ids if i > after]
            ids = ids[:limit]
            tds = [self._r.json().get(_KEY + i) for i in ids]
            nxt = ids[-1] if len(ids) == limit else None
            return tds, nxt

        return await self._run(_do)

    async def count(self) -> int:
        def _do():
            return sum(1 for _ in self._r.scan_iter(match=_KEY + "*"))

        return await self._run(_do)

    async def search(self, jsonpath: str) -> list[dict]:
        dot = _dotpath(jsonpath)
        if dot is None:
            return []

        # JSON.TYPE is non-empty only where the path exists (scan; small fleets).
        def _do():
            out = []
            for k in sorted(self._r.scan_iter(match=_KEY + "*")):
                if self._r.json().type(k, f"$.{dot}"):
                    out.append(self._r.json().get(k))
            return out

        return await self._run(_do)

    async def changes_since(self, cursor):
        # cursor = a stream id (opaque to the consumer).
        def _do():
            start = f"({cursor}" if cursor else "-"  # '(' = exclusive
            entries = self._r.xrange(_STREAM, min=start, max="+")
            # collapse to the LATEST change per id (a replaced TD logs twice)
            latest: dict[str, tuple] = {}
            new_cursor = cursor or "0-0"
            for entry_id, fields in entries:
                new_cursor = entry_id
                tid, op = fields["id"], fields["op"]
                if op == "del":
                    latest[tid] = (tid, None, entry_id)
                else:
                    td = self._r.json().get(self._key(tid))
                    latest[tid] = (tid, td, entry_id) if td is not None else (tid, None, entry_id)
            changes = list(latest.values())
            return new_cursor, changes

        return await self._run(_do)

    async def events(self) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.remove(q)
