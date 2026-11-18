from __future__ import annotations

from pathlib import Path

__version__ = "0.1.0"

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"
DEFAULT_PLAYBOOK = SAMPLES / "playbook" / "saas_clauses.json"
GOOD_SAMPLE = SAMPLES / "contracts" / "good_msa.txt"
WEAK_SAMPLE = SAMPLES / "contracts" / "weak_msa.txt"
DEFAULT_RESULTS = "results"
DEFAULT_PORT = 8031
