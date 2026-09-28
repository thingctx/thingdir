from thingdir.stores.base import Store
from thingdir.stores.fs import FsStore

# FileStore kept as a friendly alias: a local dir is just an fsspec URL.
FileStore = FsStore

__all__ = ["Store", "FsStore", "FileStore", "SqlStore", "MongoStore", "RedisStore"]


# SqlStore needs the [sql] extra (SQLAlchemy + a driver); import lazily.
def __getattr__(name):
    if name == "SqlStore":
        from thingdir.stores.sql import SqlStore

        return SqlStore
    if name == "MongoStore":
        from thingdir.stores.mongo import MongoStore

        return MongoStore
    if name == "RedisStore":
        from thingdir.stores.redis import RedisStore

        return RedisStore
    raise AttributeError(name)
