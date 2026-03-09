from __future__ import annotations

from sqlalchemy import JSON, Uuid
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


# Use PostgreSQL-native types when available, but stay SQLite-compatible for local runs.
JSONB = JSON().with_variant(PG_JSONB(), "postgresql")


def UUID(*, as_uuid: bool = True):
    return Uuid(as_uuid=as_uuid).with_variant(PG_UUID(as_uuid=as_uuid), "postgresql")


def ARRAY(item_type):
    element_type = item_type() if isinstance(item_type, type) else item_type
    return JSON().with_variant(PG_ARRAY(element_type), "postgresql")
