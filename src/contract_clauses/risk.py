from __future__ import annotations

import re
from dataclasses import dataclass

from contract_clauses.corpus import Document
from contract_clauses.models import (
    SEVERITY_ORDER,
    STATUS_MISSING,
    STATUS_PARTIAL,
    ClauseDef,
    RiskFinding,
)


@dataclass(frozen=True)
class GenericRule:
    id: str
    pattern: re.Pattern[str]
    note: str
    severity: str


def _rule(rule_id: str, pattern: str, note: str, severity: str) -> GenericRule:
    return GenericRule(rule_id, re.compile(pattern, re.IGNORECASE), note, severity)


GENERIC_RULES: tuple[GenericRule, ...] = (
    _rule(
        "best-efforts",
        r"\b(?:best|reasonable|commercially\s+reasonable|good[\s-]faith)\s+efforts?\b|\bendeavou?rs?\s+to\b",
        "Lenguaje de esfuerzo en lugar de obligación firme",
        "medium",
    ),
    _rule(
        "sole-discretion",
        r"\b(?:sole|absolute)\s+discretion\b",
        "Decisión a discreción exclusiva de una parte",
        "medium",
    ),
    _rule(
        "as-is",
        r"\bas[\s-]is\b|\bas[\s-]available\b",
        "Servicio entregado 'tal cual' sin compromiso de calidad",
        "medium",
    ),
    _rule(
        "no-obligation",
        r"\bno\s+obligation\s+to\b|\bnot\s+obligated\s+to\b|\bunder\s+no\s+obligation\b",
        "Se declara expresamente que no existe obligación",
        "medium",
    ),
    _rule(
        "without-notice",
        r"\bwithout\s+(?:prior\s+)?notice\b",
        "Acción permitida sin aviso previo",
        "medium",
    ),
    _rule(
        "undefined-term",
        r"\bto\s+be\s+(?:agreed|determined|defined)\b|\bTBD\b|\bas\s+(?:the\s+parties\s+)?may\s+be\s+agreed\b",
        "Término pendiente de definir",
        "medium",
    ),
    _rule(
        "unlimited-liability",
        r"\bunlimited\s+liabilit\w+|\bliabilit\w+\s+(?:shall\s+be\s+|is\s+|will\s+be\s+)?unlimited\b",
        "Responsabilidad ilimitada",
        "high",
    ),
    _rule(
        "unilateral-amendment",
        r"\b(?:amend|modify|change|update)\w*\s+(?:this\s+agreement|these\s+terms)[^.]{0,60}(?:unilateral\w*|at\s+any\s+time|sole\s+discretion)",
        "Modificación unilateral del contrato",
        "high",
    ),
    _rule(
        "optional-provider",
        r"\b(?:provider|supplier|vendor|company|licensor)\s+may\b",
        "'may' del lado del proveedor: la prestación es facultativa",
        "low",
    ),
    _rule(
        "may-but-not-obliged",
        r"\bmay,?\s+but\s+(?:is|shall|will)\s+not\s+(?:be\s+)?(?:obligated|required)",
        "Facultad sin obligación asociada",
        "medium",
    ),
)


def scan_window(
    doc: Document,
    start: int,
    end: int,
    clause: ClauseDef,
) -> list[RiskFinding]:
    chunk = doc.text[start:end]
    findings: list[RiskFinding] = []
    seen: set[int] = set()

    def add(rule_id: str, severity: str, note: str, m: re.Match[str]) -> None:
        key = m.start()
        if key in seen:
            return
        seen.add(key)
        findings.append(
            RiskFinding(
                rule=rule_id,
                severity=severity,
                note=note,
                span=doc.span(start + m.start(), start + m.end()),
            )
        )

    for flag in clause.risk_flags:
        for m in flag.pattern.finditer(chunk):
            add(flag.id, flag.severity, flag.note, m)
    for rule in GENERIC_RULES:
        for m in rule.pattern.finditer(chunk):
            add(rule.id, rule.severity, rule.note, m)
    findings.sort(key=lambda f: (-SEVERITY_ORDER[f.severity], f.span.start if f.span else 0))
    return findings


def gap_findings(clause: ClauseDef, status: str, unmatched: list[str]) -> list[RiskFinding]:
    if status == STATUS_MISSING:
        note = clause.if_missing or f"Cláusula ausente: {clause.title}"
        severity = "high" if clause.critical else "medium"
        return [RiskFinding(rule="gap-missing", severity=severity, note=note)]
    if status == STATUS_PARTIAL and unmatched:
        shown = "; ".join(g.split("|")[0] for g in unmatched[:3])
        severity = "medium" if clause.critical else "low"
        return [
            RiskFinding(
                rule="gap-partial",
                severity=severity,
                note=f"Cobertura parcial, falta: {shown}",
            )
        ]
    return []


def max_severity(findings: list[RiskFinding]) -> str:
    level = "none"
    for f in findings:
        if SEVERITY_ORDER[f.severity] > SEVERITY_ORDER[level]:
            level = f.severity
    return level
