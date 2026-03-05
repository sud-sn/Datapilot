"""
DataPilot — Connector Factory
================================
Creates the appropriate database connector based on configuration.

To add a new data source:
  1. Create src/connectors/your_connector.py implementing BaseConnector
  2. Register it in CONNECTOR_REGISTRY below
  3. Add settings in config.py
  That's it. Everything else works automatically.
"""

import logging
from typing import Dict, Type

from connectors.base import BaseConnector

logger = logging.getLogger("datapilot.connector.factory")

# ── Registry of all available connectors ─────────────────
# Key = source type name (matches DATAPILOT_DB_SOURCE env var)
# Value = (module_path, class_name)
# Lazy-loaded to avoid importing drivers that aren't installed.

CONNECTOR_REGISTRY: Dict[str, tuple] = {
    "snowflake":  ("connectors.snowflake_connector", "SnowflakeConnector"),
    "postgresql":  ("connectors.postgres_connector",  "PostgreSQLConnector"),
    "postgres":    ("connectors.postgres_connector",  "PostgreSQLConnector"),  # alias
    "sqlserver":   ("connectors.sqlserver_connector", "SQLServerConnector"),
    # ── Future connectors (uncomment when implemented) ───
    # "mysql":       ("connectors.mysql_connector",      "MySQLConnector"),
    # "bigquery":    ("connectors.bigquery_connector",   "BigQueryConnector"),
    # "redshift":    ("connectors.redshift_connector",   "RedshiftConnector"),
    # "clickhouse":  ("connectors.clickhouse_connector", "ClickHouseConnector"),
    # "databricks":  ("connectors.databricks_connector", "DatabricksConnector"),
    # "duckdb":      ("connectors.duckdb_connector",     "DuckDBConnector"),
    # "oracle":      ("connectors.oracle_connector",     "OracleConnector"),
}


def create_connector(settings) -> BaseConnector:
    """
    Create a database connector based on settings.db_source.

    Raises:
        ValueError: If the source type is not supported or driver not installed.
    """
    source = settings.db_source.lower().strip()

    if source not in CONNECTOR_REGISTRY:
        supported = sorted(set(CONNECTOR_REGISTRY.keys()))
        raise ValueError(
            f"Unsupported data source: '{source}'. "
            f"Supported sources: {', '.join(supported)}"
        )

    module_path, class_name = CONNECTOR_REGISTRY[source]

    try:
        import importlib
        module = importlib.import_module(module_path)
        connector_class = getattr(module, class_name)
    except ImportError as e:
        # Provide helpful error with install instructions
        install_hints = {
            "snowflake":  "pip install snowflake-connector-python",
            "postgresql": "pip install psycopg2-binary",
            "postgres":   "pip install psycopg2-binary",
            "mysql":      "pip install mysql-connector-python",
            "bigquery":   "pip install google-cloud-bigquery",
            "sqlserver":  "pip install pyodbc",
            "clickhouse": "pip install clickhouse-connect",
            "oracle":     "pip install oracledb",
        }
        hint = install_hints.get(source, f"Install the Python driver for {source}")
        raise ImportError(
            f"Cannot load {source} connector. Driver not installed.\n"
            f"Fix: {hint}\n"
            f"Original error: {e}"
        ) from e

    logger.info(f"Creating {source} connector ({class_name})")
    connector = connector_class(settings)
    return connector


def list_supported_sources() -> Dict[str, bool]:
    """
    List all registered sources and whether their driver is installed.
    Useful for the /api/sources endpoint.
    """
    result = {}
    seen = set()

    for source, (module_path, class_name) in CONNECTOR_REGISTRY.items():
        if source in seen:
            continue
        seen.add(source)

        try:
            import importlib
            importlib.import_module(module_path)
            result[source] = True
        except ImportError:
            result[source] = False

    return result
