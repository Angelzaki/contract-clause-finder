from __future__ import annotations

import argparse
import sys
from pathlib import Path

from contract_clauses import (
    DEFAULT_PLAYBOOK,
    DEFAULT_PORT,
    DEFAULT_RESULTS,
    GOOD_SAMPLE,
    WEAK_SAMPLE,
)
from contract_clauses.corpus import CorpusError, load_documents
from contract_clauses.models import ScanReport
from contract_clauses.playbook import PlaybookError, load_playbook
from contract_clauses.report import compare_reports, write_comparison, write_reports
from contract_clauses.scorer import run_scan
from contract_clauses.store import list_runs, save_run

STATUS_LABEL = {"found": "found", "partial": "partial", "missing": "MISSING"}


def scan_paths(playbook_path: str | Path, contract_paths: list[str | Path], label: str = "") -> ScanReport:
    playbook = load_playbook(playbook_path)
    docs = []
    for path in contract_paths:
        docs.extend(load_documents(path))
    return run_scan(playbook, docs, label=label)


def print_summary(report: ScanReport) -> None:
    print(f"Playbook : {report.playbook} v{report.playbook_version}")
    print(f"Contratos: {', '.join(report.contracts)}")
    print(f"Cobertura: {report.coverage_pct}% (ajustada por riesgo {report.risk_adjusted_pct}%) -> {report.verdict}")
    c = report.counts
    print(f"Cláusulas: {c['found']} found, {c['partial']} partial, {c['missing']} missing")
    print()
    print(f"{'ID':<9}{'Estado':<9}{'Crit':<6}{'Riesgo':<8}{'Pts':<6}Ubicación")
    for r in report.results:
        where = f"{r.quote.doc}:L{r.quote.line} [{r.quote.start}-{r.quote.end}]" if r.quote else "-"
        crit = "sí" if r.critical else ""
        print(f"{r.clause_id:<9}{STATUS_LABEL[r.status]:<9}{crit:<6}{r.risk_level:<8}{r.score:<6.2f}{where}")
    print()
    if report.critical_missing:
        print("Críticas faltantes: " + ", ".join(report.critical_missing))
    else:
        print("Críticas faltantes: ninguna")
    risky = [r for r in report.results if r.risk_level in ("medium", "high")]
    if risky:
        print("Cláusulas con riesgo: " + ", ".join(f"{r.clause_id}({r.risk_level})" for r in risky))


def cmd_scan(args: argparse.Namespace) -> int:
    contracts = args.contract or [str(GOOD_SAMPLE)]
    report = scan_paths(args.playbook, contracts, label=args.label or "cli:scan")
    md_path, json_path = write_reports(report, args.out)
    run_id = None
    if not args.no_store:
        run_id = save_run(Path(args.out) / "history.db", report)
    print_summary(report)
    print()
    print(f"Informe: {md_path}")
    print(f"JSON   : {json_path}")
    if run_id is not None:
        print(f"Historial: {Path(args.out) / 'history.db'} (corrida #{run_id})")
    if args.fail_under is not None and report.coverage_pct < args.fail_under:
        print(f"Cobertura {report.coverage_pct}% por debajo del umbral {args.fail_under}%", file=sys.stderr)
        return 2
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    good = scan_paths(args.playbook, [args.good], label="cli:compare:a")
    weak = scan_paths(args.playbook, [args.weak], label="cli:compare:b")
    cmp = compare_reports(good.to_dict(), weak.to_dict())
    md_path, json_path = write_comparison(cmp, args.out)
    if not args.no_store:
        db = Path(args.out) / "history.db"
        save_run(db, good)
        save_run(db, weak)
    a_name = ", ".join(good.contracts)
    b_name = ", ".join(weak.contracts)
    print(f"{a_name}: {good.coverage_pct}% ({good.verdict})")
    print(f"{b_name}: {weak.coverage_pct}% ({weak.verdict})")
    print(f"Diferencia: {cmp['coverage_delta']:+} pts")
    print(f"Críticas faltantes en {b_name}: {', '.join(weak.critical_missing) or 'ninguna'}")
    print()
    print(f"{'ID':<9}{a_name:<16}{b_name:<16}{'Riesgo':<8}")
    for row in cmp["rows"]:
        print(f"{row['clause_id']:<9}{row['a_status']:<16}{row['b_status']:<16}{row['b_risk']:<8}")
    print()
    print(f"Comparación: {md_path}")
    print(f"JSON       : {json_path}")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    db = Path(args.db) if args.db else Path(DEFAULT_RESULTS) / "history.db"
    rows = list_runs(db, args.limit)
    if not rows:
        print(f"Sin corridas en {db}")
        return 0
    print(f"{'#':<5}{'Fecha (UTC)':<27}{'Cobertura':<11}{'Ajust.':<8}{'Veredicto':<12}{'F/P/M':<9}{'Crit.falta':<11}Contratos")
    for r in rows:
        fpm = f"{r['found']}/{r['partial']}/{r['missing']}"
        print(
            f"{r['id']:<5}{r['created_at']:<27}{str(r['coverage_pct']) + '%':<11}"
            f"{str(r['risk_adjusted_pct']) + '%':<8}{r['verdict']:<12}{fpm:<9}{r['critical_missing']:<11}{r['contracts']}"
        )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from contract_clauses.web import create_app

    app = create_app(results_dir=args.out)
    print(f"UI: http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contract-clauses",
        description="Buscador local de cláusulas contractuales (léxico/regex, sin LLM)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="evalúa uno o más contratos contra un playbook")
    scan.add_argument("--playbook", default=str(DEFAULT_PLAYBOOK))
    scan.add_argument("--contract", action="append", help="archivo o carpeta (repetible)")
    scan.add_argument("--out", default=DEFAULT_RESULTS)
    scan.add_argument("--label", default="")
    scan.add_argument("--no-store", action="store_true", help="no guardar en SQLite")
    scan.add_argument("--fail-under", type=float, default=None, help="salida 2 si la cobertura es menor")
    scan.set_defaults(func=cmd_scan)

    cmp = sub.add_parser("compare", help="compara un contrato sólido contra uno débil")
    cmp.add_argument("--playbook", default=str(DEFAULT_PLAYBOOK))
    cmp.add_argument("--good", default=str(GOOD_SAMPLE))
    cmp.add_argument("--weak", default=str(WEAK_SAMPLE))
    cmp.add_argument("--out", default=DEFAULT_RESULTS)
    cmp.add_argument("--no-store", action="store_true")
    cmp.set_defaults(func=cmd_compare)

    hist = sub.add_parser("history", help="lista corridas guardadas")
    hist.add_argument("--db", default="")
    hist.add_argument("--limit", type=int, default=20)
    hist.set_defaults(func=cmd_history)

    serve = sub.add_parser("serve", help="levanta la UI web")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--out", default=DEFAULT_RESULTS)
    serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (PlaybookError, CorpusError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
