from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

STATUS_FOUND = "found"
STATUS_PARTIAL = "partial"
STATUS_MISSING = "missing"

SEVERITY_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


@dataclass(frozen=True)
class Span:
    doc: str
    start: int
    end: int
    line: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc": self.doc,
            "start": self.start,
            "end": self.end,
            "line": self.line,
            "text": self.text,
        }


@dataclass(frozen=True)
class PhraseGroup:
    raw: str
    pattern: re.Pattern[str] = field(repr=False, compare=False)


@dataclass(frozen=True)
class RiskFlag:
    id: str
    pattern: re.Pattern[str] = field(repr=False, compare=False)
    note: str
    severity: str


@dataclass(frozen=True)
class ClauseDef:
    id: str
    title: str
    critical: bool
    weight: float
    must_have: tuple[PhraseGroup, ...]
    keywords: tuple[PhraseGroup, ...]
    risk_flags: tuple[RiskFlag, ...]
    if_missing: str
    suggestion: str
    description: str = ""


@dataclass(frozen=True)
class Playbook:
    name: str
    version: str
    description: str
    clauses: tuple[ClauseDef, ...]
    source: str = ""


@dataclass(frozen=True)
class RiskFinding:
    rule: str
    severity: str
    note: str
    span: Span | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "note": self.note,
            "span": self.span.to_dict() if self.span else None,
        }


@dataclass
class ClauseResult:
    clause_id: str
    title: str
    critical: bool
    weight: float
    status: str
    group_ratio: float
    keyword_ratio: float
    score: float = 0.0
    adjusted_score: float = 0.0
    quote: Span | None = None
    matched: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    keywords_hit: list[str] = field(default_factory=list)
    evidence: list[Span] = field(default_factory=list)
    counter_evidence: list[Span] = field(default_factory=list)
    risks: list[RiskFinding] = field(default_factory=list)
    risk_level: str = "none"
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_id": self.clause_id,
            "title": self.title,
            "critical": self.critical,
            "weight": self.weight,
            "status": self.status,
            "group_ratio": round(self.group_ratio, 3),
            "keyword_ratio": round(self.keyword_ratio, 3),
            "score": round(self.score, 3),
            "adjusted_score": round(self.adjusted_score, 3),
            "quote": self.quote.to_dict() if self.quote else None,
            "matched": self.matched,
            "unmatched": self.unmatched,
            "keywords_hit": self.keywords_hit,
            "evidence": [s.to_dict() for s in self.evidence],
            "counter_evidence": [s.to_dict() for s in self.counter_evidence],
            "risks": [r.to_dict() for r in self.risks],
            "risk_level": self.risk_level,
            "suggestion": self.suggestion,
        }


@dataclass
class ScanReport:
    playbook: str
    playbook_version: str
    contracts: list[str]
    results: list[ClauseResult]
    coverage_pct: float
    risk_adjusted_pct: float
    verdict: str
    counts: dict[str, int]
    critical_missing: list[str]
    critical_gaps: list[str]
    risky_clauses: list[str]
    generated_at: str
    label: str = ""

    def result_for(self, clause_id: str) -> ClauseResult | None:
        for res in self.results:
            if res.clause_id == clause_id:
                return res
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "playbook": self.playbook,
            "playbook_version": self.playbook_version,
            "contracts": self.contracts,
            "label": self.label,
            "generated_at": self.generated_at,
            "coverage_pct": self.coverage_pct,
            "risk_adjusted_pct": self.risk_adjusted_pct,
            "verdict": self.verdict,
            "counts": self.counts,
            "critical_missing": self.critical_missing,
            "critical_gaps": self.critical_gaps,
            "risky_clauses": self.risky_clauses,
            "results": [r.to_dict() for r in self.results],
        }
