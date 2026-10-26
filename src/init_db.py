"""StockSense Database Initializer.

Executes sql/01_create_tables.sql and sql/02_views.sql against the target
SQL Server database in sequential GO-delimited batches.
Safely re-runnable.
"""

from __future__ import annotations

import re
import sys
import logging
from pathlib import Path
from typing import List

from sqlalchemy import text
from src.config import get_db_engine, SQL_DIR, retry_on_db_error

logger = logging.getLogger("stocksense.init_db")


def split_sql_batches(sql_text: str) -> List[str]:
    """Split a T-SQL script on standalone 'GO' batch delimiters."""
    # Split on lines containing only 'GO' (case-insensitive, optional whitespace)
    batches = re.split(r"^\s*GO\s*$", sql_text, flags=re.MULTILINE | re.IGNORECASE)
    cleaned = []
    for b in batches:
        stmt = b.strip()
        if stmt:
            cleaned.append(stmt)
    return cleaned


@retry_on_db_error()
def execute_sql_file(file_path: Path) -> int:
    """Execute all batches in a SQL file against the configured database."""
    if not file_path.exists():
        raise FileNotFoundError(f"SQL file not found: {file_path}")

    logger.info(f"Executing SQL script: {file_path.name}...")
    sql_text = file_path.read_text(encoding="utf-8")
    batches = split_sql_batches(sql_text)

    engine = get_db_engine()
    executed_count = 0

    with engine.begin() as conn:
        for idx, batch in enumerate(batches, 1):
            try:
                conn.execute(text(batch))
                executed_count += 1
            except Exception as e:
                logger.error(f"Error executing batch #{idx} in {file_path.name}:\n{batch[:200]}...")
                logger.error(f"Exception details: {e}")
                raise

    logger.info(f"Successfully executed {executed_count} batches from {file_path.name}.")
    return executed_count


def init_database() -> None:
    """Initialize schema by running table DDL followed by analytical views."""
    logger.info("Initializing StockSense database schema...")

    create_tables_file = SQL_DIR / "01_create_tables.sql"
    create_views_file = SQL_DIR / "02_views.sql"

    # 1. Tables
    execute_sql_file(create_tables_file)

    # 2. Views
    execute_sql_file(create_views_file)

    # 3. Verify created tables
    engine = get_db_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT TABLE_NAME, TABLE_TYPE 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_SCHEMA = 'dbo'
            ORDER BY TABLE_TYPE, TABLE_NAME;
        """)).fetchall()

        logger.info(f"Database objects currently in 'dbo' schema ({len(result)} total):")
        for obj_name, obj_type in result:
            logger.info(f"  [{obj_type}] {obj_name}")

    logger.info("Database initialization completed successfully!")


if __name__ == "__main__":
    try:
        init_database()
    except Exception as exc:
        logger.error(f"Failed to initialize database: {exc}")
        sys.exit(1)
