"""
DataPilot — PostgreSQL Connector
===================================
Implements BaseConnector for PostgreSQL.

Also works with:
- Amazon Redshift (PostgreSQL-compatible wire protocol)
- CockroachDB (PostgreSQL-compatible)
- TimescaleDB (PostgreSQL extension)
- Supabase (hosted PostgreSQL)
- Neon (serverless PostgreSQL)
- AlloyDB (Google's PostgreSQL-compatible)

PostgreSQL-specific features:
- information_schema + pg_catalog for rich metadata
- pg_stat_user_tables for row counts and table sizes
- pg_description for column/table comments
- EXPLAIN for query cost estimation
"""

import time
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, date
from decimal import Decimal
import uuid

import psycopg2
import psycopg2.extras

from connectors.base import (
    BaseConnector, SchemaMetadata, TableInfo, ColumnInfo, QueryResult
)

logger = logging.getLogger("datapilot.connector.postgresql")


POSTGRESQL_DIALECT_HINTS = """POSTGRESQL SQL RULES — follow these exactly:
- Use ILIKE for case-insensitive string matching
- Use :: for type casting (e.g., col::DATE, col::TEXT, col::NUMERIC)
- Use NOW() or CURRENT_TIMESTAMP for current timestamp, CURRENT_DATE for today
- Use DATE_TRUNC('month', col) for date truncation
- Use EXTRACT(YEAR FROM col) to extract date parts
- Use AGE(end, start) for interval calculation
- Use COALESCE for null handling
- Use CONCAT or || for string concatenation
- String literals use single quotes: 'value'
- Identifiers use double quotes when needed: "Column Name"
- Use LIMIT and OFFSET for pagination (not TOP)
- Use DISTINCT ON (col) for deduplication per group
- Use FILTER (WHERE ...) with aggregates for conditional aggregation
- Use LATERAL JOIN for correlated subqueries
- Use generate_series() for sequence generation
- Use string_agg(col, ', ') for group concatenation
- PostgreSQL is case-sensitive for quoted identifiers, case-insensitive for unquoted (stored lowercase)
- Use to_char(col, 'YYYY-MM-DD') for date formatting
- Use INTERVAL '30 days' for date arithmetic (e.g., CURRENT_DATE - INTERVAL '30 days')
- Boolean values are TRUE/FALSE (not 1/0)
- Use BOOL_OR, BOOL_AND for boolean aggregation
- Use PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY col) for median
"""


class PostgreSQLConnector(BaseConnector):
    """PostgreSQL database connector."""

    def __init__(self, settings):
        super().__init__(settings)

    # ── Connection ───────────────────────────────────────

    def connect(self):
        host = self.settings.db_host
        port = self.settings.db_port
        logger.info(f"Connecting to PostgreSQL: {host}:{port}/{self.settings.db_database}")

        conn_params = {
            "host": host,
            "port": port,
            "dbname": self.settings.db_database,
            "user": self.settings.db_user,
            "password": self.settings.db_password,
            "connect_timeout": 15,
            "options": f"-c statement_timeout={self.settings.db_query_timeout * 1000}",  # milliseconds
        }

        # SSL support
        ssl_mode = getattr(self.settings, "db_ssl_mode", "prefer")
        if ssl_mode:
            conn_params["sslmode"] = ssl_mode

        self._connection = psycopg2.connect(**conn_params)
        # Use autocommit for read-only queries (no transaction overhead)
        self._connection.autocommit = True
        logger.info("PostgreSQL connected")

    def disconnect(self):
        if self._connection and not self._connection.closed:
            self._connection.close()
            self._connection = None
            logger.info("PostgreSQL disconnected")

    def is_connected(self) -> bool:
        if self._connection is None:
            return False
        try:
            return not self._connection.closed
        except Exception:
            return False

    # ── Schema Discovery ─────────────────────────────────

    def discover_tables(self) -> List[TableInfo]:
        self.ensure_connected()
        schema = self.settings.db_schema

        cur = self._connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            # Combine information_schema with pg_stat for row counts/sizes
            cur.execute("""
                SELECT
                    t.table_name,
                    t.table_type,
                    COALESCE(s.n_live_tup, 0) AS row_count,
                    COALESCE(pg_total_relation_size(quote_ident(t.table_schema) || '.' || quote_ident(t.table_name)), 0) AS size_bytes,
                    COALESCE(obj_description(
                        (quote_ident(t.table_schema) || '.' || quote_ident(t.table_name))::regclass
                    ), '') AS comment
                FROM information_schema.tables t
                LEFT JOIN pg_stat_user_tables s
                    ON t.table_schema = s.schemaname
                    AND t.table_name = s.relname
                WHERE t.table_schema = %s
                  AND t.table_type IN ('BASE TABLE', 'VIEW')
                ORDER BY t.table_name
            """, (schema,))

            tables = []
            for row in cur.fetchall():
                tables.append(TableInfo(
                    name=row["table_name"],
                    table_type=row["table_type"],
                    schema_name=schema,
                    row_count=row["row_count"],
                    size_bytes=row["size_bytes"],
                    comment=row["comment"] or "",
                ))
            logger.info(f"Discovered {len(tables)} tables")
            return tables

        finally:
            cur.close()

    def discover_columns(self, table_name: str) -> List[ColumnInfo]:
        self.ensure_connected()
        schema = self.settings.db_schema

        cur = self._connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            # Get columns + their comments from pg_description
            cur.execute("""
                SELECT
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.character_maximum_length,
                    c.numeric_precision,
                    c.numeric_scale,
                    c.column_default,
                    c.ordinal_position,
                    COALESCE(
                        col_description(
                            (quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass,
                            c.ordinal_position
                        ), ''
                    ) AS comment
                FROM information_schema.columns c
                WHERE c.table_schema = %s
                  AND c.table_name = %s
                ORDER BY c.ordinal_position
            """, (schema, table_name))

            columns = []
            for row in cur.fetchall():
                dtype = row["data_type"]
                if row.get("character_maximum_length"):
                    dtype = f"{dtype}({row['character_maximum_length']})"
                elif row.get("numeric_precision") and row.get("numeric_scale"):
                    dtype = f"{dtype}({row['numeric_precision']},{row['numeric_scale']})"

                columns.append(ColumnInfo(
                    name=row["column_name"],
                    data_type=dtype,
                    nullable=row["is_nullable"] == "YES",
                    comment=row["comment"] or "",
                    default=row.get("column_default"),
                    ordinal=row["ordinal_position"],
                ))
            return columns

        finally:
            cur.close()

    def discover_primary_keys(self, table_name: str) -> List[str]:
        self.ensure_connected()
        schema = self.settings.db_schema

        cur = self._connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("""
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = %s
                  AND tc.table_name = %s
                  AND tc.constraint_type = 'PRIMARY KEY'
                ORDER BY kcu.ordinal_position
            """, (schema, table_name))
            return [row["column_name"] for row in cur.fetchall()]
        except Exception:
            return []
        finally:
            cur.close()

    def discover_foreign_keys(self, table_name: str) -> List[Dict[str, str]]:
        self.ensure_connected()
        schema = self.settings.db_schema

        cur = self._connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("""
                SELECT
                    kcu.column_name AS fk_column,
                    ccu.table_name AS pk_table,
                    ccu.column_name AS pk_column
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                    AND tc.table_schema = ccu.table_schema
                WHERE tc.table_schema = %s
                  AND tc.table_name = %s
                  AND tc.constraint_type = 'FOREIGN KEY'
            """, (schema, table_name))
            return [
                {"column": row["fk_column"], "references": f"{row['pk_table']}.{row['pk_column']}"}
                for row in cur.fetchall()
            ]
        except Exception:
            return []
        finally:
            cur.close()

    def sample_column_values(
        self, table_name: str, column_name: str, n: int = 5
    ) -> List[str]:
        """PostgreSQL-optimized sampling."""
        self.ensure_connected()
        schema = self.settings.db_schema

        cur = self._connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            # Use parameterized identifiers safely
            # (can't parameterize identifiers, but we validated table/col names from info_schema)
            cur.execute(
                f'SELECT DISTINCT "{column_name}" AS val '
                f'FROM "{schema}"."{table_name}" '
                f'WHERE "{column_name}" IS NOT NULL '
                f'LIMIT {n}'
            )
            return [str(row["val"]) for row in cur.fetchall()]
        except Exception:
            return []
        finally:
            cur.close()

    # ── Query Execution ──────────────────────────────────

    def execute_query(self, sql: str) -> QueryResult:
        self.ensure_connected()
        start = time.time()

        try:
            cur = self._connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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

            # Serialize Python types to JSON-safe values
            clean_rows = []
            for row in rows:
                clean = {}
                for k, v in row.items():
                    if isinstance(v, (datetime, date)):
                        clean[k] = v.isoformat()
                    elif isinstance(v, Decimal):
                        clean[k] = float(v)
                    elif isinstance(v, uuid.UUID):
                        clean[k] = str(v)
                    elif isinstance(v, bytes):
                        clean[k] = v.hex()
                    elif isinstance(v, (list, dict)):
                        clean[k] = str(v)
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

        except psycopg2.Error as e:
            elapsed = (time.time() - start) * 1000
            error_msg = str(e).strip()
            logger.error(f"PostgreSQL error: {error_msg}")
            # Reset connection on error (psycopg2 needs this)
            try:
                self._connection.rollback()
            except Exception:
                pass
            return QueryResult(
                columns=[], rows=[], row_count=0,
                execution_time_ms=elapsed, query=sql, error=error_msg,
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return QueryResult(
                columns=[], rows=[], row_count=0,
                execution_time_ms=elapsed, query=sql, error=str(e),
            )

    # ── Dialect ──────────────────────────────────────────

    def get_dialect(self) -> str:
        return "postgresql"

    def get_dialect_hints(self) -> str:
        return POSTGRESQL_DIALECT_HINTS
