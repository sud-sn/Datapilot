"""
DataPilot — Response Synthesizer
==================================
Takes raw query results and generates:
1. Natural language summary of the data
2. Visualization recommendations (chart type, axes)
3. Follow-up question suggestions

This is what makes DataPilot feel like talking to a data analyst,
not just a SQL generator.
"""

import logging
from typing import Dict, List, Optional, Any

from langchain.schema.messages import HumanMessage, SystemMessage

logger = logging.getLogger("datapilot.synthesizer")


SYNTHESIZER_PROMPT = """You are a data analyst assistant. Given a user's question, the SQL query that was executed, and the query results, provide a clear, concise natural language answer.

RULES:
1. Answer the user's question directly and specifically.
2. Include key numbers and metrics from the results.
3. Format large numbers with commas (e.g., 1,234,567).
4. Format currency with $ and 2 decimal places.
5. Format percentages with 1 decimal place.
6. If the data shows trends, mention them.
7. If results are empty, say so clearly and suggest why.
8. Keep the answer concise — 2-4 sentences for simple questions, more for complex analysis.
9. Do NOT repeat the SQL query in your answer.
10. Do NOT say "based on the data" or "according to the results" — just state the facts.
11. If the result is a single number, lead with that number.
12. Suggest 1-2 natural follow-up questions the user might want to ask.

RESPONSE FORMAT:
Answer: [your natural language answer]
Follow-up: [1-2 suggested follow-up questions, separated by |]
Chart: [none|bar|line|pie|table|number] — recommend the best visualization
"""


class ResponseSynthesizer:
    """Generates natural language responses from query results."""

    def __init__(self, llm):
        self.llm = llm

    async def synthesize(
        self,
        question: str,
        sql: str,
        result: Dict,
    ) -> Dict[str, str]:
        """
        Generate a natural language response from query results.

        Returns:
            {
                "answer": "Total revenue last quarter was $12.4M, up 8% from...",
                "follow_ups": ["How does this break down by region?", "What about Q3?"],
                "chart_type": "bar",
            }
        """
        # Build result summary for the LLM
        result_summary = self._format_results_for_llm(result)

        messages = [
            SystemMessage(content=SYNTHESIZER_PROMPT),
            HumanMessage(content=f"""
User question: {question}

SQL executed:
{sql}

Results ({result.get('row_count', 0)} rows, {result.get('execution_time_ms', 0):.0f}ms):
{result_summary}
"""),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            return self._parse_response(response.content)
        except Exception as e:
            logger.error(f"Synthesis error: {e}")
            # Fallback: generate a basic response without LLM
            return self._fallback_response(question, result)

    def _format_results_for_llm(self, result: Dict, max_rows: int = 20) -> str:
        """Format query results into a readable string for the LLM."""
        if result.get("error"):
            return f"ERROR: {result['error']}"

        rows = result.get("rows", [])
        columns = result.get("columns", [])

        if not rows:
            return "No results returned."

        # Show first N rows as a table
        lines = []
        lines.append(" | ".join(columns))
        lines.append("-" * len(lines[0]))

        for row in rows[:max_rows]:
            values = []
            for col in columns:
                val = row.get(col, "")
                if val is None:
                    val = "NULL"
                values.append(str(val)[:50])  # Truncate long values
            lines.append(" | ".join(values))

        if len(rows) > max_rows:
            lines.append(f"... and {len(rows) - max_rows} more rows")

        return "\n".join(lines)

    def _parse_response(self, text: str) -> Dict[str, Any]:
        """Parse the structured LLM response."""
        answer = text
        follow_ups = []
        chart_type = "table"

        # Extract Answer section
        if "Answer:" in text:
            parts = text.split("Answer:", 1)
            remaining = parts[1] if len(parts) > 1 else text

            # Extract follow-ups
            if "Follow-up:" in remaining:
                answer_part, follow_part = remaining.split("Follow-up:", 1)
                answer = answer_part.strip()

                if "Chart:" in follow_part:
                    follow_text, chart_part = follow_part.split("Chart:", 1)
                    follow_ups = [q.strip() for q in follow_text.strip().split("|") if q.strip()]
                    chart_type = chart_part.strip().lower()
                else:
                    follow_ups = [q.strip() for q in follow_part.strip().split("|") if q.strip()]
            elif "Chart:" in remaining:
                answer_part, chart_part = remaining.split("Chart:", 1)
                answer = answer_part.strip()
                chart_type = chart_part.strip().lower()
            else:
                answer = remaining.strip()

        # Validate chart type
        valid_charts = {"none", "bar", "line", "pie", "table", "number", "area", "scatter"}
        if chart_type not in valid_charts:
            chart_type = "table"

        return {
            "answer": answer,
            "follow_ups": follow_ups[:3],
            "chart_type": chart_type,
        }

    def _fallback_response(self, question: str, result: Dict) -> Dict[str, Any]:
        """Generate a basic response when LLM synthesis fails."""
        row_count = result.get("row_count", 0)
        columns = result.get("columns", [])
        rows = result.get("rows", [])

        if result.get("error"):
            answer = f"The query encountered an error: {result['error']}"
        elif row_count == 0:
            answer = "The query returned no results. Try broadening your search criteria."
        elif row_count == 1 and len(columns) == 1:
            value = rows[0][columns[0]] if rows else "N/A"
            answer = f"The answer is: {value}"
        else:
            answer = f"Found {row_count} results across {len(columns)} columns."

        return {
            "answer": answer,
            "follow_ups": [],
            "chart_type": "table" if row_count > 1 else "number",
        }
