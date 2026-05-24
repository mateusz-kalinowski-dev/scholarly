import re

ARXIV_ID_RE = re.compile(r"^(\d{4}\.\d{4,5})(v\d+)?$")


def normalize_arxiv_id(raw: str) -> str:
    """Np. 2403.01234v1 -> 2403.01234 (jedna praca = jeden rekord)."""
    raw = raw.strip().split("/")[-1]
    m = ARXIV_ID_RE.match(raw)
    if m:
        return m.group(1)
    return raw
