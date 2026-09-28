"""The storage protocol used by a directory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol


class Store(Protocol):
    """A backend that stores TDs by id and supports asynchronous I/O."""

    async def put(self, td_id: str, td: dict) -> bool:
        """Create or replace the TD at ``td_id``. Returns True if it was
        newly created, False if it replaced an existing one."""
        ...

    async def get(self, td_id: str) -> dict | None:
        """The TD at ``td_id``, or None if absent."""
        ...

    async def delete(self, td_id: str) -> bool:
        """Remove the TD. Returns True if something was removed."""
        ...

    async def list(self, *, limit: int | None = None, offset: int = 0) -> list[dict]:
        """Return TDs, optionally paginated.

        Use ``page`` for keyset pagination on large stores. Offset pagination
        takes time proportional to the offset.
        """
        ...

    async def page(
        self, *, after: str | None = None, limit: int = 100
    ) -> tuple[list[dict], str | None]:
        """Return one page of TDs ordered by id.

        Returns ``(tds, next_cursor)``. Pass the cursor as ``after`` to
        continue. The cursor is None when no more TDs remain.
        """
        ...

    async def count(self) -> int:
        """How many TDs are stored (for pagination headers)."""
        ...

    async def search(self, jsonpath: str) -> list[dict]:
        """TDs matching a JSONPath expression (the TDD
        `GET /search/jsonpath`). A backend may do this natively (Postgres
        jsonpath) or in Python (files)."""
        ...

    def events(self) -> AsyncIterator[dict]:
        """Stream lifecycle events with an event type and TD id."""
        ...

    async def changes_since(self, cursor) -> tuple[Any, list[Change]]:
        """Return changes after ``cursor`` for replay by a derived index.

        Returns ``(new_cursor, changes)``. Each change is
        ``(id, td_or_None, seq)``; ``td=None`` marks a deletion. Cursors are
        backend specific. A cursor of zero returns all changes.
        """
        ...


# A change record: (td_id, td or None for a delete, monotonic seq).
Change = tuple
