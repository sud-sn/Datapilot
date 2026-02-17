"""
DataPilot — Abstract Base Connector
======================================
Every database connector implements this interface.
Adding a new source = create one file that inherits BaseConnector.

This is the ONLY contract between DataPilot core and any database.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ColumnInfo:
    """Metadata for a single column."""
    name: str
    data_type: str
    nullable: bool = True
    comment: str = ""
    default: Optional[str] = None
    ordinal: int = 0
    sample_values: List[str] = field(default_factory=list)


@dataclass
class TableInfo:
    """Metadata for a single table or view."""
    name: str
    table_type: str = "BASE TABLE"      # BASE TABLE | VIEW
    schema_name: str = ""
    row_count: int = 0
    size_bytes: int = 0
    comment: str = ""
    columns: Dict[str, ColumnInfo] = field(default_factory=dict)
    primary_keys: List[str] = field(default_factory=list)
    foreign_keys: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class SchemaMetadata:
    """Complete schema metadata for a database/schema."""
    source_type: str                     # "snowflake", "postgresql", etc.
    database: str
    schema_name: str
    discovered_at: str = ""
    tables: Dict[str, TableInfo] = field(default_factory=dict)

    def table_count(self) -> int:
        return len(self.tables)

    def column_count(self) -> int:
        return sum(len(t.columns) for t in self.tables.values())


@dataclass
class QueryResult:
    """Universal query result from any connector."""
    columns: List[str]
    rows: List[Dict[str, Any]]
    row_count: int
    execution_time_ms: float
    truncated: bool = False
    query: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "execution_time_ms": self.execution_time_ms,
            "truncated": self.truncated,
            "query": self.query,
            "error": self.error,
        }

    @property
    def is_empty(self) -> bool:
        return len(self.rows) == 0

    @property
    def is_single_value(self) -> bool:
        return len(self.rows) == 1 and len(self.columns) == 1

    @property
    def single_value(self) -> Any:
        if self.is_single_value:
            return self.rows[0][self.columns[0]]
        return None


class BaseConnector(ABC):
    """
    Abstract base class for all database connectors.

    To add a new database source:
    1. Create a file in src/connectors/ (e.g., mysql_connector.py)
    2. Inherit from BaseConnector
    3. Implement all abstract methods
    4. Register in src/connectors/factory.py
    That's it.
    """

    def __init__(self, settings):
        self.settings = settings
        self._connection = None

    # ── Connection Management ────────────────────────────

    @abstractmethod
    def connect(self):
        """Establish connection to the database."""
        pass

    @abstractmethod
    def disconnect(self):
        """Close the database connection."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connection is active."""
        pass

    def ensure_connected(self):
        """Reconnect if disconnected."""
        if not self.is_connected():
            self.connect()

    # ── Schema Discovery ─────────────────────────────────

    @abstractmethod
    def discover_tables(self) -> List[TableInfo]:
        """
        Discover all tables and views in the configured schema.
        Must return TableInfo with at minimum: name, table_type, row_count.
        """
        pass

    @abstractmethod
    def discover_columns(self, table_name: str) -> List[ColumnInfo]:
        """
        Discover all columns for a specific table.
        Must return ColumnInfo with at minimum: name, data_type, nullable.
        """
        pass

    @abstractmethod
    def discover_primary_keys(self, table_name: str) -> List[str]:
        """Return list of primary key column names for a table."""
        pass

    @abstractmethod
    def discover_foreign_keys(self, table_name: str) -> List[Dict[str, str]]:
        """
        Return foreign key relationships for a table.
        Each FK is: {"column": "col_name", "references": "other_table.other_col"}
        """
        pass

    def sample_column_values(
        self, table_name: str, column_name: str, n: int = 5
    ) -> List[str]:
        """
        Get N distinct sample values for a column.
        Override for source-specific optimizations.
        Default implementation uses a simple SELECT DISTINCT.
        """
        try:
            result = self.execute_query(
                f'SELECT DISTINCT "{column_name}" AS val '
                f'FROM "{table_name}" '
                f'WHERE "{column_name}" IS NOT NULL '
                f'LIMIT {n}'
            )
            if result.error:
                return []
            return [str(row.get("val", "")) for row in result.rows]
        except Exception:
            return []

    # ── Query Execution ──────────────────────────────────

    @abstractmethod
    def execute_query(self, sql: str) -> QueryResult:
        """
        Execute a SQL query and return results.
        Must handle timeouts, row limits, and error formatting.
        """
        pass

    # ── SQL Dialect Info ─────────────────────────────────

    @abstractmethod
    def get_dialect(self) -> str:
        """
        Return the SQL dialect name.
        Used by the SQL generator to produce dialect-correct SQL.
        E.g., "snowflake", "postgresql", "mysql", "tsql", "bigquery"
        """
        pass

    @abstractmethod
    def get_dialect_hints(self) -> str:
        """
        Return dialect-specific SQL hints for the LLM.
        These are appended to the SQL generation prompt.

        E.g., for PostgreSQL:
        "Use ILIKE for case-insensitive matching.
         Use :: for type casting (e.g., column::DATE).
         Use NOW() for current timestamp."
        """
        pass

    # ── Full Schema Discovery (Orchestrated) ─────────────

    def discover_full_schema(self, include_samples: bool = True) -> SchemaMetadata:
        """
        Run complete schema discovery.
        This is the main entry point — calls all the individual methods.
        """
        self.ensure_connected()

        metadata = SchemaMetadata(
            source_type=self.get_dialect(),
            database=getattr(self.settings, "db_database", ""),
            schema_name=getattr(self.settings, "db_schema", ""),
            discovered_at=datetime.utcnow().isoformat(),
        )

        # 1. Discover all tables
        tables = self.discover_tables()
        for table in tables:
            metadata.tables[table.name] = table

        # 2. Discover columns for each table
        for table_name, table_info in metadata.tables.items():
            columns = self.discover_columns(table_name)
            for col in columns:
                table_info.columns[col.name] = col

        # 3. Discover primary keys
        for table_name, table_info in metadata.tables.items():
            try:
                table_info.primary_keys = self.discover_primary_keys(table_name)
            except Exception:
                pass

        # 4. Discover foreign keys
        for table_name, table_info in metadata.tables.items():
            try:
                table_info.foreign_keys = self.discover_foreign_keys(table_name)
            except Exception:
                pass

        # 5. Sample column values
        if include_samples:
            sample_n = getattr(self.settings, "sample_value_count", 5)
            for table_name, table_info in metadata.tables.items():
                for col_name, col_info in table_info.columns.items():
                    # Skip binary/complex types
                    skip_types = ("bytea", "blob", "binary", "variant", "object", "array")
                    if any(t in col_info.data_type.lower() for t in skip_types):
                        continue
                    col_info.sample_values = self.sample_column_values(
                        table_name, col_name, sample_n
                    )

        return metadata
