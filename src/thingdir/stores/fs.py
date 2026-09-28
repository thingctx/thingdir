"""Store TDs on any fsspec backend."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from jsonpath_ng.ext import parse as jsonpath_parse


def _safe_name(td_id: str) -> str:
    return "".join(c if (c.isalnum() or c in "-._") else "_" for c in td_id)


class FsStore:
    def __init__(self, url: str) -> None:
        self._fs, self._root = _open(url)  # (fsspec filesystem, base path)
        self._fs.makedirs(self._root, exist_ok=True)
        self._ids: set[str] = set()  # known td ids
        # id -> the path the document actually lives at. A file already in the
        # directory keeps the name it was given; only documents this store
        # writes get the canonical name. Without this, a hand named file is
        # discovered by _scan and then unreadable by _path.
        self._paths: dict[str, str] = {}
        self._subscribers: list[asyncio.Queue] = []
        # in-memory change log
        self._seq = 0
        self._seqs: dict[str, int] = {}
        self._tombstones: list[tuple[str, int]] = []
        self._scan()

    def _path(self, td_id: str) -> str:
        return self._paths.get(td_id) or self._canonical_path(td_id)

    def _canonical_path(self, td_id: str) -> str:
        return f"{self._root}/{_safe_name(td_id)}.td.json"

    def _scan(self) -> None:
        try:
            entries = self._fs.ls(self._root, detail=False)
        except FileNotFoundError:
            return
        for p in entries:
            if not str(p).endswith(".td.json"):
                continue
            try:
                td = json.loads(self._fs.cat_file(p))
            except Exception:  # unreadable / not JSON
                continue
            tid = td.get("id")
            if tid:
                self._ids.add(tid)
                self._paths[tid] = str(p)
                # Seed the change log too. A derived index replays from
                # changes_since(0), so a document that was already on disk has
                # to carry a seq or the index never learns it exists.
                self._seq += 1
                self._seqs[tid] = self._seq

    def _emit(self, event: str, td_id: str) -> None:
        for q in list(self._subscribers):
            q.put_nowait({"event": event, "id": td_id})

    async def _run(self, fn):
        return await asyncio.to_thread(fn)

    async def put(self, td_id: str, td: dict) -> bool:
        existed = td_id in self._ids
        path = self._path(td_id)
        await self._run(lambda: self._fs.pipe_file(path, json.dumps(td, indent=2).encode()))
        self._ids.add(td_id)
        self._paths[td_id] = path
        self._seq += 1
        self._seqs[td_id] = self._seq
        self._tombstones = [t for t in self._tombstones if t[0] != td_id]
        self._emit("updated" if existed else "created", td_id)
        return not existed

    async def get(self, td_id: str) -> dict | None:
        if td_id not in self._ids:
            return None
        try:
            return await self._run(lambda: json.loads(self._fs.cat_file(self._path(td_id))))
        except FileNotFoundError:
            return None

    async def delete(self, td_id: str) -> bool:
        if td_id not in self._ids:
            return False
        try:
            await self._run(lambda: self._fs.rm_file(self._path(td_id)))
        except FileNotFoundError:
            pass
        self._ids.discard(td_id)
        self._paths.pop(td_id, None)
        self._seq += 1
        self._seqs.pop(td_id, None)
        self._tombstones.append((td_id, self._seq))
        self._emit("deleted", td_id)
        return True

    async def list(self, *, limit: int | None = None, offset: int = 0) -> list[dict]:
        ids = sorted(self._ids)[offset : offset + limit if limit is not None else None]
        out = []
        for tid in ids:
            td = await self.get(tid)
            if td is not None:
                out.append(td)
        return out

    async def page(self, *, after=None, limit: int = 100):
        ids = sorted(i for i in self._ids if after is None or i > after)[:limit]
        tds = []
        for tid in ids:
            td = await self.get(tid)
            if td is not None:
                tds.append(td)
        nxt = ids[-1] if len(ids) == limit else None
        return tds, nxt

    async def count(self) -> int:
        return len(self._ids)

    async def search(self, jsonpath: str) -> list[dict]:
        expr = jsonpath_parse(jsonpath)
        out = []
        for tid in sorted(self._ids):
            td = await self.get(tid)
            if td is not None and expr.find(td):
                out.append(td)
        return out

    async def changes_since(self, cursor: int) -> tuple[int, list[tuple]]:
        changes: list[tuple] = []
        for tid, seq in self._seqs.items():
            if seq > cursor:
                changes.append((tid, await self.get(tid), seq))
        for tid, seq in self._tombstones:
            if seq > cursor:
                changes.append((tid, None, seq))
        changes.sort(key=lambda c: c[2])
        return self._seq, changes

    async def events(self) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.remove(q)


def _open(url: str):
    """Return the filesystem and base path for a store URL.

    A bare path uses the local filesystem.
    """
    import fsspec

    if "://" not in url:
        url = "file://" + url
    fs, _, paths = fsspec.get_fs_token_paths(url)
    return fs, paths[0]
