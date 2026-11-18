from __future__ import annotations

import re
from dataclasses import dataclass, field

from contract_clauses.corpus import Document
from contract_clauses.models import (
    STATUS_FOUND,
    STATUS_MISSING,
    STATUS_PARTIAL,
    ClauseDef,
    ClauseResult,
    Span,
)
from contract_clauses.risk import gap_findings, max_severity, scan_window

MAX_WINDOW_UNITS = 8
MAX_WINDOW_CHARS = 2400
KEYWORD_ONLY_MIN_HITS = 2
MAX_COUNTER_EVIDENCE = 3

_NEGATION = re.compile(r"\b(?:no|not|never|neither|nor|without|cannot)\s+(?:\w+\s+){0,2}$", re.IGNORECASE)
_IN_NO_EVENT = re.compile(r"\bin\s+$", re.IGNORECASE)

Range = tuple[int, int]


@dataclass
class UnitHits:
    groups: dict[int, Range] = field(default_factory=dict)
    negated: dict[int, list[Range]] = field(default_factory=dict)
    keywords: dict[int, Range] = field(default_factory=dict)


@dataclass
class Candidate:
    doc: Document
    start: int
    end: int
    groups: dict[int, Range]
    keywords: dict[int, Range]

    @property
    def key(self) -> tuple[int, int, int]:
        return (len(self.groups), len(self.keywords), -(self.end - self.start))


def is_negated(text: str, start: int) -> bool:
    prefix = text[max(0, start - 48):start]
    cue = _NEGATION.search(prefix)
    if cue is None:
        return False
    return _IN_NO_EVENT.search(prefix[: cue.start()]) is None


def _unit_hits(doc: Document, clause: ClauseDef, start: int, end: int) -> UnitHits:
    text = doc.text
    chunk = text[start:end]
    hits = UnitHits()
    for gi, group in enumerate(clause.must_have):
        for m in group.pattern.finditer(chunk):
            abs_start = start + m.start()
            abs_end = start + m.end()
            if gi == 0 and is_negated(text, abs_start):
                hits.negated.setdefault(gi, []).append((abs_start, abs_end))
                continue
            hits.groups.setdefault(gi, (abs_start, abs_end))
    for ki, group in enumerate(clause.keywords):
        m = group.pattern.search(chunk)
        if m:
            hits.keywords[ki] = (start + m.start(), start + m.end())
    return hits


def _best_candidate(doc: Document, clause: ClauseDef, per_unit: list[UnitHits]) -> Candidate | None:
    best: Candidate | None = None
    units = doc.units
    for i in range(len(units)):
        groups: dict[int, Range] = {}
        keywords: dict[int, Range] = {}
        start = units[i][0]
        for j in range(i, min(len(units), i + MAX_WINDOW_UNITS)):
            end = units[j][1]
            if j > i and (end - start > MAX_WINDOW_CHARS or doc.sections[j] != doc.sections[i]):
                break
            for gi, rng in per_unit[j].groups.items():
                groups.setdefault(gi, rng)
            for ki, rng in per_unit[j].keywords.items():
                keywords.setdefault(ki, rng)
            if not groups and not keywords:
                continue
            cand = Candidate(doc, start, end, dict(groups), dict(keywords))
            if best is None or cand.key > best.key:
                best = cand
    return best


def find_clause(clause: ClauseDef, docs: list[Document]) -> ClauseResult:
    best: Candidate | None = None
    counter: list[Span] = []
    for doc in docs:
        per_unit = [_unit_hits(doc, clause, s, e) for (s, e) in doc.units]
        for hits in per_unit:
            for rng in hits.negated.get(0, []):
                if len(counter) < MAX_COUNTER_EVIDENCE:
                    counter.append(_sentence_span(doc, rng))
        cand = _best_candidate(doc, clause, per_unit)
        if cand is not None and (best is None or cand.key > best.key):
            best = cand

    total_groups = len(clause.must_have)
    total_keywords = len(clause.keywords)
    groups_hit = len(best.groups) if best else 0
    keywords_hit = len(best.keywords) if best else 0

    anchored = best is not None and 0 in best.groups
    if best is not None and groups_hit == total_groups:
        status = STATUS_FOUND
    elif best is not None and (
        anchored or groups_hit >= 2 or (groups_hit == 0 and keywords_hit >= KEYWORD_ONLY_MIN_HITS)
    ):
        status = STATUS_PARTIAL
    else:
        status = STATUS_MISSING

    if status == STATUS_MISSING:
        groups_hit = 0
        keywords_hit = 0

    result = ClauseResult(
        clause_id=clause.id,
        title=clause.title,
        critical=clause.critical,
        weight=clause.weight,
        status=status,
        group_ratio=groups_hit / total_groups,
        keyword_ratio=(keywords_hit / total_keywords) if total_keywords else 0.0,
        suggestion=clause.suggestion,
        counter_evidence=counter,
    )
    result.unmatched = [
        g.raw
        for gi, g in enumerate(clause.must_have)
        if status == STATUS_MISSING or best is None or gi not in best.groups
    ]

    if status != STATUS_MISSING and best is not None:
        result.quote = best.doc.span(best.start, best.end)
        result.matched = [clause.must_have[gi].raw for gi in sorted(best.groups)]
        result.keywords_hit = [clause.keywords[ki].raw for ki in sorted(best.keywords)]
        result.evidence = [best.doc.span(*best.groups[gi]) for gi in sorted(best.groups)]
        risks = scan_window(best.doc, best.start, best.end, clause)
    else:
        risks = []

    risks.extend(gap_findings(clause, status, result.unmatched))
    result.risks = risks
    result.risk_level = max_severity(risks)
    return result


def _sentence_span(doc: Document, rng: Range) -> Span:
    text = doc.text
    start = max(text.rfind(".", 0, rng[0]), text.rfind("\n", 0, rng[0])) + 1
    ends = [i for i in (text.find(".", rng[1]), text.find("\n", rng[1])) if i != -1]
    end = (min(ends) + 1) if ends else len(text)
    return doc.span(start, end)


def find_all(clauses: tuple[ClauseDef, ...], docs: list[Document]) -> list[ClauseResult]:
    return [find_clause(c, docs) for c in clauses]
