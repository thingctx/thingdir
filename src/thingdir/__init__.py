"""A W3C Thing Description Directory (TDD).

Serve WoT Thing Descriptions through the TDD API. Storage backends include
files via fsspec and SQL via SQLAlchemy.

Import the storage and search modules without loading the server stack.
"""

from thingdir.stores import FileStore, FsStore, Store


# build_app (FastAPI) and RdfIndex ([rdf] extra) load lazily, so importing a
# store or the index does not pull in the server stack or pyoxigraph.
def __getattr__(name):
    if name == "build_app":
        from thingdir.app import build_app

        return build_app
    if name == "RdfIndex":
        from thingdir.search import RdfIndex

        return RdfIndex
    raise AttributeError(name)


__all__ = ["build_app", "Store", "FsStore", "FileStore", "RdfIndex"]
