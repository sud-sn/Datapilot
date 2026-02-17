"""
DataPilot — LLM Provider Abstraction
=======================================
Supports multiple LLM backends. Priority order:
1. Groq (FREE, fastest, 70B model quality) — RECOMMENDED
2. Ollama (FREE, local, no data leaves machine)
3. OpenRouter (FREE models available)
4. OpenAI (paid, best quality)
5. Anthropic (paid, best quality)

For Text-to-SQL, we use temperature=0 for deterministic output.
"""

import logging
from typing import Optional

logger = logging.getLogger("datapilot.llm")


def get_llm_provider(
    provider: str,
    model: str,
    temperature: float = 0.0,  # Zero for SQL generation
    api_key: str = "",
    base_url: str = "",
):
    """Factory function to create the appropriate LLM instance."""

    provider = provider.lower().strip()
    logger.info(f"Initializing LLM: {provider} / {model}")

    # ── Groq (FREE, RECOMMENDED) ────────────────────────
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=model or "llama-3.3-70b-versatile",
            api_key=api_key,
            temperature=temperature,
            max_tokens=4096,
            streaming=True,
        )

    # ── Ollama (FREE, LOCAL) ─────────────────────────────
    elif provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
            return ChatOllama(
                model=model or "qwen2.5-coder:7b",
                base_url=base_url or "http://localhost:11434",
                temperature=temperature,
                num_ctx=8192,
            )
        except ImportError:
            from langchain_community.chat_models import ChatOllama
            return ChatOllama(
                model=model or "qwen2.5-coder:7b",
                base_url=base_url or "http://localhost:11434",
                temperature=temperature,
            )

    # ── OpenRouter (FREE MODELS) ─────────────────────────
    elif provider == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or "meta-llama/llama-3.1-8b-instruct:free",
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            temperature=temperature,
            streaming=True,
        )

    # ── OpenAI (PAID) ────────────────────────────────────
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or "gpt-4o",
            api_key=api_key,
            temperature=temperature,
            streaming=True,
        )

    # ── Anthropic (PAID) ─────────────────────────────────
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model or "claude-sonnet-4-20250514",
            api_key=api_key,
            temperature=temperature,
            streaming=True,
        )

    # ── LM Studio (FREE, LOCAL) ──────────────────────────
    elif provider == "lmstudio":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or "local-model",
            base_url=base_url or "http://localhost:1234/v1",
            api_key="not-needed",
            temperature=temperature,
        )

    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. "
            f"Supported: groq, ollama, openrouter, openai, anthropic, lmstudio"
        )
