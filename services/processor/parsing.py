"""Czyszczenie LaTeX/tekstu i ekstrakcja sekcji."""
from __future__ import annotations

import re
from dataclasses import dataclass

SECTION_PATTERN = re.compile(
    r"\\(?P<cmd>section|subsection)\*?\{(?P<title>[^}]*)\}",
    re.IGNORECASE,
)
KNOWN_SECTIONS = {
    "abstract",
    "introduction",
    "background",
    "related work",
    "methods",
    "methodology",
    "materials and methods",
    "experiments",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
    "references",
    "bibliography",
    "appendix",
    "acknowledgments",
    "acknowledgements",
}

SKIP_SECTIONS = {"references", "bibliography", "acknowledgments", "acknowledgements"}


@dataclass
class SectionBlock:
    section_name: str
    subsection_name: str | None
    content: str


def estimate_tokens(text: str) -> int:
    """Przybliżenie: ~1.3 tokena na słowo."""
    words = len(text.split())
    return max(1, int(words * 1.3))


def clean_text(raw: str) -> str:
    if not raw:
        return ""

    text = raw
    text = re.sub(r"(?m)^%.*$", "", text)
    text = re.sub(r"\\begin\{[^}]+\}.*?\\end\{[^}]+\}", "", text, flags=re.DOTALL)
    text = re.sub(r"\\cite[t|p]?\{[^}]*\}", "", text)
    text = re.sub(r"\\ref\{[^}]*\}", "", text)
    text = re.sub(r"\\label\{[^}]*\}", "", text)
    text = re.sub(r"\\includegraphics(\[[^\]]*\])?\{[^}]*\}", "", text)
    text = re.sub(r"\$[^$]+\$", " ", text)
    text = re.sub(r"\\\[[\s\S]*?\\\]", " ", text)
    text = re.sub(r"\\[a-zA-Z@]+\*?(\[[^\]]*\])?(\{[^}]*\})*", " ", text)
    text = re.sub(r"[{}\\]", " ", text)
    text = re.sub(r"-\s*\n\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_section_title(title: str) -> str:
    t = title.strip()
    t = re.sub(r"^\d+(\.\d+)*\s*", "", t)
    return t.strip() or "Body"


def parse_sections(raw: str) -> list[SectionBlock]:
    """Dzieli dokument na sekcje na podstawie \\section / \\subsection."""
    stripped = re.sub(r"(?m)^%.*$", "", raw)
    matches = list(SECTION_PATTERN.finditer(stripped))

    if not matches:
        body = clean_text(raw)
        return [SectionBlock("Body", None, body)] if body else []

    sections: list[SectionBlock] = []
    current_section = "Body"
    current_subsection: str | None = None

    if matches[0].start() > 0:
        pre = clean_text(stripped[: matches[0].start()])
        if pre:
            sections.append(SectionBlock("Body", None, pre))

    for i, match in enumerate(matches):
        cmd = match.group("cmd").lower()
        title = _normalize_section_title(match.group("title"))
        if cmd == "section":
            current_section = title
            current_subsection = None
        else:
            current_subsection = title

        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(stripped)
        content = clean_text(stripped[start:end])
        if content:
            sections.append(
                SectionBlock(current_section, current_subsection, content)
            )

    return sections


def analyze_document(sections: list[SectionBlock]) -> dict:
    total_tokens = sum(estimate_tokens(s.content) for s in sections)
    return {
        "total_tokens": total_tokens,
        "section_count": len(sections),
        "sections": sections,
    }
