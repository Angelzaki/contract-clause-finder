from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from pathlib import Path

from contract_clauses.models import Span

SUFFIXES = {".txt", ".md"}
MAX_BYTES = 2_000_000

_NUMBERED = re.compile(
    r"^\s*(?:\d+(?:\.\d+)+\.?|\d+[.)]|\([a-zA-Z0-9]{1,4}\)|[A-Z][.)]|(?:Section|Article|Clause)\s+[\dIVX]+[.:]?)\s+\S"
)


_HEADING = re.compile(r"^\s*(?:\d+[.)]|(?:Section|Article|Clause)\s+[\dIVX]+[.:]?)\s+\S")


class CorpusError(ValueError):
    pass


@dataclass
class Document:
    name: str
    text: str
    units: list[tuple[int, int]] = field(default_factory=list)
    sections: list[int] = field(default_factory=list)
    _line_starts: list[int] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._line_starts = [0] + [m.end() for m in re.finditer(r"\n", self.text)]
        self.units = _split_units(self.text)
        self.sections = _assign_sections(self.text, self.units)

    def line_of(self, offset: int) -> int:
        return bisect.bisect_right(self._line_starts, offset)

    def span(self, start: int, end: int) -> Span:
        while start < end and self.text[start].isspace():
            start += 1
        while end > start and self.text[end - 1].isspace():
            end -= 1
        return Span(
            doc=self.name,
            start=start,
            end=end,
            line=self.line_of(start),
            text=self.text[start:end],
        )


def _split_units(text: str) -> list[tuple[int, int]]:
    units: list[tuple[int, int]] = []
    cur_start: int | None = None
    cur_end = 0
    pos = 0
    for raw in text.splitlines(keepends=True):
        line_start = pos
        pos += len(raw)
        body = raw.strip()
        if not body:
            if cur_start is not None:
                units.append((cur_start, cur_end))
                cur_start = None
            continue
        if cur_start is not None and _NUMBERED.match(raw):
            units.append((cur_start, cur_end))
            cur_start = None
        if cur_start is None:
            cur_start = line_start + (len(raw) - len(raw.lstrip()))
        cur_end = line_start + len(raw.rstrip())
    if cur_start is not None:
        units.append((cur_start, cur_end))
    return units


def _is_heading(first_line: str) -> bool:
    stripped = first_line.strip()
    if _HEADING.match(first_line):
        return True
    letters = [c for c in stripped if c.isalpha()]
    return len(letters) >= 3 and len(stripped) <= 60 and stripped.upper() == stripped and not stripped.endswith(".")


def _assign_sections(text: str, units: list[tuple[int, int]]) -> list[int]:
    sections: list[int] = []
    current = 0
    for idx, (start, end) in enumerate(units):
        first_line = text[start:end].split("\n", 1)[0]
        if idx > 0 and _is_heading(first_line):
            current += 1
        sections.append(current)
    return sections


def _read(path: Path) -> str:
    if path.stat().st_size > MAX_BYTES:
        raise CorpusError(f"archivo demasiado grande (> {MAX_BYTES} bytes): {path}")
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        return fh.read()


def load_documents(path: str | Path) -> list[Document]:
    p = Path(path)
    if not p.exists():
        raise CorpusError(f"ruta no encontrada: {p}")
    if p.is_file():
        files = [p]
    else:
        files = sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in SUFFIXES)
    if not files:
        raise CorpusError(f"sin archivos .txt/.md en {p}")
    docs = [Document(name=f.name, text=_read(f)) for f in files]
    return docs


def documents_from_texts(items: list[tuple[str, str]]) -> list[Document]:
    docs = [Document(name=name or f"doc{i + 1}.txt", text=text) for i, (name, text) in enumerate(items) if text.strip()]
    if not docs:
        raise CorpusError("no hay texto de contrato para analizar")
    return docs
