"""
DataPilot — SQL Generator (Dialect-Aware)
============================================
Converts natural language → SQL for ANY supported database.

The dialect-specific rules come from the connector's get_dialect_hints().
This means adding a new database requires ZERO changes to this file.

Architecture:
  question + M-Schema + dialect hints → LLM → raw SQL → extract → return
"""

import re
import logging
from typing import Dict, List, Optional, Tuple

from langchain.schema.messages import HumanMessage, AIMessage, SystemMessage

logger = logging.getLogger("datapilot.sqlgen")


SQL_SYSTEM_PROMPT = """You are DataPilot, an expert SQL analyst. You convert natural language questions into precise, optimized SQL queries.

CRITICAL RULES:
1. OUTPUT ONLY SQL: Return ONLY the SQL query. No explanations, no markdown, no code fences. Just pure SQL.
2. USE EXACT COLUMN/TABLE NAMES from the schema. Match case exactly.
3. USE EXACT VALUES from the sample values shown. If samples show 'SHIPPED', use 'SHIPPED' not 'shipped'.
4. SELECT only needed columns — never SELECT *.
5. Always add ORDER BY for deterministic results.
6. Always add LIMIT 100 unless the user specifies a count.
7. Use WHERE clauses to filter early for performance.
8. Use meaningful aliases with AS.
9. NEVER generate DDL/DML (DROP, DELETE, INSERT, UPDATE, ALTER, CREATE). Only SELECT/WITH.
10. When the user says "last month", "this year" etc., use the database's date functions.
11. If ambiguous, make reasonable assumptions and prefer simpler queries.

{dialect_hints}
"""

SELF_CORRECTION_PROMPT = """The previous SQL query failed:

ERROR: {error}

PREVIOUS SQL:
{previous_sql}

Fix the query. Common issues: wrong column name, type mismatch, syntax error.
Return ONLY the corrected SQL.
"""


class SQLGenerator:
    """Generates SQL from natural language using LLM + schema context."""

    def __init__(self, llm, schema_introspector, connector, vector_store=None):
        self.llm = llm
        self.schema = schema_introspector
        self.connector = connector
        self.vector_store = vector_store
        self.max_retries = 2

        # Get dialect-specific hints from the connector
        self.dialect = connector.get_dialect()
        self.dialect_hints = connector.get_dialect_hints()

    def _get_system_prompt(self) -> str:
        return SQL_SYSTEM_PROMPT.format(dialect_hints=self.dialect_hints)

    async def agenerate(
        self,
        question: str,
        conversation_history: List[Dict[str, str]] = None,
        specific_tables: List[str] = None,
    ) -> Tuple[str, str]:
        """Generate SQL from a natural language question."""
        schema_context = self._build_schema_context(question, specific_tables)
        messages = self._build_messages(question, schema_context, conversation_history)

        try:
            response = await self.llm.ainvoke(messages)
            raw_sql = self._extract_sql(response.content)
            logger.info(f"Generated SQL ({self.dialect}): {raw_sql[:200]}...")
            return raw_sql, ""
        except Exception as e:
            logger.error(f"SQL generation failed: {e}")
            raise

    def generate(
        self,
        question: str,
        conversation_history: List[Dict[str, str]] = None,
        specific_tables: List[str] = None,
    ) -> Tuple[str, str]:
        """Sync version of generate."""
        schema_context = self._build_schema_context(question, specific_tables)
        messages = self._build_messages(question, schema_context, conversation_history)

        response = self.llm.invoke(messages)
        raw_sql = self._extract_sql(response.content)
        return raw_sql, ""

    async def aself_correct(
        self, question: str, failed_sql: str, error_message: str, schema_context: str,
    ) -> str:
        """Retry SQL generation with error context."""
        messages = [
            SystemMessage(content=self._get_system_prompt()),
            SystemMessage(content=f"DATABASE SCHEMA:\n{schema_context}"),
            HumanMessage(content=question),
            AIMessage(content=failed_sql),
            HumanMessage(content=SELF_CORRECTION_PROMPT.format(
                error=error_message, previous_sql=failed_sql,
            )),
        ]
        response = await self.llm.ainvoke(messages)
        return self._extract_sql(response.content)

    def _build_schema_context(
        self, question: str, specific_tables: Optional[List[str]] = None
    ) -> str:
        """Build schema context. Uses RAG for large schemas."""
        metadata = self.schema.discover_schema()

        if specific_tables:
            from connectors.base import SchemaMetadata
            filtered = SchemaMetadata(
                source_type=metadata.source_type,
                database=metadata.database,
                schema_name=metadata.schema_name,
                discovered_at=metadata.discovered_at,
            )
            for t in specific_tables:
                key = t.upper() if self.dialect == "snowflake" else t
                for name, info in metadata.tables.items():
                    if name.upper() == t.upper():
                        filtered.tables[name] = info
                        break
            return self.schema.build_mschema(filtered)

        if metadata.table_count() <= 15:
            return self.schema.build_mschema()

        # Large schema → RAG
        if self.vector_store:
            try:
                results = self.vector_store.similarity_search_with_relevance_scores(question, k=8)
                relevant = set()
                for doc, score in results:
                    if score >= 0.3:
                        tname = doc.metadata.get("table_name")
                        if tname:
                            relevant.add(tname)

                if relevant:
                    from connectors.base import SchemaMetadata
                    filtered = SchemaMetadata(
                        source_type=metadata.source_type,
                        database=metadata.database,
                        schema_name=metadata.schema_name,
                        discovered_at=metadata.discovered_at,
                    )
                    for name, info in metadata.tables.items():
                        if name in relevant:
                            filtered.tables[name] = info
                    logger.info(f"RAG selected {len(relevant)} tables: {relevant}")
                    return self.schema.build_mschema(filtered)
            except Exception as e:
                logger.warning(f"RAG failed, using full schema: {e}")

        return self.schema.build_mschema()

    def _build_messages(self, question, schema_context, history=None):
        messages = [
            SystemMessage(content=self._get_system_prompt()),
            SystemMessage(content=f"DATABASE SCHEMA:\n\n{schema_context}"),
        ]
        if history:
            for msg in history[-6:]:
                if msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "assistant":
                    messages.append(AIMessage(content=msg.get("sql", msg["content"])))
        messages.append(HumanMessage(content=question))
        return messages

    def _extract_sql(self, text: str) -> str:
        """Extract clean SQL from LLM response."""
        text = text.strip()

        # Remove markdown code fences
        if "```" in text:
            match = re.search(r'```(?:sql)?\s*\n?(.*?)\n?```', text, re.DOTALL)
            if match:
                text = match.group(1).strip()

        # Find SQL start
        lines = text.split("\n")
        sql_start = -1
        for i, line in enumerate(lines):
            stripped = line.strip().upper()
            if stripped.startswith("SELECT") or stripped.startswith("WITH"):
                sql_start = i
                break
        if sql_start >= 0:
            text = "\n".join(lines[sql_start:])

        # Remove trailing explanation
        clean_lines = []
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.lower().startswith(("this query", "explanation:", "note:", "the above")):
                break
            clean_lines.append(line)

        text = "\n".join(clean_lines).strip()
        if text.endswith(";"):
            text = text[:-1].strip()
        return text
