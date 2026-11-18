from __future__ import annotations

import json
from pathlib import Path

import pytest

from contract_clauses import DEFAULT_PLAYBOOK, GOOD_SAMPLE, WEAK_SAMPLE
from contract_clauses.cli import main
from contract_clauses.corpus import Document, documents_from_texts, load_documents
from contract_clauses.finder import find_clause, is_negated
from contract_clauses.playbook import PlaybookError, compile_group, load_playbook, parse_playbook
from contract_clauses.report import compare_reports, render_markdown, write_reports
from contract_clauses.scorer import run_scan
from contract_clauses.store import get_run, list_runs, save_run
from contract_clauses.web import ScanRequest, execute_scan, list_samples

CRITICAL = {"DATA-01", "BRCH-01", "SEC-01", "CONF-01", "IND-01", "LIAB-01", "TRM-01"}


@pytest.fixture(scope="module")
def playbook():
    return load_playbook(DEFAULT_PLAYBOOK)


@pytest.fixture(scope="module")
def good(playbook):
    return run_scan(playbook, load_documents(GOOD_SAMPLE))


@pytest.fixture(scope="module")
def weak(playbook):
    return run_scan(playbook, load_documents(WEAK_SAMPLE))


def test_playbook_loads_and_marks_criticals(playbook):
    assert len(playbook.clauses) >= 20
    assert {c.id for c in playbook.clauses if c.critical} == CRITICAL


def test_good_msa_has_high_coverage(good):
    assert good.coverage_pct >= 90
    assert good.verdict == "strong"
    assert good.counts["missing"] == 0
    assert good.critical_missing == []
    assert good.critical_gaps == []


def test_weak_msa_misses_critical_clauses(weak, good):
    assert len(weak.critical_missing) >= 3
    assert {"LIAB-01", "TRM-01", "BRCH-01"} <= set(weak.critical_missing)
    assert weak.verdict == "weak"
    assert weak.coverage_pct < 50
    assert weak.coverage_pct < good.coverage_pct - 40


def test_weak_msa_flags_risky_language(weak):
    rules = {r.rule for res in weak.results for r in res.risks}
    assert {"best-efforts", "sole-discretion", "price-increase", "broad-license", "unilateral-change"} <= rules
    assert weak.risk_adjusted_pct < weak.coverage_pct
    assert "SVC-01" in weak.risky_clauses


def test_quotes_and_offsets_match_source(good):
    doc = load_documents(GOOD_SAMPLE)[0]
    for res in good.results:
        assert res.quote is not None, res.clause_id
        q = res.quote
        assert doc.text[q.start:q.end] == q.text
        assert q.line == doc.text.count("\n", 0, q.start) + 1
        for span in res.evidence:
            assert q.start <= span.start < span.end <= q.end
            assert doc.text[span.start:span.end] == span.text


def test_liability_clause_quote_points_at_section_12(good):
    res = good.result_for("LIAB-01")
    assert res.status == "found"
    assert "twelve (12) months" in res.quote.text
    assert res.quote.text.startswith("12.")
    assert "13. TERMINATION" not in res.quote.text


def test_negated_termination_is_counter_evidence(weak):
    res = weak.result_for("TRM-01")
    assert res.status == "missing"
    assert res.quote is None
    assert any("no right to terminate" in c.text for c in res.counter_evidence)
    assert any(r.rule == "gap-missing" and r.severity == "high" for r in res.risks)


def test_missing_clause_carries_gap_note_and_suggestion(weak):
    res = weak.result_for("LIAB-01")
    assert res.status == "missing"
    assert res.score == 0.0
    assert "ilimitada" in res.risks[0].note
    assert res.suggestion


def test_scores_are_ordered_by_status(good, weak):
    for report in (good, weak):
        for res in report.results:
            if res.status == "missing":
                assert res.score == 0
            elif res.status == "partial":
                assert 0 < res.score < 0.85
            else:
                assert 0.85 <= res.score <= 1.0
            assert res.adjusted_score <= res.score


def test_phrase_group_alternatives_and_wildcards():
    group = compile_group("terminat*|wind down")
    assert group.pattern.search("Either party may terminate")
    assert group.pattern.search("on Termination of this")
    assert group.pattern.search("a wind  down period")
    assert not group.pattern.search("exterminate")
    raw = compile_group(r"re:\d{2}(?:\.\d+)?\s*%")
    assert raw.pattern.search("uptime of 99.9% monthly")


def test_invalid_playbooks_are_rejected():
    with pytest.raises(PlaybookError):
        parse_playbook({"clauses": []})
    with pytest.raises(PlaybookError):
        parse_playbook({"clauses": [{"id": "A", "title": "A", "must_have": ["re:("]}]})
    with pytest.raises(PlaybookError):
        parse_playbook({"clauses": [{"id": "A", "title": "A", "must_have": []}]})
    dup = {"id": "A", "title": "A", "must_have": ["x"]}
    with pytest.raises(PlaybookError):
        parse_playbook({"clauses": [dup, dup]})


def test_negation_ignores_in_no_event():
    text = "In no event shall liability exceed the fees. The vendor does not provide indemnification."
    assert not is_negated(text, text.index("liability"))
    assert is_negated(text, text.index("indemnification"))


def test_keyword_only_mention_is_not_enough_for_found(playbook):
    clause = next(c for c in playbook.clauses if c.id == "LIAB-01")
    docs = documents_from_texts([("x.txt", "Mutual exclusions apply except for fraud or gross negligence.")])
    res = find_clause(clause, docs)
    assert res.status == "partial"
    assert res.group_ratio == 0.0


def test_unrelated_text_is_missing(playbook):
    docs = documents_from_texts([("x.txt", "The parties will meet on Tuesdays to discuss lunch.")])
    report = run_scan(playbook, docs)
    assert report.counts["found"] == 0
    assert report.coverage_pct == 0.0
    assert len(report.critical_missing) == len(CRITICAL)


def test_multiple_contracts_are_searched_together(playbook):
    docs = load_documents(GOOD_SAMPLE.parent)
    assert {d.name for d in docs} == {"good_msa.txt", "weak_msa.txt"}
    report = run_scan(playbook, docs)
    assert report.critical_missing == []
    assert report.result_for("LIAB-01").quote.doc == "good_msa.txt"


def test_sections_do_not_cross_headings():
    doc = Document("t.txt", "1. FIRST\n\n1.1 alpha text.\n\n2. SECOND\n\n2.1 beta text.\n")
    assert doc.sections == [0, 0, 1, 1]


def test_markdown_and_json_reports(tmp_path, good):
    md_path, json_path = write_reports(good, tmp_path)
    md = md_path.read_text(encoding="utf-8")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "## Matriz" in md and "LIAB-01" in md and "CIP 404730" in md
    assert data["coverage_pct"] == good.coverage_pct
    assert len(data["results"]) == len(good.results)
    assert render_markdown(data).count("### ") == len(good.results)


def test_compare_reports_rows(good, weak):
    cmp = compare_reports(good.to_dict(), weak.to_dict())
    assert cmp["coverage_delta"] < -40
    row = next(r for r in cmp["rows"] if r["clause_id"] == "LIAB-01")
    assert (row["a_status"], row["b_status"]) == ("found", "missing")
    assert row["delta"] < 0


def test_store_roundtrip(tmp_path, good, weak):
    db = tmp_path / "h.db"
    first = save_run(db, good)
    second = save_run(db, weak)
    runs = list_runs(db)
    assert [r["id"] for r in runs] == [second, first]
    assert runs[0]["critical_missing"] == len(weak.critical_missing)
    payload = get_run(db, first)
    assert payload["coverage_pct"] == good.coverage_pct
    assert get_run(db, 999) is None
    assert list_runs(tmp_path / "none.db") == []


def test_cli_scan_compare_history(tmp_path, capsys):
    out = str(tmp_path / "res")
    assert main(["scan", "--contract", str(WEAK_SAMPLE), "--out", out]) == 0
    assert (tmp_path / "res" / "clause_report.md").is_file()
    assert (tmp_path / "res" / "clause_report.json").is_file()
    assert main(["scan", "--contract", str(WEAK_SAMPLE), "--out", out, "--fail-under", "80", "--no-store"]) == 2
    assert main(["compare", "--out", out]) == 0
    assert (tmp_path / "res" / "compare_report.md").is_file()
    assert main(["history", "--db", str(tmp_path / "res" / "history.db")]) == 0
    text = capsys.readouterr().out
    assert "LIAB-01" in text and "weak" in text


def test_cli_reports_missing_inputs(tmp_path, capsys):
    assert main(["scan", "--contract", str(tmp_path / "nope.txt"), "--out", str(tmp_path)]) == 1
    assert "error:" in capsys.readouterr().err


def test_web_scan_uses_samples_and_pasted_text(tmp_path):
    assert "good_msa.txt" in list_samples()["contracts"]
    payload = execute_scan(ScanRequest(samples=["weak_msa.txt"]), tmp_path)
    assert payload["run_id"] == 1
    assert "LIAB-01" in payload["critical_missing"]
    pasted = execute_scan(
        ScanRequest(
            playbook="saas_clauses.json",
            documents=[{"name": "p.txt", "text": Path(GOOD_SAMPLE).read_text(encoding="utf-8")}],
        ),
        tmp_path,
    )
    assert pasted["coverage_pct"] == pytest.approx(
        run_scan(load_playbook(DEFAULT_PLAYBOOK), load_documents(GOOD_SAMPLE)).coverage_pct
    )
    with pytest.raises(Exception):
        execute_scan(ScanRequest(samples=["../../etc/passwd"]), tmp_path)
