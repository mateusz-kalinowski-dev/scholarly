#!/usr/bin/env python3
"""
Przypisuje golden_qa.chunk_id do child chunków v2 (section + overlap reference_context).

  python remap_golden_qa_v2.py
  python remap_golden_qa_v2.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import re
import sys

from dotenv import load_dotenv

load_dotenv()

from v2.config import POSTGRES_V2_URL

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("remap_golden_qa")


def _norm_section(name: str | None) -> str:
    if not name:
        return ""
    s = name.lower()
    s = re.sub(r"[\\&]+", " and ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", text.lower()) if t not in {"the", "and", "for", "with", "from", "that", "this", "are", "was"}}


def _score(reference_context: str, content: str, *, section_gq: str, section_chunk: str) -> float:
    ref = re.sub(r"\s+", " ", reference_context).strip().lower()
    body = re.sub(r"\s+", " ", content).strip().lower()
    if not ref or not body:
        return 0.0

    score = 0.0
    if _norm_section(section_gq) == _norm_section(section_chunk):
        score += 5.0
    elif _norm_section(section_gq) and _norm_section(section_gq) in _norm_section(section_chunk):
        score += 3.0
    elif _norm_section(section_gq) and _norm_section(section_chunk) not in ("body", "abstract", ""):
        score -= 2.0

    ref_words = _tokens(ref)
    body_words = _tokens(body)
    if ref_words:
        score += 10.0 * len(ref_words & body_words) / len(ref_words)

    probe = ref[:120]
    if probe and probe in body:
        score += 8.0
    elif probe[:80] and probe[:80] in body:
        score += 4.0

    return score


def fetch_pending(conn) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id::text, paper_id::text, arxiv_id, section_name,
                   reference_context
            FROM golden_qa
            WHERE chunk_id IS NULL OR migration_status = 'pending'
            ORDER BY arxiv_id, section_name
            """
        )
        return cur.fetchall()


def fetch_child_candidates(conn, paper_id: str) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id::text, section_name, content
            FROM chunks
            WHERE paper_id = %s::uuid
              AND chunk_role = 'child'
            """,
            (paper_id,),
        )
        return cur.fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description="Remap golden_qa → child chunks v2")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from psycopg import connect

    with connect(POSTGRES_V2_URL) as conn:
        pending = fetch_pending(conn)
        if not pending:
            logger.info("Brak rekordów do mapowania.")
            return 0

        logger.info("Do mapowania: %d rekordów golden_qa", len(pending))
        mapped = 0

        for gid, paper_id, arxiv_id, section_name, reference_context in pending:
            candidates = fetch_child_candidates(conn, paper_id)
            if not candidates:
                logger.warning("[%s] Brak child chunków dla %s", arxiv_id, gid)
                continue

            best_id = None
            best_score = 0.0
            best_section = None
            for cid, sec, content in candidates:
                s = _score(reference_context, content, section_gq=section_name or "", section_chunk=sec or "")
                if s > best_score:
                    best_score = s
                    best_id = cid
                    best_section = sec

            section_match = _norm_section(section_name or "") == _norm_section(best_section or "")
            min_score = 3.0 if section_match else 6.0
            if not best_id or best_score < min_score:
                logger.warning(
                    "[%s] %s — brak dopasowania (best=%.1f)",
                    arxiv_id,
                    section_name,
                    best_score,
                )
                continue

            logger.info(
                "[%s] %s → %s (score=%.1f, chunk_section=%s)",
                arxiv_id,
                section_name,
                best_id[:8],
                best_score,
                best_section,
            )

            if not args.dry_run:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE golden_qa
                        SET chunk_id = %s::uuid,
                            migration_status = 'mapped'
                        WHERE id = %s::uuid
                        """,
                        (best_id, gid),
                    )
                conn.commit()
            mapped += 1

    logger.info("Zmapowano: %d / %d", mapped, len(pending))
    return 0 if mapped == len(pending) else 1


if __name__ == "__main__":
    sys.exit(main())
