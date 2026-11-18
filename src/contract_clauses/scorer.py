from __future__ import annotations

from datetime import datetime, timezone

from contract_clauses.corpus import Document
from contract_clauses.finder import find_all
from contract_clauses.models import (
    STATUS_FOUND,
    STATUS_MISSING,
    STATUS_PARTIAL,
    ClauseResult,
    Playbook,
    ScanReport,
)

FOUND_BASE = 0.85
FOUND_KEYWORD_BONUS = 0.15
PARTIAL_BASE = 0.25
PARTIAL_GROUP_SPAN = 0.5

RISK_MULTIPLIER = {"none": 1.0, "low": 0.95, "medium": 0.85, "high": 0.6}

STRONG_MIN = 85.0
ACCEPTABLE_MIN = 65.0


def clause_score(res: ClauseResult) -> float:
    if res.status == STATUS_FOUND:
        return FOUND_BASE + FOUND_KEYWORD_BONUS * res.keyword_ratio
    if res.status == STATUS_PARTIAL:
        return PARTIAL_BASE + PARTIAL_GROUP_SPAN * res.group_ratio
    return 0.0


def text_risk_level(res: ClauseResult) -> str:
    order = {"none": 0, "low": 1, "medium": 2, "high": 3}
    level = "none"
    for risk in res.risks:
        if risk.span is not None and order[risk.severity] > order[level]:
            level = risk.severity
    return level


def apply_scores(results: list[ClauseResult]) -> None:
    for res in results:
        res.score = clause_score(res)
        res.adjusted_score = res.score * RISK_MULTIPLIER[text_risk_level(res)]


def weighted_pct(results: list[ClauseResult], adjusted: bool = False) -> float:
    total = sum(r.weight for r in results)
    if total == 0:
        return 0.0
    got = sum(r.weight * (r.adjusted_score if adjusted else r.score) for r in results)
    return round(100.0 * got / total, 1)


def verdict_for(coverage: float, critical_missing: list[str], critical_gaps: list[str]) -> str:
    if coverage >= STRONG_MIN and not critical_gaps:
        return "strong"
    if coverage >= ACCEPTABLE_MIN and not critical_missing:
        return "acceptable"
    return "weak"


def build_report(
    playbook: Playbook,
    docs: list[Document],
    results: list[ClauseResult],
    label: str = "",
) -> ScanReport:
    apply_scores(results)
    coverage = weighted_pct(results)
    adjusted = weighted_pct(results, adjusted=True)
    counts = {
        STATUS_FOUND: sum(1 for r in results if r.status == STATUS_FOUND),
        STATUS_PARTIAL: sum(1 for r in results if r.status == STATUS_PARTIAL),
        STATUS_MISSING: sum(1 for r in results if r.status == STATUS_MISSING),
    }
    critical_missing = [r.clause_id for r in results if r.critical and r.status == STATUS_MISSING]
    critical_gaps = [r.clause_id for r in results if r.critical and r.status != STATUS_FOUND]
    risky = [r.clause_id for r in results if r.risk_level in ("medium", "high")]
    return ScanReport(
        playbook=playbook.name,
        playbook_version=playbook.version,
        contracts=[d.name for d in docs],
        results=results,
        coverage_pct=coverage,
        risk_adjusted_pct=adjusted,
        verdict=verdict_for(coverage, critical_missing, critical_gaps),
        counts=counts,
        critical_missing=critical_missing,
        critical_gaps=critical_gaps,
        risky_clauses=risky,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        label=label,
    )


def run_scan(playbook: Playbook, docs: list[Document], label: str = "") -> ScanReport:
    results = find_all(playbook.clauses, docs)
    return build_report(playbook, docs, results, label=label)
