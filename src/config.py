"""
DataPilot — Configuration
==========================
All settings via environment variables or .env file.
Zero paid dependencies. Enterprise-grade security defaults.

Database settings use a universal 'db_' prefix.
Snowflake-specific fields (account, warehouse, role) are ignored by other connectors.
PostgreSQL-specific fields (host, port, ssl_mode) are ignored by Snowflake.
"""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings — all configurable via environment variables."""

    # ── Application ──────────────────────────────────────
    app_name: str = "DataPilot"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_level: str = "INFO"

    # ══════════════════════════════════════════════════════
    # DATABASE — Universal settings (works for any source)
    # ══════════════════════════════════════════════════════

    # Source type: "snowflake" | "postgresql" | "mysql" | "bigquery" | ...
    db_source: str = "snowflake"

    # Common across ALL sources
    db_user: str = ""
    db_password: str = ""
    db_database: str = ""
    db_schema: str = "public"

    # PostgreSQL / MySQL / SQL Server / ClickHouse
    db_host: str = "localhost"
    db_port: int = 5432
    db_ssl_mode: str = "prefer"

    # Snowflake-specific (ignored by other connectors)
    db_account: str = ""
    db_warehouse: str = ""
    db_role: str = ""

    # Query safety (universal)
    db_query_timeout: int = 30
    max_result_rows: int = 10000

    # ══════════════════════════════════════════════════════
    # LLM PROVIDER
    # ══════════════════════════════════════════════════════
    llm_provider: str = "groq"
    llm_model: str = "llama-3.3-70b-versatile"
    temperature: float = 0.0
    api_key: str = ""
    base_url: str = ""

    # ── Embeddings (local, free) ─────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── Vector Store ─────────────────────────────────────
    chroma_persist_dir: Path = Path("./data/chroma_db")
    chunk_size: int = 800
    chunk_overlap: int = 150

    # ── Cache ────────────────────────────────────────────
    cache_enabled: bool = True
    cache_ttl: int = 3600
    cache_max_entries: int = 500

    # ── Query Safety ─────────────────────────────────────
    max_query_complexity: int = 5
    blocked_keywords: str = "DROP,DELETE,INSERT,UPDATE,ALTER,CREATE,TRUNCATE,GRANT,REVOKE,EXEC,EXECUTE,MERGE,COPY,PUT,REMOVE"
    max_conversation_turns: int = 20

    # ── Schema Discovery ─────────────────────────────────
    schema_refresh_interval: int = 3600
    include_sample_values: bool = True
    sample_value_count: int = 5

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_prefix = "DATAPILOT_"
