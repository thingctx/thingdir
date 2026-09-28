# Copyright 2026 The thingdir Authors
# SPDX-License-Identifier: Apache-2.0
"""The client and the directory against each other, which nothing else checks.

Each project tests itself. Nothing tested the shape they make together: a
directory holds the descriptions, and a client builds itself from the directory
and drives what it finds.

thingctx's TDDRegistry expects a list of descriptions at /things; this app
serves them; neither repository knows the other exists. That is exactly the
seam somebody could break without either suite noticing.

Skipped rather than failed when thingctx is absent, because thingdir does not
depend on it and a directory that refused to test itself alone would be the
wrong trade.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx
import pytest
import uvicorn

from thingdir import FileStore, build_app

thingctx = pytest.importorskip("thingctx", reason="the client tier is not installed")

from thingctx import LocalBinding, ThingClient  # noqa: E402
from thingctx.registry import TDDRegistry  # noqa: E402

ORDERS = "urn:example:orders:1"

TD = {
    "@context": "https://www.w3.org/2022/wot/td/v1.1",
    "id": ORDERS,
    "title": "Orders",
    "securityDefinitions": {"nosec_sc": {"scheme": "nosec"}},
    "security": ["nosec_sc"],
    "actions": {
        "reindex": {
            "idempotent": True,
            "forms": [{"href": "local://reindex", "op": ["invokeaction"]}],
        },
        "drain_queue": {
            "@type": "tc:Destructive",
            "forms": [{"href": "local://drain_queue", "op": ["invokeaction"]}],
        },
    },
}


@pytest.fixture
def directory(tmp_path: Any) -> Any:
    """A real server on a real port: the client speaks HTTP to it, not Python."""
    app = build_app(FileStore(str(tmp_path / "store")), sync_interval=0)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started and server.servers:
            break
        time.sleep(0.05)
    else:  # pragma: no cover - only on a machine that cannot bind a port
        pytest.fail("the directory never started")
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def _published(base: str) -> None:
    assert httpx.put(f"{base}/things/{ORDERS}", json=TD, timeout=10).status_code in (
        201,
        204,
    )


def test_a_client_builds_itself_from_what_the_directory_serves(directory: str) -> None:
    """The seam neither repository tests: /things, and what reads it.

    thingctx's TDDRegistry and this app were written apart. If either changes
    what a listing looks like, this is the only thing that notices.
    """
    _published(directory)
    client = ThingClient.from_registry(
        TDDRegistry(f"{directory}/things"), bindings=[LocalBinding()], approve_when="never"
    )
    assert [thing.id for thing in client.things] == [ORDERS]
    assert {a["function"]["name"] for a in client.list_actions()} == {
        "orders__reindex",
        "orders__drain_queue",
    }


def test_the_annotations_survive_the_directory(directory: str) -> None:
    """What a description says about danger has to survive the round trip.

    The annotation is written in one repository and stored and served by
    another. A consumer decides whether an action is safe to repeat by reading
    it, so anything that drops it on the way turns a destructive action into one
    a caller will happily reissue.
    """
    _published(directory)
    client = ThingClient.from_registry(
        TDDRegistry(f"{directory}/things"), bindings=[LocalBinding()], approve_when="never"
    )
    thing = next(t for t in client.things if t.id == ORDERS)
    assert thing.actions["reindex"].is_destructive() is False
    assert thing.actions["drain_queue"].is_destructive() is True
    assert thing.actions["drain_queue"].requires_approval() is True


def test_a_thing_added_later_is_found_by_the_next_client(directory: str) -> None:
    # The reason to run a directory at all. A list in a deployment does not do
    # this, and a client that cached the fleet would not either.
    _published(directory)
    second = dict(TD, id="urn:example:search:1", title="Search")
    httpx.put(f"{directory}/things/{second['id']}", json=second, timeout=10)

    client = ThingClient.from_registry(
        TDDRegistry(f"{directory}/things"), bindings=[LocalBinding()], approve_when="never"
    )
    assert {t.id for t in client.things} == {ORDERS, "urn:example:search:1"}
