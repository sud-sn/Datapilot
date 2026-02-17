"""
DataPilot — Main Application (Multi-Source)
==============================================
Natural language data assistant for ANY database:
  Snowflake · PostgreSQL · (more coming)

Architecture:
  User Question
      → Schema Context (M-Schema from any connector)
      → LLM (Groq free / Ollama / OpenAI)
      → SQL (dialect-specific via connector hints)
      → Security Validator
      → Query Executor (via connector)
      → Results
      → Response Synthesizer (LLM → natural language answer)
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

# ─── Path Setup ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = Path(__file__).resolve().parent
for p in [str(PROJECT_ROOT), str(SRC_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)
os.chdir(PROJECT_ROOT)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.schema import Document

from config import Settings
from llm_providers import get_llm_provider
from connectors.factory import create_connector, list_supported_sources
from connectors.base import BaseConnector
from core.schema_introspector import SchemaIntrospector
from core.sql_generator import SQLGenerator
from core.query_executor import QueryExecutor, QueryCache
from core.response_synthesizer import ResponseSynthesizer
from security.guard import SQLValidator

# ─── Logging ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("datapilot")

settings = Settings()

# ─── Global State ────────────────────────────────────────
connector: Optional[BaseConnector] = None
schema_introspector: Optional[SchemaIntrospector] = None
sql_generator: Optional[SQLGenerator] = None
sql_validator: Optional[SQLValidator] = None
query_executor: Optional[QueryExecutor] = None
query_cache: Optional[QueryCache] = None
response_synthesizer = None
vector_store = None
llm = None


def initialize_vector_store(schema_docs: List[Dict]) -> Chroma:
    embeddings = HuggingFaceEmbeddings(
        model_name=settings.embedding_model,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
    documents = [
        Document(page_content=doc["content"], metadata=doc["metadata"])
        for doc in schema_docs
    ]
    return Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        persist_directory=str(settings.chroma_persist_dir),
        collection_name="schema_context",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global connector, schema_introspector, sql_generator, sql_validator
    global query_executor, query_cache, response_synthesizer, vector_store, llm

    logger.info("Starting DataPilot...")

    # 1. LLM
    llm = get_llm_provider(
        provider=settings.llm_provider,
        model=settings.llm_model,
        temperature=settings.temperature,
        api_key=settings.api_key,
        base_url=settings.base_url,
    )
    logger.info(f"LLM: {settings.llm_provider}/{settings.llm_model}")

    # 2. Database connector (via factory)
    connector = create_connector(settings)
    connector.connect()
    logger.info(f"Database: {settings.db_source} → {settings.db_database}")

    # 3. Core components
    schema_introspector = SchemaIntrospector(connector, settings)
    query_executor = QueryExecutor(connector)
    query_cache = QueryCache(settings)
    sql_validator = SQLValidator(settings)
    response_synthesizer = ResponseSynthesizer(llm)

    # 4. Schema discovery + vector indexing
    try:
        metadata = schema_introspector.discover_schema()
        schema_docs = schema_introspector.build_schema_documents(metadata)
        vector_store = initialize_vector_store(schema_docs)
        logger.info(f"Schema: {metadata.table_count()} tables, {metadata.column_count()} columns")
    except Exception as e:
        logger.warning(f"Schema discovery deferred: {e}")
        vector_store = None

    # 5. SQL generator (dialect-aware)
    sql_generator = SQLGenerator(llm, schema_introspector, connector, vector_store)

    logger.info("DataPilot ready!")
    yield

    logger.info("Shutting down...")
    if connector:
        connector.disconnect()


app = FastAPI(
    title="DataPilot",
    description="Natural language data assistant — Snowflake, PostgreSQL, and more",
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


# ─── API Models ──────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str
    sql: Optional[str] = None

class AskRequest(BaseModel):
    question: str
    conversation_history: List[ChatMessage] = []
    session_id: str = "default"

class AskResponse(BaseModel):
    answer: str
    sql: str
    data: Optional[Dict[str, Any]] = None
    chart_type: str = "table"
    follow_ups: List[str] = []
    execution_time_ms: float = 0
    row_count: int = 0
    cached: bool = False
    warnings: List[str] = []
    source: str = ""


# ─── Core Endpoint ───────────────────────────────────────

@app.post("/api/ask", response_model=AskResponse)
async def ask(request: AskRequest):
    """Ask a question about your data in natural language."""
    question = request.question.strip()
    if not question:
        raise HTTPException(400, "Question cannot be empty")

    history = [msg.model_dump() for msg in request.conversation_history]

    # 1. Generate SQL
    try:
        sql, _ = await sql_generator.agenerate(question, history)
    except Exception as e:
        raise HTTPException(500, f"SQL generation failed: {e}")

    # 2. Validate
    validation = sql_validator.validate(sql)
    if not validation.is_safe:
        try:
            sql, _ = await sql_generator.agenerate(
                f"Generate a simple, safe SELECT query for: {question}", history
            )
            validation = sql_validator.validate(sql)
            if not validation.is_safe:
                raise HTTPException(400, f"Unsafe query: {validation.errors}")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, f"Unsafe query: {validation.errors}")

    sql = validation.query

    # 3. Cache check
    cached_result = query_cache.get(sql)
    if cached_result:
        synthesis = await response_synthesizer.synthesize(question, sql, cached_result.to_dict())
        return AskResponse(
            answer=synthesis["answer"], sql=sql, data=cached_result.to_dict(),
            chart_type=synthesis.get("chart_type", "table"),
            follow_ups=synthesis.get("follow_ups", []),
            execution_time_ms=cached_result.execution_time_ms,
            row_count=cached_result.row_count, cached=True,
            warnings=validation.warnings, source=settings.db_source,
        )

    # 4. Execute
    result = query_executor.execute(sql)

    # 5. Self-correct on error
    if result.error and sql_generator.max_retries > 0:
        schema_context = schema_introspector.build_mschema()
        for attempt in range(sql_generator.max_retries):
            try:
                corrected = await sql_generator.aself_correct(
                    question, sql, result.error, schema_context
                )
                v = sql_validator.validate(corrected)
                if not v.is_safe:
                    continue
                result = query_executor.execute(v.query)
                if not result.error:
                    sql = v.query
                    validation = v
                    break
            except Exception:
                pass

    # 6. Error response
    if result.error:
        return AskResponse(
            answer=f"Query failed: {result.error}. Try rephrasing.",
            sql=sql, data=None, chart_type="none",
            follow_ups=["Can you rephrase?"],
            execution_time_ms=result.execution_time_ms, row_count=0,
            warnings=validation.warnings + [result.error],
            source=settings.db_source,
        )

    query_cache.put(sql, result)

    # 7. Synthesize answer
    try:
        synthesis = await response_synthesizer.synthesize(question, sql, result.to_dict())
    except Exception:
        synthesis = {"answer": f"Query returned {result.row_count} rows.", "follow_ups": [], "chart_type": "table"}

    return AskResponse(
        answer=synthesis["answer"], sql=sql, data=result.to_dict(),
        chart_type=synthesis.get("chart_type", "table"),
        follow_ups=synthesis.get("follow_ups", []),
        execution_time_ms=result.execution_time_ms,
        row_count=result.row_count, cached=False,
        warnings=validation.warnings, source=settings.db_source,
    )


# ─── Utility Endpoints ──────────────────────────────────

@app.get("/api/health")
async def health():
    table_count = 0
    try:
        if schema_introspector and schema_introspector._cache:
            table_count = schema_introspector._cache.table_count()
    except Exception:
        pass

    connected = connector.is_connected() if connector else False

    return {
        "status": "healthy" if connected and llm else "degraded",
        "source": settings.db_source,
        "components": {
            "database": f"{settings.db_source} ({'connected' if connected else 'disconnected'})",
            "llm": f"{settings.llm_provider}/{settings.llm_model}" if llm else "not initialized",
            "vector_store": "ready" if vector_store else "not initialized",
            "cache": query_cache.stats if query_cache else {},
        },
        "schema": {"tables": table_count, "database": settings.db_database},
    }


@app.get("/api/sources")
async def get_sources():
    """List all supported database sources and their availability."""
    return {
        "active_source": settings.db_source,
        "supported": list_supported_sources(),
    }


@app.get("/api/schema")
async def get_schema():
    if not schema_introspector:
        raise HTTPException(503, "Not initialized")
    metadata = schema_introspector.discover_schema()
    return {
        "source": metadata.source_type,
        "database": metadata.database,
        "schema": metadata.schema_name,
        "table_count": metadata.table_count(),
        "tables": {
            name: {
                "type": info.table_type,
                "row_count": info.row_count,
                "column_count": len(info.columns),
                "columns": list(info.columns.keys()),
                "comment": info.comment,
            }
            for name, info in metadata.tables.items()
        },
    }


@app.post("/api/schema/refresh")
async def refresh_schema():
    if not schema_introspector:
        raise HTTPException(503, "Not initialized")
    metadata = schema_introspector.discover_schema(force_refresh=True)
    global vector_store
    schema_docs = schema_introspector.build_schema_documents(metadata)
    vector_store = initialize_vector_store(schema_docs)
    sql_generator.vector_store = vector_store
    query_cache.invalidate()
    return {"message": "Schema refreshed", "tables": metadata.table_count()}


@app.get("/api/schema/mschema")
async def get_mschema():
    if not schema_introspector:
        raise HTTPException(503, "Not initialized")
    return {"mschema": schema_introspector.build_mschema()}


@app.post("/api/sql/validate")
async def validate_sql(body: Dict):
    result = sql_validator.validate(body.get("sql", ""))
    return {
        "is_safe": result.is_safe, "errors": result.errors,
        "warnings": result.warnings, "complexity_score": result.complexity_score,
        "validated_query": result.query,
    }


@app.post("/api/cache/clear")
async def clear_cache():
    query_cache.invalidate()
    return {"message": "Cache cleared"}


# ─── Frontend ────────────────────────────────────────────
frontend_dir = None
for candidate in [PROJECT_ROOT / "frontend" / "dist", PROJECT_ROOT / "frontend"]:
    if candidate.exists() and (candidate / "index.html").exists():
        frontend_dir = candidate
        break

if frontend_dir:
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True))
else:
    @app.get("/")
    async def root():
        return {"message": "DataPilot API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    src = settings.db_source.upper()
    db = settings.db_database or "NOT SET"
    print()
    print("  ╔═══════════════════════════════════════╗")
    print("  ║       DataPilot Starting...            ║")
    print("  ╚═══════════════════════════════════════╝")
    print()
    print(f"  Source     : {src}")
    print(f"  Database   : {db}")
    print(f"  LLM        : {settings.llm_provider}/{settings.llm_model}")
    print(f"  Server     : http://localhost:{settings.port}")
    print(f"  API Docs   : http://localhost:{settings.port}/docs")
    print()
    uvicorn.run(app, host=settings.host, port=settings.port)
