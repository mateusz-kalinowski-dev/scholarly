"""Podsumowanie stanu pipeline w Postgres. Uruchom: python stats.py"""
from psycopg import connect

from config import POSTGRES_URL

QUERIES = [
    ("papers — embedding_status", """
        SELECT embedding_status, COUNT(*) FROM papers
        GROUP BY embedding_status ORDER BY COUNT(*) DESC
    """),
    ("papers — parsing_status", """
        SELECT parsing_status, COUNT(*) FROM papers
        GROUP BY parsing_status ORDER BY COUNT(*) DESC
    """),
    ("chunki child z embeddingiem", """
        SELECT COUNT(*) FROM chunks
        WHERE chunk_role = 'child' AND embedding IS NOT NULL
    """),
    ("chunki child bez embeddingu", """
        SELECT COUNT(*) FROM chunks
        WHERE chunk_role = 'child' AND embedding IS NULL
    """),
]


def main() -> None:
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            for title, sql in QUERIES:
                print(f"\n=== {title} ===")
                cur.execute(sql)
                rows = cur.fetchall()
                if len(rows) == 1 and len(rows[0]) == 1:
                    print(rows[0][0])
                else:
                    for row in rows:
                        print(row)


if __name__ == "__main__":
    main()
