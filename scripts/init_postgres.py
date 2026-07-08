"""
Run once per environment (local, staging, prod) before starting the app:

    python scripts/init_postgres.py

Creates the app tables (users, usage_log) and the LangGraph checkpoint/store
tables in the target Postgres database. Safe to re-run — all setup calls are
idempotent (CREATE TABLE IF NOT EXISTS under the hood).
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.db.init_db import init_all

if __name__ == "__main__":
    init_all()
    print("Database initialized.")
