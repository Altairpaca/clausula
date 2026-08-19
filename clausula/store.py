"""Compatibility import for the SQLite storage adapter."""

from .adapters.sqlite import SCHEMA, SCHEMA_VERSION, Store

__all__ = ["SCHEMA", "SCHEMA_VERSION", "Store"]
