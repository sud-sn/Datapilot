# DataPilot

**Ask your data anything. No dashboards. No SQL. Just answers.**

DataPilot connects to your database and lets anyone ask questions in plain English. It generates SQL, executes it safely, and returns answers with visualizations.

Supports: **Snowflake** · **PostgreSQL** (and any PG-compatible: Redshift, CockroachDB, Supabase, Neon, AlloyDB, TimescaleDB)

---

## How It Works

```
User: "What were total sales by region last quarter?"

   ┌──────────────────┐
   │  Natural language  │
   │  question          │
   └────────┬───────────┘
            │
   ┌────────▼───────────┐
   │  Schema Context     │ ← Auto-discovers tables, columns, types, sample values
   │  (M-Schema format)  │
   └────────┬───────────┘
            │
   ┌────────▼───────────┐
   │  LLM SQL Generator  │ ← Dialect-aware (Snowflake SQL vs PostgreSQL)
   │  (Groq free / etc)  │
   └────────┬───────────┘
            │
   ┌────────▼───────────┐
   │  Security Validator  │ ← 5-layer: blocks DDL/DML, injection, complexity
   └────────┬───────────┘
            │
   ┌────────▼───────────┐
   │  Query Executor      │ ← Runs against Snowflake or PostgreSQL
   └────────┬───────────┘
            │
   ┌────────▼───────────┐
   │  Response Synth      │ ← "Sales were $14.2M. APAC led with $5.8M..."
   └──────────────────────┘
```

---

## Quick Start

### 1. Install

```bash
git clone <your-repo-url>
cd datapilot

python -m venv venv
source venv/bin/activate       # Linux/Mac
# venv\Scripts\activate        # Windows

pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — set DB_SOURCE to "snowflake" or "postgresql" and fill credentials
```

### 3. Run

```bash
python src/app.py
```

Open **http://localhost:8000** and start asking questions.

---

## Database Configuration

### Snowflake

```env
DATAPILOT_DB_SOURCE=snowflake

DATAPILOT_DB_ACCOUNT=xy12345.us-east-1
DATAPILOT_DB_USER=your_user
DATAPILOT_DB_PASSWORD=your_password
DATAPILOT_DB_WAREHOUSE=COMPUTE_WH
DATAPILOT_DB_DATABASE=ANALYTICS_DB
DATAPILOT_DB_SCHEMA=PUBLIC
DATAPILOT_DB_ROLE=READONLY_ROLE
```

Recommended read-only role:

```sql
CREATE ROLE DATAPILOT_ROLE;
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE DATAPILOT_ROLE;
GRANT USAGE ON DATABASE ANALYTICS_DB TO ROLE DATAPILOT_ROLE;
GRANT USAGE ON SCHEMA ANALYTICS_DB.PUBLIC TO ROLE DATAPILOT_ROLE;
GRANT SELECT ON ALL TABLES IN SCHEMA ANALYTICS_DB.PUBLIC TO ROLE DATAPILOT_ROLE;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ANALYTICS_DB.PUBLIC TO ROLE DATAPILOT_ROLE;

CREATE USER datapilot_user PASSWORD='secure_pass' DEFAULT_ROLE=DATAPILOT_ROLE;
GRANT ROLE DATAPILOT_ROLE TO USER datapilot_user;
```

### PostgreSQL

```env
DATAPILOT_DB_SOURCE=postgresql

DATAPILOT_DB_HOST=localhost
DATAPILOT_DB_PORT=5432
DATAPILOT_DB_USER=your_pg_user
DATAPILOT_DB_PASSWORD=your_pg_password
DATAPILOT_DB_DATABASE=analytics
DATAPILOT_DB_SCHEMA=public
DATAPILOT_DB_SSL_MODE=prefer
```

Recommended read-only role:

```sql
CREATE ROLE datapilot_role LOGIN PASSWORD 'secure_pass';
GRANT CONNECT ON DATABASE analytics TO datapilot_role;
GRANT USAGE ON SCHEMA public TO datapilot_role;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO datapilot_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO datapilot_role;
```

Also works with: **Amazon Redshift**, **CockroachDB**, **Supabase**, **Neon**, **AlloyDB**, **TimescaleDB**.

### LLM Provider

**Groq (FREE — recommended)**
```env
DATAPILOT_LLM_PROVIDER=groq
DATAPILOT_LLM_MODEL=llama-3.3-70b-versatile
DATAPILOT_API_KEY=gsk_your_groq_key
```
Sign up at https://console.groq.com — no credit card. 14,400 requests/day free.

**Ollama (FREE — local)**
```env
DATAPILOT_LLM_PROVIDER=ollama
DATAPILOT_LLM_MODEL=qwen2.5-coder:7b
```

---

## Architecture

```
datapilot/
├── src/
│   ├── app.py                             # FastAPI + orchestration
│   ├── config.py                          # Universal settings
│   ├── llm_providers.py                   # Multi-LLM abstraction
│   ├── connectors/
│   │   ├── base.py                        # Abstract interface (ABC)
│   │   ├── factory.py                     # Creates connector from config
│   │   ├── snowflake_connector.py         # Snowflake implementation
│   │   └── postgres_connector.py          # PostgreSQL implementation
│   ├── core/
│   │   ├── schema_introspector.py         # Source-agnostic schema discovery
│   │   ├── sql_generator.py               # Dialect-aware Text-to-SQL
│   │   ├── query_executor.py              # Execute + cache
│   │   └── response_synthesizer.py        # Results → natural language
│   └── security/
│       └── guard.py                       # SQL validation (5 layers)
├── frontend/
│   └── index.html                         # Chat UI + tables + charts
├── .env.example
├── requirements.txt
└── README.md
```

### How the Connector Pattern Works

Each connector implements one abstract interface (`BaseConnector`). The rest of DataPilot — schema discovery, SQL generation, security, caching, frontend — is completely source-agnostic:

```
BaseConnector (abstract)
    ├── connect() / disconnect() / is_connected()
    ├── discover_tables() → List[TableInfo]
    ├── discover_columns(table) → List[ColumnInfo]
    ├── discover_primary_keys(table) → List[str]
    ├── discover_foreign_keys(table) → List[Dict]
    ├── sample_column_values(table, col) → List[str]
    ├── execute_query(sql) → QueryResult
    ├── get_dialect() → "snowflake" | "postgresql"
    └── get_dialect_hints() → str  (LLM prompt rules for this SQL dialect)
```

### Adding a New Database

1. Create `src/connectors/mysql_connector.py` implementing `BaseConnector`
2. Add one line to `CONNECTOR_REGISTRY` in `factory.py`
3. Add the driver to `requirements.txt`

Zero changes to any other file. Schema discovery, SQL generation, security, caching, and frontend all work automatically.

---

## Security — 5 Layers

| Layer | What it blocks |
|-------|---------------|
| **1. DDL/DML keywords** | DROP, DELETE, INSERT, UPDATE, ALTER, CREATE, TRUNCATE |
| **2. Source-specific** | Snowflake: COPY INTO, PUT, SYSTEM$. PostgreSQL: pg_sleep, pg_read_file, COPY, dblink, SET ROLE |
| **3. Injection prevention** | Multi-statement, comment injection, UNION schema extraction |
| **4. SQL parsing** | sqlparse structural validation — only SELECT/WITH statements |
| **5. Complexity limits** | Max JOINs, automatic LIMIT, query timeout, row caps |

---

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ask` | POST | Ask a question → get answer + data |
| `/api/health` | GET | Health check with component status |
| `/api/schema` | GET | View discovered schema metadata |
| `/api/schema/refresh` | POST | Force re-discover schema |
| `/api/schema/mschema` | GET | View M-Schema (what the LLM sees) |
| `/api/sources` | GET | List supported and available sources |
| `/api/sql/validate` | POST | Validate SQL without executing |
| `/api/cache/clear` | POST | Clear query cache |

Swagger docs: http://localhost:8000/docs

---

## Tech Stack — 100% Open Source, $0

| Component | Technology | Cost |
|-----------|-----------|------|
| LLM | Groq (llama-3.3-70b) | $0 |
| Embeddings | all-MiniLM-L6-v2 (local) | $0 |
| Vector Store | ChromaDB (local) | $0 |
| Backend | FastAPI + Python | $0 |
| SQL Parsing | sqlparse | $0 |
| Frontend | Vanilla HTML/JS + Chart.js | $0 |
| Snowflake driver | snowflake-connector-python | $0 |
| PostgreSQL driver | psycopg2-binary | $0 |

---

## License

MIT
