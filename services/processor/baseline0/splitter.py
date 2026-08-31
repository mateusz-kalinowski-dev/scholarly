"""RecursiveCharacterTextSplitter — jak w tutorialowych RAG (bez LangChain)."""
from __future__ import annotations

_DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


def _merge_splits(splits: list[str], separator: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    sep_len = len(separator)
    docs: list[str] = []
    current: list[str] = []
    total = 0

    for piece in splits:
        piece_len = len(piece)
        add_len = piece_len + (sep_len if current else 0)
        if current and total + add_len > chunk_size:
            doc = separator.join(current).strip()
            if doc:
                docs.append(doc)
            while total > chunk_overlap and current:
                total -= len(current[0]) + (sep_len if len(current) > 1 else 0)
                current.pop(0)
        current.append(piece)
        total += add_len

    if current:
        doc = separator.join(current).strip()
        if doc:
            docs.append(doc)
    return docs


def _split_text(text: str, separators: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    separator = separators[0]
    rest = separators[1:]

    if separator:
        splits = text.split(separator)
    else:
        splits = list(text)

    good: list[str] = []
    merge_buf: list[str] = []

    for piece in splits:
        if not piece:
            continue
        candidate = piece if not separator else piece
        if len(candidate) > chunk_size:
            if merge_buf:
                good.extend(_merge_splits(merge_buf, separator, chunk_size, chunk_overlap))
                merge_buf = []
            if rest:
                sub_sep = "" if separator == "" else separator
                good.extend(_split_text(candidate, rest, chunk_size, chunk_overlap))
            else:
                for i in range(0, len(candidate), chunk_size - chunk_overlap or chunk_size):
                    chunk = candidate[i : i + chunk_size]
                    if chunk.strip():
                        good.append(chunk)
        else:
            merge_buf.append(candidate)

    if merge_buf:
        good.extend(_merge_splits(merge_buf, separator, chunk_size, chunk_overlap))
    return good


def recursive_character_split(
    text: str,
    *,
    chunk_size: int = 1000,
    chunk_overlap: int = 0,
    separators: list[str] | None = None,
) -> list[str]:
    """
    Dzieli surowy tekst papieru na chunki o stałej długości (~chunk_size znaków).
    Nie respektuje sekcji ani równań — celowo słabe cięcie pod Baseline 0.
    """
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap musi być mniejszy niż chunk_size")
    seps = separators if separators is not None else _DEFAULT_SEPARATORS
    return _split_text(text, seps, chunk_size, chunk_overlap)
