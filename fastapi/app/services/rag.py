import httpx

from app.config import LLM_MAX_CONTEXT_CHARS, LLM_MODEL, OLLAMA_BASE_URL
from app.schemas import SearchHit, SourceChunk, SourcePaper


class LLMError(Exception):
    pass


SYSTEM_PROMPT = (
    "You are a scientific assistant. Answer only using the provided context. "
    "If the context is insufficient, say you do not know. Cite paper titles when relevant."
)


def hits_to_sources(hits: list[SearchHit]) -> tuple[list[SourceChunk], list[SourcePaper]]:
    sources: list[SourceChunk] = []
    papers_map: dict[str, SourcePaper] = {}

    for h in hits:
        sources.append(
            SourceChunk(
                chunk_id=h.chunk_id,
                paper_id=h.paper_id,
                arxiv_id=h.arxiv_id,
                title=h.title,
                section_name=h.section_name,
                content=h.content[:500],
                score=h.score,
            )
        )
        if h.paper_id not in papers_map:
            papers_map[h.paper_id] = SourcePaper(
                paper_id=h.paper_id,
                arxiv_id=h.arxiv_id,
                title=h.title,
                arxiv_url=h.arxiv_url,
            )

    return sources, list(papers_map.values())


def build_rag_prompt(question: str, hits: list[SearchHit]) -> str:
    context_parts: list[str] = []
    used = 0

    for i, hit in enumerate(hits, start=1):
        block = (
            f"[{i}] Paper: {hit.title} (arXiv:{hit.arxiv_id})\n"
            f"Section: {hit.section_name or 'N/A'}\n"
            f"{hit.content}\n"
        )
        if used + len(block) > LLM_MAX_CONTEXT_CHARS:
            break
        context_parts.append(block)
        used += len(block)

    context = "\n".join(context_parts) if context_parts else "(no context retrieved)"

    return (
        f"SYSTEM:\n{SYSTEM_PROMPT}\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"QUESTION:\n{question}\n\n"
        f"ANSWER:\n"
    )


def build_llm_only_prompt(question: str) -> str:
    return (
        f"SYSTEM:\n{SYSTEM_PROMPT}\n\n"
        f"QUESTION:\n{question}\n\n"
        f"ANSWER:\n"
    )


async def generate_answer(prompt: str) -> str:
    payload = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": 8192},
    }
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate", json=payload
        )

    if response.status_code != 200:
        raise LLMError(
            f"Ollama generate HTTP {response.status_code}: {response.text[:300]}"
        )

    data = response.json()
    answer = (data.get("response") or "").strip()
    if not answer:
        raise LLMError("Pusta odpowiedź z modelu")
    return answer
