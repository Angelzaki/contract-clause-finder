from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from contract_clauses import DEFAULT_PLAYBOOK, DEFAULT_RESULTS, GOOD_SAMPLE, SAMPLES, WEAK_SAMPLE, __version__
from contract_clauses.corpus import CorpusError, Document, documents_from_texts, load_documents
from contract_clauses.playbook import PlaybookError, load_playbook, parse_playbook
from contract_clauses.report import compare_reports, render_markdown, write_reports
from contract_clauses.scorer import run_scan
from contract_clauses.store import get_run, list_runs, save_run

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
MAX_UPLOAD_CHARS = 1_000_000


class UploadedDoc(BaseModel):
    name: str = "contract.txt"
    text: str = Field(max_length=MAX_UPLOAD_CHARS)


class ScanRequest(BaseModel):
    playbook: str | None = None
    playbook_json: dict[str, Any] | None = None
    samples: list[str] = Field(default_factory=list)
    documents: list[UploadedDoc] = Field(default_factory=list)
    label: str = ""


def list_samples() -> dict[str, list[str]]:
    return {
        "playbooks": sorted(p.name for p in (SAMPLES / "playbook").glob("*.json")),
        "contracts": sorted(p.name for p in (SAMPLES / "contracts").glob("*.txt")),
    }


def _sample_path(kind: str, name: str) -> Path:
    if name not in list_samples()[kind]:
        raise CorpusError(f"muestra desconocida: {name}")
    folder = "playbook" if kind == "playbooks" else "contracts"
    return SAMPLES / folder / name


def _documents(req: ScanRequest) -> list[Document]:
    docs: list[Document] = []
    for name in req.samples:
        docs.extend(load_documents(_sample_path("contracts", name)))
    if req.documents:
        docs.extend(documents_from_texts([(d.name, d.text) for d in req.documents]))
    if not docs:
        raise CorpusError("selecciona un contrato de muestra o pega texto")
    return docs


def execute_scan(req: ScanRequest, results_dir: str | Path = DEFAULT_RESULTS) -> dict[str, Any]:
    if req.playbook_json is not None:
        playbook = parse_playbook(req.playbook_json, source="upload")
    elif req.playbook:
        playbook = load_playbook(_sample_path("playbooks", req.playbook))
    else:
        playbook = load_playbook(DEFAULT_PLAYBOOK)
    report = run_scan(playbook, _documents(req), label=req.label or "web:scan")
    write_reports(report, results_dir)
    run_id = save_run(Path(results_dir) / "history.db", report)
    payload = report.to_dict()
    payload["run_id"] = run_id
    return payload


def create_app(results_dir: str | Path = DEFAULT_RESULTS) -> FastAPI:
    app = FastAPI(title="contract-clause-finder", version=__version__)
    db_path = Path(results_dir) / "history.db"

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        ctx = {
            "samples": list_samples(),
            "default_playbook": DEFAULT_PLAYBOOK.name,
            "good": GOOD_SAMPLE.name,
            "weak": WEAK_SAMPLE.name,
            "version": __version__,
        }
        return TEMPLATES.TemplateResponse(request, "index.html", ctx)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/samples")
    def api_samples() -> dict[str, list[str]]:
        return list_samples()

    @app.post("/api/scan")
    def api_scan(req: ScanRequest) -> dict[str, Any]:
        try:
            return execute_scan(req, results_dir)
        except (PlaybookError, CorpusError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/compare")
    def api_compare(a: str = GOOD_SAMPLE.name, b: str = WEAK_SAMPLE.name, playbook: str | None = None) -> dict[str, Any]:
        try:
            first = execute_scan(ScanRequest(playbook=playbook, samples=[a], label="web:compare:a"), results_dir)
            second = execute_scan(ScanRequest(playbook=playbook, samples=[b], label="web:compare:b"), results_dir)
        except (PlaybookError, CorpusError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return compare_reports(first, second)

    @app.get("/api/history")
    def api_history(limit: int = 20) -> list[dict[str, Any]]:
        return list_runs(db_path, min(max(limit, 1), 200))

    @app.get("/api/history/{run_id}")
    def api_history_item(run_id: int) -> dict[str, Any]:
        payload = get_run(db_path, run_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="corrida no encontrada")
        return payload

    @app.get("/api/history/{run_id}/report.md", response_class=PlainTextResponse)
    def api_history_markdown(run_id: int) -> str:
        payload = get_run(db_path, run_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="corrida no encontrada")
        return render_markdown(payload)

    return app


app = create_app()
