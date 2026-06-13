from collections.abc import Generator

from psycopg import Connection, connect

from app.config import POSTGRES_URL, POSTGRES_V2_URL


def get_connection() -> Connection:
    return connect(POSTGRES_URL)


def get_connection_v2() -> Connection:
    return connect(POSTGRES_V2_URL)


def get_db() -> Generator[Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_db_v2() -> Generator[Connection, None, None]:
    conn = get_connection_v2()
    try:
        yield conn
    finally:
        conn.close()
