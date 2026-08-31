import json
import logging
import time

import pika
import requests

from arxiv_ids import normalize_arxiv_id
from config import EMBED_MODEL, RABBITMQ_PREFETCH, RABBITMQ_URL
from ingestion import SourceUnavailableError, fetch_raw_text
from pipeline.chunking import build_parent_child_chunks
from pipeline.db import (
    list_child_contents,
    mark_failed,
    mark_source_unavailable,
    maybe_refresh_search_indexes,
    paper_is_skipped,
    save_parent_child_chunks,
    update_child_embeddings,
    update_paper_after_ingest,
    update_paper_embeddings,
    upsert_paper_metadata,
)
from pipeline.embeddings import embed_texts, wait_for_ollama_models
from pipeline.parsing import parse_sections

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

        update_paper_after_ingest(arxiv_id, storage_path)

        sections = parse_sections(raw_text)
        title = data.get("title") or ""
        parents = build_parent_child_chunks(sections, paper_title=title)
        if not parents:
            raise ValueError("Brak parent chunków")

        p_count, c_count = save_parent_child_chunks(paper_id, parents)
        logger.info("[%s] Chunki: %d parent, %d child", arxiv_id, p_count, c_count)

        stage = "embedding"
        children = list_child_contents(paper_id)
        if not children:
            raise ValueError("Brak child chunków")

        vectors = embed_texts([content for _, content in children])
        pairs = [
            (cid, emb)
            for (cid, _), emb in zip(children, vectors)
            if emb is not None
        ]
        if len(pairs) != len(children):
            raise ValueError(f"Niepełne embeddingi child ({len(pairs)}/{len(children)})")
        update_child_embeddings(pairs)
        logger.info("[%s] Embeddingi child: %d", arxiv_id, len(pairs))

        summary = data.get("summary_raw") or data.get("summary") or ""
        title_vec = embed_texts([title])[0]
        summary_vec = embed_texts([summary])[0] if summary.strip() else None
        if not title_vec:
            raise ValueError("Brak embeddingu tytułu")
        update_paper_embeddings(paper_id, title_vec, summary_vec, EMBED_MODEL)

        maybe_refresh_search_indexes()

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
    wait_for_ollama_models(["bge-m3"])
    start_consuming()
