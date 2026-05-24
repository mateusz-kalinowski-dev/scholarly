from collections.abc import Generator

from psycopg import Connection, connect

from app.config import POSTGRES_URL


def get_connection() -> Connection:
    return connect(POSTGRES_URL)


def get_db() -> Generator[Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
