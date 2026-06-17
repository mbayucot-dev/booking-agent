"""Checkpointer configuration.

Domain models threaded through graph state get serialized into the checkpoint.
We register them via an explicit ``allowed_msgpack_modules`` allowlist so they
survive when LangGraph makes strict deserialization the default (it allows
arbitrary types today but will block them in a future version).
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from .availability_provider import Staff
from .state import (
    ApprovalState,
    AvailabilityResult,
    BookingRequest,
    PreparedAction,
    Slot,
    ValidationResult,
)

# Every non-builtin type that can land in BookingState and be checkpointed.
CHECKPOINT_ALLOWLIST = [
    BookingRequest,
    ValidationResult,
    Slot,
    AvailabilityResult,
    PreparedAction,
    ApprovalState,
    Staff,
]

# Constructor allowlist → silent (de)serialization for our types.
CHECKPOINT_SERDE = JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_ALLOWLIST)


def default_checkpointer() -> BaseCheckpointSaver:
    """In-process checkpointer with our domain types allow-listed. Production can
    inject a durable (e.g. Postgres) saver built with the same ``CHECKPOINT_SERDE``."""
    return MemorySaver(serde=CHECKPOINT_SERDE)


def build_postgres_checkpointer(database_url: str) -> BaseCheckpointSaver:
    """Durable Postgres-backed saver: paused (awaiting-approval) runs survive a
    restart and are resumable on any replica. Built on a small connection pool so
    it lives for the app's lifetime; ``setup()`` provisions the checkpoint tables."""
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        database_url,
        max_size=4,
        # PostgresSaver runs each op autocommit and expects dict rows.
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    saver = PostgresSaver(conn=pool, serde=CHECKPOINT_SERDE)
    saver.setup()
    return saver


def build_checkpointer(settings) -> BaseCheckpointSaver:
    """Select the saver by config: durable Postgres when DATABASE_URL is Postgres,
    else the in-process MemorySaver (SQLite/dev — unchanged default)."""
    if settings.is_postgres:
        return build_postgres_checkpointer(settings.database_url)
    return default_checkpointer()
