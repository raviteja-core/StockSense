"""StockSense Configuration & Database Connection Manager.

Handles environment loading, SQL Server connection via SQLAlchemy URL.create,
transient connection retries, and project paths.
"""

from __future__ import annotations

import os
import sys
import time
import logging
from pathlib import Path
from typing import Any, Callable, TypeVar, Optional, Tuple
from functools import wraps

from dotenv import load_dotenv
from sqlalchemy import create_engine, text, Engine
from sqlalchemy.engine import URL

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("stocksense.config")

# Project Directory Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

DATA_RAW_DIR = PROJECT_ROOT / os.getenv("DATA_RAW_DIR", "data/raw")
DATA_PROCESSED_DIR = PROJECT_ROOT / os.getenv("DATA_PROCESSED_DIR", "data/processed")
SQL_DIR = PROJECT_ROOT / "sql"

DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# Database Settings for Local SQL Server
DB_SERVER = os.getenv("DB_SERVER", "localhost,1433")
DB_NAME = os.getenv("DB_NAME", "stocksense")
DB_USER = os.getenv("DB_USER", "stocksense_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
DB_TRUST_SERVER_CERT = os.getenv("DB_TRUST_SERVER_CERT", "yes")
DB_CONNECTION_TIMEOUT = int(os.getenv("DB_CONNECTION_TIMEOUT", "30"))

# Unit test override flag
DB_BACKEND = os.getenv("DB_BACKEND", "mssql").lower().strip()

T = TypeVar("T")


def parse_db_server(server_str: str) -> Tuple[str, int]:
    """Parse server string into (host, port).

    Supports formats:
    - 'localhost,1433' (SQL Server comma convention)
    - 'localhost:1433'
    - 'localhost' (defaults to 1433)
    """
    server_str = server_str.strip()
    if "," in server_str:
        host, port_str = server_str.split(",", 1)
        return host.strip(), int(port_str.strip())
    elif ":" in server_str:
        host, port_str = server_str.split(":", 1)
        return host.strip(), int(port_str.strip())
    return server_str, 1433


def retry_on_db_error(
    max_retries: int = 3,
    initial_delay: float = 2.0,
    backoff_factor: float = 1.5
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to retry database operations on transient connection drops."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            delay = initial_delay
            last_exception: Optional[Exception] = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc
                    err_msg = str(exc).lower()
                    is_transient = any(
                        term in err_msg
                        for term in [
                            "login timeout", "communication link failure",
                            "handshake failed", "connection reset", "could not open a connection"
                        ]
                    )
                    if attempt < max_retries and is_transient:
                        logger.warning(
                            f"[Retry {attempt}/{max_retries}] Transient database error encountered. "
                            f"Retrying in {delay:.1f}s... (Error: {exc})"
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        raise
            if last_exception:
                raise last_exception
            raise RuntimeError("Exceeded retry attempts.")
        return wrapper
    return decorator


def build_sqlalchemy_url() -> URL:
    """Build SQLAlchemy connection URL object safely without string interpolation.

    Ensures passwords containing special characters (e.g., '@', '#', '%') are
    safely handled by URL.create.
    """
    host, port = parse_db_server(DB_SERVER)
    query_params = {
        "driver": DB_DRIVER,
        "TrustServerCertificate": DB_TRUST_SERVER_CERT,
        "Connection Timeout": str(DB_CONNECTION_TIMEOUT),
    }

    return URL.create(
        drivername="mssql+pyodbc",
        username=DB_USER,
        password=DB_PASSWORD,
        host=host,
        port=port,
        database=DB_NAME,
        query=query_params
    )


def get_db_engine(backend: Optional[str] = None, echo: bool = False) -> Engine:
    """Create and return SQLAlchemy Engine.

    Default backend is SQL Server ('mssql').
    'sqlite' is available as a fallback for unit testing.
    """
    selected_backend = backend.lower() if backend else DB_BACKEND

    if selected_backend == "sqlite":
        sqlite_path = DATA_PROCESSED_DIR / "stocksense_test.db"
        return create_engine(f"sqlite:///{sqlite_path}", echo=echo)

    # SQL Server via URL.create
    connection_url = build_sqlalchemy_url()
    engine = create_engine(
        connection_url,
        echo=echo,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=5,
        max_overflow=10,
        fast_executemany=True  # Batch insert optimization
    )
    return engine


@retry_on_db_error()
def test_connection() -> bool:
    """Verify SQL Server connectivity and log version and authenticated user."""
    engine = get_db_engine()
    logger.info("Testing SQL Server connection...")
    with engine.connect() as conn:
        result = conn.execute(text("SELECT @@VERSION AS version, DB_NAME() AS db_name, SUSER_NAME() AS user_name;")).fetchone()
        if result:
            version = result[0].split("\n")[0]
            db_name = result[1]
            user_name = result[2]
            logger.info(f"Connected to SQL Server! DB: {db_name} | User: {user_name} | Version: {version}")
        else:
            logger.info("Connected, but version query returned no rows.")
    return True


if __name__ == "__main__":
    try:
        test_connection()
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        sys.exit(1)
