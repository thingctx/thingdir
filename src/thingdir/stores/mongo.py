"""Store TDs through the MongoDB API."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


# JSONPath -> Mongo dot-path (plain field paths only).
def _jsonpath_to_dotpath(jsonpath: str) -> str | None:
    p = jsonpath.strip()
    if not p.startswith("$"):
        return None
    p = p[1:].lstrip(".")
    if any(c in p for c in "[]?*()@ "):  # not a plain field path
        return None
    return p.replace(".", ".") or None


class MongoStore:
    def __init__(self, url: str, *, db: str = "thingdir") -> None:
        import pymongo

        self._client = pymongo.MongoClient(url)
        self._db = self._client[db]
        self._things = self._db["things"]
        self._tombstones = self._db["tombstones"]
        self._counter = self._db["counter"]
        self._subscribers: list[asyncio.Queue] = []
        # a single counter doc gives a monotonic version across writes
        if self._counter.find_one({"_id": "seq"}) is None:
            self._counter.insert_one({"_id": "seq", "n": 0})
        self._things.create_index("seq")
        self._things.create_index("id", unique=True)

    def _next_seq(self) -> int:
        doc = self._counter.find_one_and_update(
            {"_id": "seq"}, {"$inc": {"n": 1}}, return_document=True
        )
        return doc["n"]

    def _emit(self, event: str, td_id: str) -> None:
        for q in list(self._subscribers):
            q.put_nowait({"event": event, "id": td_id})

    async def _run(self, fn):
        return await asyncio.to_thread(fn)

    async def put(self, td_id: str, td: dict) -> bool:
        def _do():
            existed = self._things.find_one({"id": td_id}, {"_id": 1}) is not None
            seq = self._next_seq()
            self._things.replace_one(
                {"id": td_id}, {"id": td_id, "seq": seq, "td": td}, upsert=True
            )
            return not existed

        created = await self._run(_do)
        self._emit("created" if created else "updated", td_id)
        return created

    async def get(self, td_id: str) -> dict | None:
        def _do():
            doc = self._things.find_one({"id": td_id})
            return doc["td"] if doc else None

        return await self._run(_do)

    async def delete(self, td_id: str) -> bool:
        def _do():
            n = self._things.delete_one({"id": td_id}).deleted_count
            if n:
                self._tombstones.insert_one({"id": td_id, "seq": self._next_seq()})
            return n > 0

        removed = await self._run(_do)
        if removed:
            self._emit("deleted", td_id)
        return removed

    async def list(self, *, limit: int | None = None, offset: int = 0) -> list[dict]:
        def _do():
            cur = self._things.find({}, {"td": 1}).sort("id", 1).skip(offset)
            if limit is not None:
                cur = cur.limit(limit)
            return [d["td"] for d in cur]

        return await self._run(_do)

    async def page(self, *, after=None, limit: int = 100):
        def _do():
            q = {"id": {"$gt": after}} if after is not None else {}
            docs = list(self._things.find(q, {"id": 1, "td": 1}).sort("id", 1).limit(limit))
            tds = [d["td"] for d in docs]
            nxt = docs[-1]["id"] if len(docs) == limit else None
            return tds, nxt

        return await self._run(_do)

    async def count(self) -> int:
        return await self._run(lambda: self._things.count_documents({}))

    async def search(self, jsonpath: str) -> list[dict]:
        dot = _jsonpath_to_dotpath(jsonpath)
        if dot is None:
            return []  # unsupported expression on Mongo

        def _do():
            cur = self._things.find({f"td.{dot}": {"$exists": True}}, {"td": 1}).sort("id", 1)
            return [d["td"] for d in cur]

        return await self._run(_do)

    async def changes_since(self, cursor: int) -> tuple[int, list[tuple]]:
        def _do():
            rows = self._things.find({"seq": {"$gt": cursor}}, {"id": 1, "td": 1, "seq": 1})
            tombs = self._tombstones.find({"seq": {"$gt": cursor}}, {"id": 1, "seq": 1})
            changes = [(r["id"], r["td"], r["seq"]) for r in rows]
            changes += [(t["id"], None, t["seq"]) for t in tombs]
            changes.sort(key=lambda c: c[2])
            new_cursor = changes[-1][2] if changes else cursor
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
