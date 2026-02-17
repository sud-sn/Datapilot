"""
DataPilot — Launcher
=====================
Just run: python run.py
"""

import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SRC_DIR))
os.chdir(PROJECT_ROOT)

if __name__ == "__main__":
    import uvicorn
    from config import Settings
    settings = Settings()

    src = settings.db_source.upper()
    db = settings.db_database or "NOT SET"
    host_info = ""
    if settings.db_source in ("postgresql", "postgres"):
        host_info = f"\n  Host       : {settings.db_host}:{settings.db_port}"
    elif settings.db_source == "snowflake":
        host_info = f"\n  Account    : {settings.db_account}"

    print()
    print("  ╔═══════════════════════════════════════╗")
    print("  ║        DataPilot Starting...           ║")
    print("  ╚═══════════════════════════════════════╝")
    print()
    print(f"  Source     : {src}")
    print(f"  Database   : {db}{host_info}")
    print(f"  LLM        : {settings.llm_provider}/{settings.llm_model}")
    print(f"  Server     : http://localhost:{settings.port}")
    print(f"  API Docs   : http://localhost:{settings.port}/docs")
    print()

    uvicorn.run("app:app", host=settings.host, port=settings.port, reload=settings.debug)
