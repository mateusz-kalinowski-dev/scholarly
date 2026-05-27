import json
import logging
import time

import pika
import requests

from chunking import TextChunk, build_chunks
from config import POSTGRES_URL, RABBITMQ_PREFETCH, RABBITMQ_URL
from arxiv_ids import normalize_arxiv_id
from db import (
    get_paper_fields,
    mark_failed,
    mark_source_unavailable,
    paper_is_skipped,
    save_chunks,
    save_paper_embeddings,
    update_chunk_embeddings_bulk,
    update_paper_after_ingest,
    upsert_paper_metadata,
)
from embeddings import embed_texts, maybe_refresh_ivfflat_index, wait_for_ollama_models
from ingestion import SourceUnavailableError, fetch_raw_text
from parsing import analyze_document, parse_sections
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _should_requeue(exc: BaseException) -> bool:
    """Tylko błędy przejściowe wracają do kolejki (sieć/Ollama). 404/410 nigdy."""
    if isinstance(exc, SourceUnavailableError):
        return False
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        if 400 <= exc.response.status_code < 500:
            return False
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    if isinstance(exc, requests.RequestException):
        return True
    msg = str(exc).lower()
    return any(
        k in msg
        for k in ("timeout", "connection", "ollama", "rabbitmq", "temporarily")
    )


def _embed_paper_and_chunks(
    paper_id: str,
    arxiv_id: str,
    title: str,
    summary: str | None,
    chunk_ids: list[str],
    chunks: list[TextChunk],
) -> None:
    texts: list[str] = [title]
    has_summary = bool(summary and summary.strip())
    if has_summary:
        texts.append(summary)
    texts.extend(ch.content for ch in chunks)

    t0 = time.perf_counter()
    vectors = embed_texts(texts)
    logger.info(
        "[%s] Embeddingi (%d tekstów, batch) w %.1fs",
        arxiv_id,
        len(texts),
        time.perf_counter() - t0,
    )

    title_emb = vectors[0]
    if not title_emb:
        raise ValueError("Nie udało się wyembedować tytułu")

    offset = 1
    summary_emb = None
    if has_summary:
        summary_emb = vectors[1]
        offset = 2

    save_paper_embeddings(paper_id, title, summary or "", title_emb, summary_emb)

    pairs: list[tuple[str, list[float]]] = []
    for i, chunk_id in enumerate(chunk_ids):
        emb = vectors[offset + i]
        if emb:
            pairs.append((chunk_id, emb))
        else:
            logger.warning("[%s] Brak wektora chunka %s", arxiv_id, chunk_id)

    update_chunk_embeddings_bulk(pairs)
    logger.info("[%s] Zapisano %d/%d embeddingów chunków", arxiv_id, len(pairs), len(chunks))


def process_message(ch, method, properties, body):
    data = json.loads(body)
    data["id"] = normalize_arxiv_id(data["id"])
    arxiv_id = data["id"]
    t_paper = time.perf_counter()
    logger.info("[%s] Start pipeline", arxiv_id)

    paper_id: str | None = None
    stage = "parsing"

    try:
        if paper_is_skipped(arxiv_id):
            logger.info("[%s] Pominięto — brak źródła (parsing FAILED)", arxiv_id)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        result = upsert_paper_metadata(data)
        if not result:
            logger.info("[%s] Pominięto — DONE lub brak źródła w Postgres", arxiv_id)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return
        paper_id, arxiv_id, should_process = result
        if not should_process:
            logger.info("[%s] Pominięto — embedding już DONE", arxiv_id)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        logger.info("[%s] Metadane w Postgres (id=%s)", arxiv_id, paper_id)

        storage_path, raw_text = fetch_raw_text(
            arxiv_id, data.get("source_url"), data.get("pdf_url")
        )
        if not raw_text.strip():
            raise ValueError("Brak tekstu po e-print i PDF")

        sections = parse_sections(raw_text)
        analysis = analyze_document(sections)
        total_tokens = analysis["total_tokens"]
        chunks = build_chunks(sections, total_tokens)
        update_paper_after_ingest(arxiv_id, storage_path, total_tokens)
        logger.info(
            "[%s] Parsed: %d sekcji, ~%d tokenów, %d chunków",
            arxiv_id,
            analysis["section_count"],
            total_tokens,
            len(chunks),
        )

        if not chunks:
            raise ValueError("Brak chunków po chunkingu")

        chunk_ids = save_chunks(paper_id, chunks)

        stage = "embedding"
        fields = get_paper_fields(paper_id) or {
            "title": data["title"],
            "summary": data.get("summary_raw") or data.get("summary"),
        }
        _embed_paper_and_chunks(
            paper_id,
            arxiv_id,
            fields["title"],
            fields.get("summary"),
            chunk_ids,
            chunks,
        )

        maybe_refresh_ivfflat_index()

        logger.info(
            "[%s] Pipeline OK w %.1fs",
            arxiv_id,
            time.perf_counter() - t_paper,
        )

    except Exception as e:
        logger.exception("[%s] Błąd pipeline (%s): %s", arxiv_id, stage, e)
        if isinstance(e, SourceUnavailableError) or (
            isinstance(e, requests.HTTPError)
            and e.response is not None
            and e.response.status_code in (404, 410)
        ):
            mark_source_unavailable(arxiv_id)
            logger.warning("[%s] ACK — brak źródła arXiv, pomijam na stałe", arxiv_id)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return
        mark_failed(arxiv_id, stage)
        if _should_requeue(e):
            logger.warning("[%s] Requeue (błąd przejściowy)", arxiv_id)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        else:
            logger.warning(
                "[%s] ACK bez requeue (błąd trwały) — użyj requeue_incomplete.py",
                arxiv_id,
            )
            ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    ch.basic_ack(delivery_tag=method.delivery_tag)


def start_consuming():
    while True:
        try:
            params = pika.URLParameters(RABBITMQ_URL)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue="paper_tasks", durable=True)
            channel.basic_qos(prefetch_count=RABBITMQ_PREFETCH)
            channel.basic_consume(
                queue="paper_tasks", on_message_callback=process_message
            )

            logger.info(
                "Processor — paper_tasks (prefetch=%s)", RABBITMQ_PREFETCH
            )
            channel.start_consuming()
        except Exception as e:
            logger.error("Błąd RabbitMQ: %s. Ponawiam za 5s...", e)
            time.sleep(5)


if __name__ == "__main__":
    wait_for_ollama_models(["nomic-embed-text"])
    start_consuming()
