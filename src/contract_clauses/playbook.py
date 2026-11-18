from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from contract_clauses.models import ClauseDef, PhraseGroup, Playbook, RiskFlag, SEVERITY_ORDER

RAW_PREFIX = "re:"


class PlaybookError(ValueError):
    pass


def _literal_to_regex(alt: str) -> str:
    alt = alt.strip()
    if not alt:
        raise PlaybookError("alternativa vacía en grupo de frases")
    parts = []
    for tok in alt.split():
        if tok.endswith("*"):
            parts.append(re.escape(tok[:-1]) + r"\w*")
        else:
            parts.append(re.escape(tok))
    return r"\s+".join(parts)


def compile_group(spec: str) -> PhraseGroup:
    spec = spec.strip()
    if not spec:
        raise PlaybookError("grupo de frases vacío")
    try:
        if spec.startswith(RAW_PREFIX):
            body = spec[len(RAW_PREFIX):]
            pattern = re.compile(body, re.IGNORECASE)
        else:
            alts = [_literal_to_regex(a) for a in spec.split("|")]
            pattern = re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")(?!\w)", re.IGNORECASE)
    except re.error as exc:
        raise PlaybookError(f"regex inválida en '{spec}': {exc}") from exc
    return PhraseGroup(raw=spec, pattern=pattern)


def _parse_risk_flag(clause_id: str, raw: dict[str, Any]) -> RiskFlag:
    for key in ("id", "pattern", "note"):
        if not raw.get(key):
            raise PlaybookError(f"{clause_id}: risk_flag sin '{key}'")
    severity = raw.get("severity", "medium")
    if severity not in SEVERITY_ORDER or severity == "none":
        raise PlaybookError(f"{clause_id}: severidad inválida '{severity}'")
    try:
        pattern = re.compile(raw["pattern"], re.IGNORECASE)
    except re.error as exc:
        raise PlaybookError(f"{clause_id}/{raw['id']}: regex inválida: {exc}") from exc
    return RiskFlag(id=raw["id"], pattern=pattern, note=raw["note"], severity=severity)


def _parse_clause(raw: dict[str, Any]) -> ClauseDef:
    cid = raw.get("id")
    if not cid:
        raise PlaybookError("cláusula sin 'id'")
    if not raw.get("title"):
        raise PlaybookError(f"{cid}: falta 'title'")
    must = raw.get("must_have") or []
    if not must:
        raise PlaybookError(f"{cid}: 'must_have' no puede estar vacío")
    weight = float(raw.get("weight", 1))
    if weight <= 0:
        raise PlaybookError(f"{cid}: 'weight' debe ser positivo")
    return ClauseDef(
        id=cid,
        title=raw["title"],
        critical=bool(raw.get("critical", False)),
        weight=weight,
        must_have=tuple(compile_group(g) for g in must),
        keywords=tuple(compile_group(g) for g in raw.get("keywords", [])),
        risk_flags=tuple(_parse_risk_flag(cid, f) for f in raw.get("risk_flags", [])),
        if_missing=raw.get("if_missing", ""),
        suggestion=raw.get("suggestion", ""),
        description=raw.get("description", ""),
    )


def parse_playbook(data: dict[str, Any], source: str = "") -> Playbook:
    clauses_raw = data.get("clauses")
    if not isinstance(clauses_raw, list) or not clauses_raw:
        raise PlaybookError("el playbook necesita una lista 'clauses'")
    clauses = tuple(_parse_clause(c) for c in clauses_raw)
    seen: set[str] = set()
    for clause in clauses:
        if clause.id in seen:
            raise PlaybookError(f"id duplicado: {clause.id}")
        seen.add(clause.id)
    return Playbook(
        name=data.get("name", "playbook"),
        version=str(data.get("version", "1")),
        description=data.get("description", ""),
        clauses=clauses,
        source=source,
    )


def load_playbook(path: str | Path) -> Playbook:
    p = Path(path)
    if not p.is_file():
        raise PlaybookError(f"playbook no encontrado: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlaybookError(f"JSON inválido en {p}: {exc}") from exc
    return parse_playbook(data, source=str(p))
