"""Store TDs through a SQLAlchemy engine."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator


def _loads(v):
    # some drivers return TEXT as str; a few coerce to dict already
    return v if isinstance(v, dict) else json.loads(v)


# Type-mapped Table objects so DDL is correct per dialect (mssql differs).
def _schema():
    from sqlalchemy import BigInteger, Column, MetaData, String, Table, Text

    md = MetaData()
    Table(
        "things",
        md,
        Column("id", String(512), primary_key=True),
        Column("td", Text, nullable=False),
        Column("seq", BigInteger, nullable=False),
    )
    Table("thing_tombstones", md, Column("id", String(512)), Column("seq", BigInteger))
    Table("thing_seq", md, Column("n", BigInteger, nullable=False))
    return md


class SqlStore:
    def __init__(self, url: str) -> None:
        from sqlalchemy import create_engine

        self._engine = create_engine(url, future=True)
        self.dialect = self._engine.dialect.name
        self._subscribers: list[asyncio.Queue] = []
        self._setup()

    def _setup(self) -> None:
        from sqlalchemy import text

        _schema().create_all(self._engine, checkfirst=True)  # per-dialect DDL
        with self._engine.begin() as c:
            row = c.execute(text("SELECT n FROM thing_seq")).fetchone()
            if row is None:
                c.execute(text("INSERT INTO thing_seq (n) VALUES (0)"))

    def _next_seq(self, c) -> int:
        from sqlalchemy import text

        c.execute(text("UPDATE thing_seq SET n = n + 1"))
        return c.execute(text("SELECT n FROM thing_seq")).fetchone()[0]

    def _emit(self, event: str, td_id: str) -> None:
        for q in list(self._subscribers):
            q.put_nowait({"event": event, "id": td_id})

    async def _run(self, fn):
        return await asyncio.to_thread(fn)

    async def put(self, td_id: str, td: dict) -> bool:
        from sqlalchemy import text

        def _do():
            with self._engine.begin() as c:
                existed = (
                    c.execute(text("SELECT 1 FROM things WHERE id = :id"), {"id": td_id}).fetchone()
                    is not None
                )
                seq = self._next_seq(c)
                if existed:
                    c.execute(
                        text("UPDATE things SET td = :td, seq = :s WHERE id = :id"),
                        {"td": json.dumps(td), "s": seq, "id": td_id},
                    )
                else:
                    c.execute(
                        text("INSERT INTO things (id, td, seq) VALUES (:id, :td, :s)"),
                        {"id": td_id, "td": json.dumps(td), "s": seq},
                    )
                return not existed

        created = await self._run(_do)
        self._emit("created" if created else "updated", td_id)
        return created

    async def get(self, td_id: str) -> dict | None:
        from sqlalchemy import text

        def _do():
            with self._engine.connect() as c:
                row = c.execute(
                    text("SELECT td FROM things WHERE id = :id"), {"id": td_id}
                ).fetchone()
                return _loads(row[0]) if row else None

        return await self._run(_do)

    async def delete(self, td_id: str) -> bool:
        from sqlalchemy import text

        def _do():
            with self._engine.begin() as c:
                n = c.execute(text("DELETE FROM things WHERE id = :id"), {"id": td_id}).rowcount
                if n:
                    seq = self._next_seq(c)
                    c.execute(
                        text("INSERT INTO thing_tombstones (id, seq) VALUES (:id, :s)"),
                        {"id": td_id, "s": seq},
                    )
                return n > 0

        removed = await self._run(_do)
        if removed:
            self._emit("deleted", td_id)
        return removed

    async def list(self, *, limit: int | None = None, offset: int = 0) -> list[dict]:

        # builder emits per-dialect limit/offset (mssql: OFFSET..FETCH).
        from sqlalchemy import column, select, table

        t = table("things", column("td"), column("id"))
        stmt = select(t.c.td).order_by(t.c.id)
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        def _do():
            with self._engine.connect() as c:
                return [_loads(r[0]) for r in c.execute(stmt).fetchall()]

        return await self._run(_do)

    async def page(self, *, after: str | None = None, limit: int = 100):
        # keyset pagination: WHERE id > :after ORDER BY id LIMIT n , O(page)
        from sqlalchemy import column, select, table

        t = table("things", column("td"), column("id"))
        stmt = select(t.c.id, t.c.td).order_by(t.c.id).limit(limit)
        if after is not None:
            stmt = stmt.where(t.c.id > after)

        def _do():
            with self._engine.connect() as c:
                rows = c.execute(stmt).fetchall()
            tds = [_loads(r[1]) for r in rows]
            nxt = rows[-1][0] if len(rows) == limit else None
            return tds, nxt

        return await self._run(_do)

    async def count(self) -> int:
        from sqlalchemy import text

        def _do():
            with self._engine.connect() as c:
                return c.execute(text("SELECT count(*) FROM things")).fetchone()[0]

        return await self._run(_do)

    async def search(self, jsonpath: str) -> list[dict]:
        """Search by JSONPath using the database's JSON query syntax."""
        from sqlalchemy import text

        d = self.dialect
        if d == "postgresql":
            pred = "CAST(td AS JSONB) @? CAST(:q AS jsonpath)"
        elif d == "sqlite":
            # json_type is non-NULL only when the path exists.
            pred = "json_type(td, :q) IS NOT NULL"
        elif d == "mssql":
            # JSON_VALUE (scalars) or JSON_QUERY (objects) , either = exists.
            pred = "(JSON_VALUE(td, :q) IS NOT NULL OR JSON_QUERY(td, :q) IS NOT NULL)"
        elif d in ("mysql", "mariadb"):
            pred = "JSON_EXTRACT(td, :q) IS NOT NULL"
        else:
            raise NotImplementedError(f"JSONPath search not wired for dialect {d!r}")
        q = jsonpath

        def _do():
            with self._engine.connect() as c:
                rows = c.execute(
                    text(f"SELECT td FROM things WHERE {pred} ORDER BY id"), {"q": q}
                ).fetchall()
                return [_loads(r[0]) for r in rows]

        return await self._run(_do)

    async def changes_since(self, cursor: int) -> tuple[int, list[tuple]]:
        from sqlalchemy import text

        def _do():
            with self._engine.connect() as c:
                rows = c.execute(
                    text("SELECT id, td, seq FROM things WHERE seq > :s"), {"s": cursor}
                ).fetchall()
                tombs = c.execute(
                    text("SELECT id, seq FROM thing_tombstones WHERE seq > :s"), {"s": cursor}
                ).fetchall()
            changes = [(r[0], _loads(r[1]), r[2]) for r in rows]
            changes += [(t[0], None, t[1]) for t in tombs]
            changes.sort(key=lambda ch: ch[2])
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
