"""Parsowanie v2 — agresywne czyszczenie LaTeX; matematyka/tabele jako święte bloki."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .sanitize import sanitize_db_text, sacred_placeholder, strip_legacy_sacred_placeholders

SECTION_PATTERN = re.compile(
    r"\\(?P<cmd>section|subsection)\*?\{(?P<title>[^}]*)\}",
    re.IGNORECASE,
)

SKIP_SECTIONS = {"references", "bibliography", "acknowledgments", "acknowledgements"}

SACRED_BLOCK_PATTERNS: list[tuple[str, str]] = [
    (r"\\begin\{equation\*?\}[\s\S]*?\\end\{equation\*?\}", "equation"),
    (r"\\begin\{align\*?\}[\s\S]*?\\end\{align\*?\}", "equation"),
    (r"\\begin\{gather\*?\}[\s\S]*?\\end\{gather\*?\}", "equation"),
    (r"\\begin\{tabular\*?\}[\s\S]*?\\end\{tabular\*?\}", "table"),
    (r"\\begin\{table\*?\}[\s\S]*?\\end\{table\*?\}", "table"),
    (r"\$\$[\s\S]*?\$\$", "display_math"),
    (r"(?<!\$)\$(?!\$)[^$\n]+\$(?!\$)", "inline_math"),
]

# Polecenia usuwane w całości (preambuła / konfiguracja / makra)
_DROP_LINE_CMDS = re.compile(
    r"\\(?:documentclass|usepackage|RequirePackage|IEEEoverridecommandlockouts|"
    r"geometry|hypersetup|pagestyle|bibliographystyle|graphicspath|colorlet|"
    r"definecolor|setlength|addtolength|setcounter|newtheorem|theoremstyle|"
    r"newenvironment|renewenvironment|input|include|lablogo|lablogowidth|"
    r"settitlefontsize|newif|makeatletter|makeatother|AtBeginDocument|"
    r"usepackage|PassOptionsToPackage|ExecuteBibliographyOptions|"
    r"addbibresource|graphicx|hyperref|amsmath|amssymb|amsfonts|xcolor|cite)\b",
    re.IGNORECASE,
)

_MACRO_DEF_START = re.compile(
    r"\\(?P<cmd>newcommand|renewcommand|providecommand|DeclareRobustCommand|"
    r"DeclareMathOperator|DeclareMathOperator\*|def|newtheorem|renewcommand)\*?",
    re.IGNORECASE,
)

_FRONT_MATTER_CMDS = re.compile(
    r"\\(?:title|author|date|thanks|maketitle|affiliation|email|institute|"
    r"IEEEauthorblockN|IEEEauthorblockA|and|thanks|keywords|IEEEkeywords)\b",
    re.IGNORECASE,
)

_TEXT_UNWRAP_CMDS = (
    "textbf", "textit", "emph", "textsc", "textrm", "texttt", "mathrm", "mathbf",
    "mathit", "mbox", "hbox", "uline", "underline", "text", "operatorname",
    "mathrm", "mathbf", "mathsf", "mathcal", "mathbb",
)

@dataclass
class SectionBlock:
    section_name: str
    subsection_name: str | None
    content: str


@dataclass
class SacredBlock:
    sacred_type: str
    content: str
    start: int
    end: int


def estimate_tokens(text: str) -> int:
    words = len(text.split())
    return max(1, int(words * 1.3))


def _find_brace_end(text: str, open_idx: int) -> int:
    """Indeks za zamykającym `}` dla `{` w open_idx."""
    if open_idx >= len(text) or text[open_idx] != "{":
        return open_idx
    depth = 0
    i = open_idx
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        elif ch == "\\" and i + 1 < len(text):
            i += 1
        i += 1
    return len(text)


def _skip_command(text: str, pos: int) -> int:
    """Przesuwa pozycję za opcjonalne [...] i wymagane {...} argumenty."""
    i = pos
    while i < len(text) and text[i] in "[{":
        if text[i] == "[":
            end = text.find("]", i)
            i = end + 1 if end != -1 else len(text)
        elif text[i] == "{":
            i = _find_brace_end(text, i)
        else:
            break
    return i


def _remove_macro_definitions(text: str) -> str:
    """Usuwa \\newcommand, \\def, \\DeclareMathOperator itd. z zagnieżdżonymi klamrami."""
    out: list[str] = []
    i = 0
    while i < len(text):
        m = _MACRO_DEF_START.search(text, i)
        if not m:
            out.append(text[i:])
            break
        out.append(text[i : m.start()])
        if m.group("cmd").lower() == "def":
            j = m.end()
            while j < len(text) and text[j] not in " \t\n\r{":
                j += 1
            j = _skip_command(text, j)
            i = j
        else:
            i = _skip_command(text, m.end())
    return "".join(out)


def _remove_braced_commands(text: str, command_names: set[str]) -> str:
    """Zamienia \\cmd{...} na zawartość klamry dla cmd z listy."""
    result = text
    for _ in range(8):
        changed = False
        for cmd in command_names:
            pattern = re.compile(
                rf"\\{cmd}\*?(?:\[[^\]]*\])?\{{",
                re.IGNORECASE,
            )
            pos = 0
            parts: list[str] = []
            while True:
                m = pattern.search(result, pos)
                if not m:
                    parts.append(result[pos:])
                    break
                parts.append(result[pos : m.start()])
                brace_start = m.end() - 1
                brace_end = _find_brace_end(result, brace_start)
                inner = result[brace_start + 1 : brace_end - 1]
                parts.append(inner)
                pos = brace_end
                changed = True
            result = "".join(parts)
        if not changed:
            break
    return result


def extract_document_body(raw: str) -> str:
    """Zostawia treść dokumentu; fallback gdy markery są nietypowe."""
    if not raw:
        return ""
    text = sanitize_db_text(raw)
    begin = re.search(r"\\begin\s*\{document\}", text, re.IGNORECASE)
    if not begin:
        return text

    body = text[begin.end() :]
    end = re.search(r"\\end\s*\{document\}", body, re.IGNORECASE)
    if end:
        body = body[: end.start()]

    if len(body.strip()) < 500 and len(text) > 2000:
        first_section = SECTION_PATTERN.search(text)
        if first_section:
            return text[first_section.start() :]
        return text[begin.end() :]
    return body


def strip_preamble_lines(text: str) -> str:
    """Usuwa linie z \\usepackage, \\documentclass, \\input{macros} itd."""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith("%"):
            continue
        if _DROP_LINE_CMDS.search(stripped):
            continue
        if re.match(r"\\(?:newcommand|renewcommand|providecommand|def)\b", stripped, re.I):
            continue
        lines.append(line)
    return "\n".join(lines)


def strip_front_matter(text: str) -> str:
    """Usuwa \\title, \\author, \\maketitle i podobne bloki przed właściwą treścią."""
    text = _remove_braced_commands(text, {c.lower() for c in (
        "title", "author", "date", "thanks", "affiliation", "institute",
        "IEEEauthorblockN", "IEEEauthorblockA", "keywords", "IEEEkeywords",
    )})
    text = re.sub(r"\\maketitle\b", "", text)
    text = re.sub(r"\\and\b", " ", text)
    text = re.sub(
        r"\\begin\{IEEEkeywords\}[\s\S]*?\\end\{IEEEkeywords\}", " ", text, flags=re.I
    )
    return text


def prepare_raw_document(raw: str) -> str:
    """Preambuła i makra usunięte; gotowe do sekcjonowania."""
    text = strip_legacy_sacred_placeholders(extract_document_body(raw))
    text = re.sub(r"(?m)^%.*$", "", text)
    text = _remove_macro_definitions(text)
    text = strip_preamble_lines(text)
    text = strip_front_matter(text)
    text = re.sub(r"\\makeatletter[\s\S]*?\\makeatother", " ", text, flags=re.I)
    return text.strip()


def _extract_abstract(text: str) -> tuple[str | None, str]:
    m = re.search(
        r"\\begin\{abstract\}([\s\S]*?)\\end\{abstract\}", text, re.IGNORECASE
    )
    if not m:
        return None, text
    abstract_raw = m.group(1)
    remainder = text[: m.start()] + " " + text[m.end() :]
    return abstract_raw, remainder


MATH_SACRED_TYPES = frozenset({"equation", "display_math", "inline_math"})


def preserve_raw_math(content: str) -> str:
    """Surowy LaTeX równania — bez usuwania \\begin, \\|, \\theta itd."""
    text = sanitize_db_text(content)
    text = re.sub(r"(?m)^%.*$", "", text)
    return text.strip()


def clean_sacred_content(content: str, sacred_type: str) -> str:
    """Tabele → czytelny tekst; równania → surowy LaTeX (BGE-M3)."""
    if sacred_type in MATH_SACRED_TYPES:
        return preserve_raw_math(content)

    text = sanitize_db_text(content)
    text = re.sub(r"(?m)^%.*$", "", text)
    text = re.sub(r"\\begin\{table\*?\}[\s\S]*?\\end\{table\*?\}", " ", text, flags=re.I)
    text = re.sub(r"\\begin\{tabular\*?\}", " ", text, flags=re.I)
    text = re.sub(r"\\end\{tabular\*?\}", " ", text, flags=re.I)
    text = re.sub(r"\\caption\*?(?:\[[^\]]*\])?\{([^}]*)\}", r"Caption: \1 ", text)
    text = re.sub(r"\\toprule\b|\\midrule\b|\\bottomrule\b|\\hline\b", " ", text)
    text = re.sub(r"\\multicolumn\{[^}]*\}\{[^}]*\}\{([^}]*)\}", r"\1 ", text)
    text = re.sub(r"\\multirow\{[^}]*\}\{[^}]*\}\{([^}]*)\}", r"\1 ", text)
    text = re.sub(r"&", " | ", text)
    text = re.sub(r"\\\\", "\n", text)
    text = _remove_braced_commands(text, {c for c in _TEXT_UNWRAP_CMDS})
    text = re.sub(
        r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})*",
        " ",
        text,
    )
    text = re.sub(r"[{}\\]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _protect_regions(text: str, patterns: list[str]) -> tuple[str, list[str]]:
    """Zastępuje regiony placeholderami, żeby nie zniszczyć ich przy czyszczeniu."""
    stored: list[str] = []
    result = text
    for pattern in patterns:
        def repl(m: re.Match[str]) -> str:
            idx = len(stored)
            stored.append(m.group(0))
            return sacred_placeholder(idx)

        result = re.sub(pattern, repl, result, flags=re.DOTALL)
    return result, stored


def _infer_sacred_type(raw: str) -> str:
    if "tabular" in raw or "\\begin{table" in raw:
        return "table"
    if raw.startswith("$$"):
        return "display_math"
    if raw.startswith("$"):
        return "inline_math"
    return "equation"


def _restore_regions(text: str, stored: list[str], *, sacred: bool) -> str:
    def repl(m: re.Match[str]) -> str:
        idx = int(m.group(1))
        if idx < 0 or idx >= len(stored):
            return " "
        raw = stored[idx]
        if sacred:
            return clean_sacred_content(raw, _infer_sacred_type(raw))
        return raw

    return re.sub(r"⟦SACRED:(\d+)⟧", repl, text)


def clean_text(raw: str) -> str:
    """Agresywne czyszczenie prozy; święte bloki i math chronione, potem oczyszczone."""
    if not raw:
        return ""

    text = strip_legacy_sacred_placeholders(sanitize_db_text(raw))
    text = re.sub(r"(?m)^%.*$", "", text)
    text = _remove_macro_definitions(text)
    text = strip_preamble_lines(text)

    protect_patterns = [p for p, _ in SACRED_BLOCK_PATTERNS]
    protect_patterns += [
        r"\\begin\{itemize\}[\s\S]*?\\end\{itemize\}",
        r"\\begin\{enumerate\}[\s\S]*?\\end\{enumerate\}",
        r"\\begin\{description\}[\s\S]*?\\end\{description\}",
    ]
    text, sacred_store = _protect_regions(text, protect_patterns)

    text = re.sub(r"\\newpage\b", "\n", text)
    text = re.sub(r"\\clearpage\b", "\n", text)
    text = re.sub(
        r"\\begin\{figure\*?\}[\s\S]*?\\end\{figure\*?\}", " ", text, flags=re.DOTALL
    )
    text = re.sub(r"\\includegraphics(\[[^\]]*\])?\{[^}]*\}", " ", text)
    text = re.sub(r"\\cite[t|p]?\{[^}]*\}", "", text)
    text = re.sub(r"\\ref\{[^}]*\}", "", text)
    text = re.sub(r"\\label\{[^}]*\}", "", text)
    text = re.sub(r"\\url\{[^}]*\}", "", text)
    text = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\footnote(?:mark)?(?:\[[^\]]*\])?\{[^}]*\}", " ", text)
    text = re.sub(r"\\vspace\*?\{[^}]*\}", " ", text)
    text = re.sub(r"\\hspace\*?\{[^}]*\}", " ", text)
    text = re.sub(r"\\noindent\b", " ", text)
    text = re.sub(r"\\centering\b", " ", text)
    text = re.sub(r"\\item\b", "\n- ", text)
    text = re.sub(r"~", " ", text)
    text = re.sub(r"\\%", "%", text)

    unwrap = {c.lower() for c in _TEXT_UNWRAP_CMDS}
    text = _remove_braced_commands(text, unwrap)

    text = re.sub(
        r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})*",
        " ",
        text,
    )
    text = re.sub(r"[{}\\]", " ", text)
    text = re.sub(r"-\s*\n\s*", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    text = _restore_regions(text, sacred_store, sacred=True)
    text = re.sub(r"[ \t]+", " ", text)
    return sanitize_db_text(text.strip())


def extract_sacred_blocks(text: str) -> list[SacredBlock]:
    blocks: list[SacredBlock] = []
    for pattern, stype in SACRED_BLOCK_PATTERNS:
        for m in re.finditer(pattern, text):
            raw = m.group(0).strip()
            content = clean_sacred_content(raw, stype)
            if len(content) < 8:
                continue
            blocks.append(
                SacredBlock(
                    sacred_type=stype,
                    content=content,
                    start=m.start(),
                    end=m.end(),
                )
            )
    blocks.sort(key=lambda b: b.start)
    merged: list[SacredBlock] = []
    for b in blocks:
        if merged and b.start < merged[-1].end:
            continue
        merged.append(b)
    return merged


def _normalize_section_title(title: str) -> str:
    t = title.strip()
    t = re.sub(r"^\d+(\.\d+)*\s*", "", t)
    t = re.sub(r"\\[a-zA-Z@]+", " ", t)
    t = re.sub(r"[{}]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip() or "Body"


def parse_sections(raw: str) -> list[SectionBlock]:
    doc = prepare_raw_document(raw)
    abstract_raw, doc = _extract_abstract(doc)

    stripped = doc
    matches = list(SECTION_PATTERN.finditer(stripped))
    sections: list[SectionBlock] = []

    if abstract_raw:
        abstract = clean_text(abstract_raw)
        if abstract:
            sections.append(SectionBlock("Abstract", None, abstract))

    if not matches:
        body = clean_text(stripped)
        if body:
            sections.append(SectionBlock("Body", None, body))
        return sections

    if matches[0].start() > 0:
        pre = stripped[: matches[0].start()]
        pre = strip_front_matter(pre)
        pre = clean_text(pre)
        if pre and estimate_tokens(pre) >= 30:
            sections.append(SectionBlock("Body", None, pre))

    current_section = "Body"
    current_subsection: str | None = None

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
        content = stripped[start:end].strip()
        if content:
            sections.append(
                SectionBlock(current_section, current_subsection, content)
            )

    return sections
