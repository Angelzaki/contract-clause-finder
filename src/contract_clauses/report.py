from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from contract_clauses.models import ScanReport

STATUS_ICON = {"found": "OK", "partial": "PARCIAL", "missing": "FALTA"}
QUOTE_LIMIT = 420


def excerpt(text: str, limit: int = QUOTE_LIMIT) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def locate(span: dict[str, Any]) -> str:
    return f"{span['doc']}:L{span['line']} [{span['start']}–{span['end']}]"


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_markdown(data: dict[str, Any]) -> str:
    counts = data["counts"]
    lines: list[str] = []
    lines.append(f"# Informe de cláusulas: {data['playbook']} v{data['playbook_version']}")
    lines.append("")
    lines.append(f"- Contratos: {', '.join(data['contracts'])}")
    lines.append(f"- Generado: {data['generated_at']}")
    lines.append(f"- Veredicto: **{data['verdict']}**")
    lines.append(f"- Cobertura: **{data['coverage_pct']}%** (ajustada por riesgo: {data['risk_adjusted_pct']}%)")
    lines.append(
        f"- Cláusulas: {counts['found']} found · {counts['partial']} partial · {counts['missing']} missing"
    )
    lines.append("")

    lines.append("## Críticas faltantes")
    lines.append("")
    titles = {r["clause_id"]: r["title"] for r in data["results"]}
    if data["critical_missing"]:
        for cid in data["critical_missing"]:
            lines.append(f"- `{cid}` {titles[cid]}")
    else:
        lines.append("Ninguna cláusula crítica ausente.")
    partial_critical = [c for c in data["critical_gaps"] if c not in data["critical_missing"]]
    if partial_critical:
        lines.append("")
        lines.append("Críticas con cobertura parcial: " + ", ".join(f"`{c}`" for c in partial_critical))
    lines.append("")

    lines.append("## Matriz")
    lines.append("")
    lines.append("| Cláusula | Título | Crítica | Estado | Puntaje | Riesgo | Ubicación |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in data["results"]:
        where = locate(r["quote"]) if r["quote"] else "-"
        lines.append(
            f"| {r['clause_id']} | {_cell(r['title'])} | {'sí' if r['critical'] else 'no'} | "
            f"{STATUS_ICON[r['status']]} | {r['score']:.2f} | {r['risk_level']} | {where} |"
        )
    lines.append("")

    lines.append("## Detalle")
    for r in data["results"]:
        lines.append("")
        lines.append(f"### {r['clause_id']} · {r['title']} — {r['status']}")
        lines.append("")
        if r["quote"]:
            lines.append(f"> {excerpt(r['quote']['text'])}")
            lines.append("")
            lines.append(f"Fuente: `{locate(r['quote'])}`")
        if r["evidence"]:
            lines.append("")
            lines.append("Evidencia por frase:")
            for span, raw in zip(r["evidence"], r["matched"]):
                lines.append(f"- `{span['text']}` en `{locate(span)}` ← `{raw}`")
        if r["unmatched"]:
            lines.append("")
            lines.append("Sin evidencia: " + "; ".join(f"`{g}`" for g in r["unmatched"]))
        if r["counter_evidence"]:
            lines.append("")
            lines.append("Contra-evidencia (negación):")
            for span in r["counter_evidence"]:
                lines.append(f"- «{excerpt(span['text'], 200)}» en `{locate(span)}`")
        if r["risks"]:
            lines.append("")
            lines.append("Riesgos:")
            for risk in r["risks"]:
                where = f" — «{risk['span']['text']}» en `{locate(risk['span'])}`" if risk["span"] else ""
                lines.append(f"- [{risk['severity']}] {risk['note']}{where}")
        if r["status"] != "found" and r["suggestion"]:
            lines.append("")
            lines.append(f"Texto sugerido: _{r['suggestion']}_")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Hecho en Lima · Angel Salazar · CIP 404730")
    lines.append("")
    return "\n".join(lines)


def write_reports(report: ScanReport, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    md_path = out / "clause_report.md"
    json_path = out / "clause_report.json"
    md_path.write_text(render_markdown(data), encoding="utf-8")
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return md_path, json_path


def compare_reports(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    rows = []
    by_b = {r["clause_id"]: r for r in b["results"]}
    for ra in a["results"]:
        rb = by_b.get(ra["clause_id"])
        rows.append(
            {
                "clause_id": ra["clause_id"],
                "title": ra["title"],
                "critical": ra["critical"],
                "a_status": ra["status"],
                "b_status": rb["status"] if rb else "missing",
                "a_risk": ra["risk_level"],
                "b_risk": rb["risk_level"] if rb else "none",
                "delta": round((rb["score"] if rb else 0.0) - ra["score"], 3),
            }
        )
    return {
        "a": {
            "contracts": a["contracts"],
            "coverage_pct": a["coverage_pct"],
            "verdict": a["verdict"],
            "critical_missing": a["critical_missing"],
        },
        "b": {
            "contracts": b["contracts"],
            "coverage_pct": b["coverage_pct"],
            "verdict": b["verdict"],
            "critical_missing": b["critical_missing"],
        },
        "coverage_delta": round(b["coverage_pct"] - a["coverage_pct"], 1),
        "rows": rows,
    }


def render_comparison(cmp: dict[str, Any]) -> str:
    a_name = ", ".join(cmp["a"]["contracts"])
    b_name = ", ".join(cmp["b"]["contracts"])
    lines = [
        f"# Comparación: {a_name} vs {b_name}",
        "",
        f"- {a_name}: {cmp['a']['coverage_pct']}% ({cmp['a']['verdict']})",
        f"- {b_name}: {cmp['b']['coverage_pct']}% ({cmp['b']['verdict']})",
        f"- Diferencia de cobertura: {cmp['coverage_delta']:+} pts",
        f"- Críticas faltantes en {b_name}: {', '.join(cmp['b']['critical_missing']) or 'ninguna'}",
        "",
        f"| Cláusula | Título | Crítica | {a_name} | {b_name} | Riesgo {b_name} | Δ |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in cmp["rows"]:
        lines.append(
            f"| {row['clause_id']} | {_cell(row['title'])} | {'sí' if row['critical'] else 'no'} | "
            f"{row['a_status']} | {row['b_status']} | {row['b_risk']} | {row['delta']:+.2f} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_comparison(cmp: dict[str, Any], out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / "compare_report.md"
    json_path = out / "compare_report.json"
    md_path.write_text(render_comparison(cmp), encoding="utf-8")
    json_path.write_text(json.dumps(cmp, indent=2, ensure_ascii=False), encoding="utf-8")
    return md_path, json_path
