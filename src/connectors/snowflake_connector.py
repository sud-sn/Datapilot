"""
DataPilot — Snowflake Connector
==================================
Implements BaseConnector for Snowflake.

Snowflake-specific optimizations:
- TABLESAMPLE for large tables during column sampling
- INFORMATION_SCHEMA queries for metadata
- Certificate and session parameter support
- Snowflake SQL dialect hints for LLM
"""

import time
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

import snowflake.connector
from snowflake.connector import DictCursor

from connectors.base import (
    BaseConnector, SchemaMetadata, TableInfo, ColumnInfo, QueryResult
)

logger = logging.getLogger("datapilot.connector.snowflake")


SNOWFLAKE_DIALECT_HINTS = """SNOWFLAKE SQL RULES — follow these exactly:
- Use ILIKE for case-insensitive string matching (not LOWER(x) LIKE)
- Use TRY_CAST for safe type conversion, :: for direct casting (e.g., col::DATE)
- Use DATEADD, DATEDIFF, DATE_TRUNC for date operations
- Use CURRENT_DATE(), CURRENT_TIMESTAMP() for now
- Use QUALIFY with window functions for row filtering
- Use NVL or COALESCE for null handling
- Use IFF(condition, true_val, false_val) instead of IF
- String literals use single quotes: 'value'
- Identifiers use double quotes when needed: "Column Name"
- Use FLATTEN() for semi-structured data (VARIANT/ARRAY/OBJECT)
- Use PARSE_JSON() for JSON strings
- LIMIT goes at the end (no TOP keyword)
- Snowflake is case-insensitive for unquoted identifiers (stored as UPPERCASE)
"""


class SnowflakeConnector(BaseConnector):
    """Snowflake database connector."""

    def __init__(self, settings):
        super().__init__(settings)

    # ── Connection ───────────────────────────────────────

    def connect(self):
        logger.info(f"Connecting to Snowflake: {self.settings.db_account}")
        self._connection = snowflake.connector.connect(
            account=self.settings.db_account,
            user=self.settings.db_user,
            password=self.settings.db_password,
            warehouse=self.settings.db_warehouse,
            database=self.settings.db_database,
            schema=self.settings.db_schema,
            role=self.settings.db_role,
            network_timeout=self.settings.db_query_timeout,
            login_timeout=15,
            session_parameters={
                "QUERY_TAG": "DataPilot",
                "STATEMENT_TIMEOUT_IN_SECONDS": str(self.settings.db_query_timeout),
            },
        )
        logger.info("Snowflake connected")

    def disconnect(self):
        if self._connection and not self._connection.is_closed():
            self._connection.close()
            self._connection = None
            logger.info("Snowflake disconnected")

    def is_connected(self) -> bool:
        return self._connection is not None and not self._connection.is_closed()

    # ── Schema Discovery ─────────────────────────────────

    def discover_tables(self) -> List[TableInfo]:
        self.ensure_connected()
        cur = self._connection.cursor(DictCursor)
        db = self.settings.db_database
        schema = self.settings.db_schema

        try:
            cur.execute(f"""
                SELECT TABLE_NAME, TABLE_TYPE, ROW_COUNT, BYTES, COMMENT
                FROM {db}.INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = '{schema}'
                  AND TABLE_TYPE IN ('BASE TABLE', 'VIEW')
                ORDER BY TABLE_NAME
            """)

            tables = []
            for row in cur.fetchall():
                tables.append(TableInfo(
                    name=row["TABLE_NAME"],
                    table_type=row["TABLE_TYPE"],
                    schema_name=schema,
                    row_count=row.get("ROW_COUNT") or 0,
                    size_bytes=row.get("BYTES") or 0,
                    comment=row.get("COMMENT") or "",
                ))
            logger.info(f"Discovered {len(tables)} tables")
            return tables
        finally:
            cur.close()

    def discover_columns(self, table_name: str) -> List[ColumnInfo]:
        self.ensure_connected()
        cur = self._connection.cursor(DictCursor)
        db = self.settings.db_database
        schema = self.settings.db_schema

        try:
            cur.execute(f"""
                SELECT
                    COLUMN_NAME, DATA_TYPE, IS_NULLABLE,
                    CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE,
                    COLUMN_DEFAULT, COMMENT, ORDINAL_POSITION
                FROM {db}.INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = '{schema}'
                  AND TABLE_NAME = '{table_name}'
                ORDER BY ORDINAL_POSITION
            """)

            columns = []
            for row in cur.fetchall():
                dtype = row["DATA_TYPE"]
                if row.get("CHARACTER_MAXIMUM_LENGTH"):
                    dtype = f"{dtype}({row['CHARACTER_MAXIMUM_LENGTH']})"
                elif row.get("NUMERIC_PRECISION") and row.get("NUMERIC_SCALE"):
                    dtype = f"{dtype}({row['NUMERIC_PRECISION']},{row['NUMERIC_SCALE']})"

                columns.append(ColumnInfo(
                    name=row["COLUMN_NAME"],
                    data_type=dtype,
                    nullable=row["IS_NULLABLE"] == "YES",
                    comment=row.get("COMMENT") or "",
                    default=row.get("COLUMN_DEFAULT"),
                    ordinal=row["ORDINAL_POSITION"],
                ))
            return columns
        finally:
            cur.close()

    def discover_primary_keys(self, table_name: str) -> List[str]:
        self.ensure_connected()
        cur = self._connection.cursor(DictCursor)
        db = self.settings.db_database
        schema = self.settings.db_schema

        try:
            cur.execute(f"""
                SELECT kcu.COLUMN_NAME
                FROM {db}.INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                JOIN {db}.INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                    ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                    AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                WHERE tc.TABLE_SCHEMA = '{schema}'
                  AND tc.TABLE_NAME = '{table_name}'
                  AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                ORDER BY kcu.ORDINAL_POSITION
            """)
            return [row["COLUMN_NAME"] for row in cur.fetchall()]
        except Exception:
            return []
        finally:
            cur.close()

    def discover_foreign_keys(self, table_name: str) -> List[Dict[str, str]]:
        self.ensure_connected()
        cur = self._connection.cursor(DictCursor)
        db = self.settings.db_database
        schema = self.settings.db_schema

        try:
            cur.execute(f"""
                SELECT
                    kcu.COLUMN_NAME AS fk_column,
                    kcu2.TABLE_NAME AS pk_table,
                    kcu2.COLUMN_NAME AS pk_column
                FROM {db}.INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
                JOIN {db}.INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                    ON rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                    AND rc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA
                JOIN {db}.INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu2
                    ON rc.UNIQUE_CONSTRAINT_NAME = kcu2.CONSTRAINT_NAME
                    AND rc.UNIQUE_CONSTRAINT_SCHEMA = kcu2.CONSTRAINT_SCHEMA
                WHERE rc.CONSTRAINT_SCHEMA = '{schema}'
                  AND kcu.TABLE_NAME = '{table_name}'
            """)
            return [
                {"column": row["FK_COLUMN"], "references": f"{row['PK_TABLE']}.{row['PK_COLUMN']}"}
                for row in cur.fetchall()
            ]
        except Exception:
            return []
        finally:
            cur.close()

    def sample_column_values(
        self, table_name: str, column_name: str, n: int = 5
    ) -> List[str]:
        """Snowflake-optimized sampling with TABLESAMPLE for large tables."""
        self.ensure_connected()
        cur = self._connection.cursor(DictCursor)
        schema = self.settings.db_schema

        try:
            # Safe identifier quoting
            query = f"""
                SELECT DISTINCT "{column_name}" AS val
                FROM "{schema}"."{table_name}"
                WHERE "{column_name}" IS NOT NULL
                LIMIT {n}
            """
            cur.execute(query)
            return [str(row["VAL"]) for row in cur.fetchall()]
        except Exception:
            return []
        finally:
            cur.close()

    # ── Query Execution ──────────────────────────────────

    def execute_query(self, sql: str) -> QueryResult:
        self.ensure_connected()
        start = time.time()

        try:
            cur = self._connection.cursor(DictCursor)
            cur.execute(sql)

            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = cur.fetchmany(self.settings.max_result_rows)

            truncated = False
            try:
                if cur.fetchone():
                    truncated = True
            except Exception:
                pass

            elapsed = (time.time() - start) * 1000

            # Serialize
            clean_rows = []
            for row in rows:
                clean = {}
                for k, v in row.items():
                    if isinstance(v, datetime):
                        clean[k] = v.isoformat()
                    elif isinstance(v, bytes):
                        clean[k] = v.hex()
                    elif v is None:
                        clean[k] = None
                    else:
                        clean[k] = v
                clean_rows.append(clean)

            cur.close()
            logger.info(f"Query returned {len(clean_rows)} rows in {elapsed:.0f}ms")

            return QueryResult(
                columns=columns, rows=clean_rows, row_count=len(clean_rows),
                execution_time_ms=elapsed, truncated=truncated, query=sql,
            )

        except snowflake.connector.errors.ProgrammingError as e:
            elapsed = (time.time() - start) * 1000
            return QueryResult(
                columns=[], rows=[], row_count=0,
                execution_time_ms=elapsed, query=sql, error=str(e),
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return QueryResult(
                columns=[], rows=[], row_count=0,
                execution_time_ms=elapsed, query=sql, error=str(e),
            )

    # ── Dialect ──────────────────────────────────────────

    def get_dialect(self) -> str:
        return "snowflake"

    def get_dialect_hints(self) -> str:
        return SNOWFLAKE_DIALECT_HINTS
