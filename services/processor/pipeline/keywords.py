"""Ekstrakcja słów kluczowych pod FTS / BM25 (content + keywords)."""
from __future__ import annotations

import re

_STOP = frozenset(
    {
        "about", "after", "also", "been", "being", "between", "both", "from",
        "have", "into", "more", "other", "such", "than", "that", "their",
        "there", "these", "this", "those", "through", "under", "using", "which",
        "while", "with", "within", "without", "would", "paper", "method", "model",
        "results", "based", "using", "shown", "show", "used", "use",
        # pozostałości LaTeX / FTS noise
        "begin", "caption", "hline", "rgb", "tikz", "textbf", "textcolor",
        "documentclass", "usepackage", "newcommand", "author", "maketitle",
    }
)

_LATEX_JUNK = re.compile(
    r"^(?:v\d+|\\[a-z]+|fig|tab|eqn|ref|cite|\d+\.\d{3,})$",
    re.I,
)


def extract_keywords(
    content: str,
    *,
    paper_title: str = "",
    section_name: str | None = None,
    subsection_name: str | None = None,
    sacred_type: str | None = None,
    max_keywords: int = 24,
) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        t = raw.strip().strip(".,;:")
        if len(t) < 2:
            return
        key = t.lower()
        if key in _STOP or key in seen or _LATEX_JUNK.match(key):
            return
        seen.add(key)
        found.append(t)

    for src in (paper_title, section_name or "", subsection_name or ""):
        for m in re.findall(r"\b[A-Z][A-Z0-9]{1,}\b", src):
            add(m)
        for m in re.findall(r"\b[A-Za-z]{4,}\b", src):
            if m[0].isupper():
                add(m)

    for m in re.findall(r"\b[A-Z][A-Z0-9]{1,}\b", content):
        add(m)
    for m in re.findall(r"\b\d{4}\.\d{4,5}[a-z]?\b", content, re.I):
        add(m)
    for m in re.findall(
        r"\b(?:PSNR|SSIM|mJ|FLOPs|GPU|CPU|SNN|ANN|CNN|RNN|BERT|GPT|LLM)\b", content, re.I
    ):
        add(m)
    for m in re.findall(r"\b\d+(?:\.\d+)?\s*(?:%|mJ|ms|s|GB|MB|KB)\b", content, re.I):
        add(m.replace(" ", ""))

    if sacred_type:
        add(sacred_type)
        if sacred_type in ("equation", "display_math", "inline_math"):
            add("equation")
            add("formula")

    for m in re.findall(r"\b[a-z]{5,}\b", content.lower()):
        if m not in _STOP:
            add(m)

    return found[:max_keywords]
