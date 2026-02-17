"""
DataPilot — Schema Introspector (Source-Agnostic)
====================================================
Wraps any BaseConnector to discover and format schema metadata.
This module is INDEPENDENT of any specific database — all
source-specific logic lives in the connector.

Responsibilities:
- Caching schema metadata with TTL
- Building M-Schema format for LLM prompts
- Building per-table documents for RAG indexing
"""

import time
import logging
from typing import Dict, List, Optional

from connectors.base import BaseConnector, SchemaMetadata, TableInfo

logger = logging.getLogger("datapilot.schema")


class SchemaIntrospector:
    """Source-agnostic schema discovery and formatting."""

    def __init__(self, connector: BaseConnector, settings):
        self.connector = connector
        self.settings = settings
        self._cache: Optional[SchemaMetadata] = None
        self._cache_time: float = 0
        self._mschema_cache: Optional[str] = None

    def discover_schema(self, force_refresh: bool = False) -> SchemaMetadata:
        """Discover schema via the connector. Caches with TTL."""
        now = time.time()
        if (
            not force_refresh
            and self._cache
            and (now - self._cache_time) < self.settings.schema_refresh_interval
        ):
            return self._cache

        logger.info(f"Discovering schema via {self.connector.get_dialect()} connector...")
        metadata = self.connector.discover_full_schema(
            include_samples=self.settings.include_sample_values
        )
        self._cache = metadata
        self._cache_time = time.time()
        self._mschema_cache = None

        logger.info(
            f"Schema: {metadata.table_count()} tables, "
            f"{metadata.column_count()} columns "
            f"({self.connector.get_dialect()})"
        )
        return metadata

    def build_mschema(self, metadata: Optional[SchemaMetadata] = None) -> str:
        """
        Build M-Schema format — the state-of-the-art schema representation
        for LLM Text-to-SQL. Source-agnostic.
        """
        if self._mschema_cache and metadata is None:
            return self._mschema_cache

        if metadata is None:
            metadata = self.discover_schema()

        lines = []
        lines.append(f"SOURCE: {metadata.source_type.upper()}")
        lines.append(f"DATABASE: {metadata.database}")
        lines.append(f"SCHEMA: {metadata.schema_name}")
        lines.append("")

        for table_name, table_info in metadata.tables.items():
            # Table header
            ttype = "VIEW" if "VIEW" in table_info.table_type.upper() else "TABLE"
            header = f"{ttype}: {table_name}"
            if table_info.row_count:
                header += f" ({table_info.row_count:,} rows)"
            if table_info.comment:
                header += f' — "{table_info.comment}"'

            lines.append("═" * 60)
            lines.append(header)
            lines.append("═" * 60)

            # Build key lookup
            pk_set = set(table_info.primary_keys)
            fk_map = {fk["column"]: fk["references"] for fk in table_info.foreign_keys}

            lines.append("Columns:")
            for col_name, col_info in table_info.columns.items():
                parts = [f"  - {col_name} ({col_info.data_type}"]

                flags = []
                if col_name in pk_set:
                    flags.append("PK")
                if col_name in fk_map:
                    flags.append(f"FK → {fk_map[col_name]}")
                if not col_info.nullable:
                    flags.append("NOT NULL")
                if flags:
                    parts.append(f", {', '.join(flags)}")
                parts.append(")")

                if col_info.comment:
                    parts.append(f' — "{col_info.comment}"')

                if col_info.sample_values:
                    parts.append(f" | Examples: {', '.join(col_info.sample_values[:5])}")

                lines.append("".join(parts))

            if table_info.foreign_keys:
                lines.append("Relationships:")
                for fk in table_info.foreign_keys:
                    lines.append(f"  - {fk['column']} → {fk['references']}")
            lines.append("")

        result = "\n".join(lines)
        if metadata is None or metadata == self._cache:
            self._mschema_cache = result
        return result

    def build_schema_documents(self, metadata: Optional[SchemaMetadata] = None) -> List[Dict]:
        """Build per-table documents for RAG indexing."""
        if metadata is None:
            metadata = self.discover_schema()

        documents = []
        for table_name, table_info in metadata.tables.items():
            parts = [f"Table: {table_name}"]
            if table_info.comment:
                parts.append(f"Description: {table_info.comment}")
            parts.append(f"Type: {table_info.table_type}")
            parts.append(f"Row count: {table_info.row_count}")

            parts.append("Columns:")
            for col_name, col_info in table_info.columns.items():
                col_desc = f"  - {col_name}: {col_info.data_type}"
                if col_info.comment:
                    col_desc += f" ({col_info.comment})"
                if col_info.sample_values:
                    col_desc += f" [e.g., {', '.join(col_info.sample_values[:3])}]"
                parts.append(col_desc)

            if table_info.primary_keys:
                parts.append(f"Primary key: {', '.join(table_info.primary_keys)}")
            if table_info.foreign_keys:
                parts.append("Foreign keys:")
                for fk in table_info.foreign_keys:
                    parts.append(f"  - {fk['column']} references {fk['references']}")

            documents.append({
                "content": "\n".join(parts),
                "metadata": {
                    "table_name": table_name,
                    "type": table_info.table_type,
                    "row_count": table_info.row_count,
                    "column_count": len(table_info.columns),
                },
            })
        return documents

    def close(self):
        self.connector.disconnect()
