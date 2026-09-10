"""Infrastructure adapters for canonical service contracts."""

from .schema_preflight import SchemaPreflightReport, inspect_database_schema
from .sqlite import Store

__all__ = ["SchemaPreflightReport", "Store", "inspect_database_schema"]
