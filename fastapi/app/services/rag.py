import httpx

from app.config import LLM_MAX_CONTEXT_CHARS, LLM_MODEL, LLM_NUM_CTX, OLLAMA_BASE_URL
from app.schemas import SearchHit, SourceChunk, SourcePaper

# Exact phrase when retrieval context is irrelevant (aligned with RAGAS / golden QA runs).
IDK_ANSWER = "I do not know."

LLM_OPTIONS = {"num_ctx": LLM_NUM_CTX, "temperature": 0}

RAG_SYSTEM_PROMPT = """You are Scholarly, a scientific Q&A assistant for arXiv CS papers.

You receive numbered context excerpts [1], [2], … retrieved from papers. Answer ONLY using information present in these excerpts. Do not use prior knowledge.

Answer format (required):
- Write 2–4 complete sentences in plain prose (no markdown, no bullet lists, no section headers).
- State concrete facts from the excerpts: methods, metrics, percentages, architectures, definitions, comparisons.
- When a fact comes from an excerpt, cite it with the excerpt number in square brackets, e.g. [1] or [2].
- If multiple excerpts apply, synthesize them in one coherent answer.

Partial answers:
- If excerpts partially answer the question, answer what is supported and briefly note what the excerpts do not cover.

When information is missing:
- If no excerpt contains information relevant to the question, reply with exactly: I do not know.
- Do not guess or fill gaps from outside knowledge."""

LLM_ONLY_SYSTEM_PROMPT = """You are Scholarly, a scientific assistant for arXiv CS papers.

No paper excerpts were provided for this turn. For paper-specific or experimental questions, reply with exactly: I do not know.

For general CS concepts you may answer briefly in 2–4 plain sentences (no markdown)."""


class LLMError(Exception):
    pass


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


def _answer_language_instruction(answer_language: str | None) -> str:
    if not answer_language:
        return ""
    return (
        f"\n\nLanguage: Write the answer in {answer_language}. "
        "Context excerpts may be in English; translate concepts as needed while "
        "keeping numbers, symbols, and technical terms accurate."
    )


def _format_context_block(index: int, hit: SearchHit) -> str:
    section = hit.section_name or "N/A"
    if hit.subsection_name:
        section = f"{section} / {hit.subsection_name}"
    return (
        f"--- Excerpt [{index}] ---\n"
        f"Paper: {hit.title}\n"
        f"arXiv: {hit.arxiv_id}\n"
        f"Section: {section}\n"
        f"Content:\n{hit.content}\n"
    )


def build_rag_messages(
    question: str,
    hits: list[SearchHit],
    *,
    answer_language: str | None = None,
) -> tuple[str, str]:
    context_parts: list[str] = []
    used = 0

    for i, hit in enumerate(hits, start=1):
        block = _format_context_block(i, hit)
        if used + len(block) > LLM_MAX_CONTEXT_CHARS:
            break
        context_parts.append(block)
        used += len(block)

    context = (
        "\n".join(context_parts) if context_parts else "(no context retrieved)"
    )
    system = RAG_SYSTEM_PROMPT + _answer_language_instruction(answer_language)
    user = (
        "Context excerpts:\n\n"
        f"{context}\n\n"
        f"Question: {question}\n\n"
        "Write your answer (2–4 sentences, cite [n] where relevant, plain prose only)."
    )
    return system, user


def build_llm_only_messages(
    question: str,
    *,
    answer_language: str | None = None,
) -> tuple[str, str]:
    system = LLM_ONLY_SYSTEM_PROMPT + _answer_language_instruction(answer_language)
    user = f"Question: {question}"
    return system, user


# Backward-compatible aliases for any external imports
def build_rag_prompt(
    question: str,
    hits: list[SearchHit],
    *,
    answer_language: str | None = None,
) -> str:
    system, user = build_rag_messages(question, hits, answer_language=answer_language)
    return f"SYSTEM:\n{system}\n\nUSER:\n{user}"


def build_llm_only_prompt(
    question: str,
    *,
    answer_language: str | None = None,
) -> str:
    system, user = build_llm_only_messages(
        question, answer_language=answer_language
    )
    return f"SYSTEM:\n{system}\n\nUSER:\n{user}"


async def generate_chat(system: str, user: str) -> str:
    from app.services.llm_backend import get_llm_backend

    if get_llm_backend() == "openai":
        from app.services.openai_llm import openai_chat

        return await openai_chat(system, user)

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": LLM_OPTIONS,
    }
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat", json=payload
        )

    if response.status_code != 200:
        raise LLMError(
            f"Ollama chat HTTP {response.status_code}: {response.text[:300]}"
        )

    data = response.json()
    message = data.get("message") or {}
    answer = (message.get("content") or "").strip()
    if not answer:
        raise LLMError("Pusta odpowiedź z modelu")
    return answer


async def generate_answer(prompt: str) -> str:
    """Completion-style call for rewrite / translation / Self-RAG helpers."""
    from app.services.llm_backend import get_llm_backend

    if get_llm_backend() == "openai":
        from app.services.openai_llm import openai_completion

        return await openai_completion(prompt)

    payload = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": LLM_OPTIONS,
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
