from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from .models import AnalysisResult, Evidence, Scan, ScanStatus


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / ".bfo-data"
REPOS_DIR = DATA_DIR / "repos"
SCANS_DIR = DATA_DIR / "scans"
EVIDENCE_INDEX_LOCK = Lock()


def ensure_storage() -> None:
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    SCANS_DIR.mkdir(parents=True, exist_ok=True)


def scan_dir(scan_id: str) -> Path:
    return ensure_scan_dir(scan_id)


def scan_dir_path(scan_id: str) -> Path:
    return SCANS_DIR / scan_id


def ensure_scan_dir(scan_id: str) -> Path:
    ensure_storage()
    path = scan_dir_path(scan_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_scan(scan: Scan) -> None:
    path = ensure_scan_dir(scan.id)
    (path / "scan.json").write_text(scan.model_dump_json(indent=2), encoding="utf-8")


def load_scan(scan_id: str) -> Scan | None:
    path = scan_dir_path(scan_id) / "scan.json"
    if not path.exists():
        return None
    return Scan.model_validate_json(path.read_text(encoding="utf-8"))


def update_scan(scan_id: str, **changes: Any) -> Scan:
    scan = load_scan(scan_id)
    if scan is None:
        raise KeyError(scan_id)
    updated = scan.model_copy(update=changes)
    save_scan(updated)
    return updated


def save_result(scan_id: str, result: AnalysisResult) -> None:
    path = ensure_scan_dir(scan_id) / "analysis.json"
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    save_artifacts(scan_id, result)


def load_result(scan_id: str) -> AnalysisResult | None:
    path = scan_dir_path(scan_id) / "analysis.json"
    if not path.exists():
        return None
    return AnalysisResult.model_validate_json(path.read_text(encoding="utf-8"))


def save_artifacts(scan_id: str, result: AnalysisResult) -> None:
    path = ensure_scan_dir(scan_id)
    artifact_payloads = {
        "repository.json": result.overview.repo,
        "graph.json": result.structure,
        "flows.json": result.flows,
        "risks.json": result.risks,
        "evidence.json": result.evidence,
        "diagnostics.json": result.diagnostics,
        "summary.json": result.summary,
    }
    for filename, payload in artifact_payloads.items():
        artifact_path = path / filename
        if payload is None:
            artifact_path.write_text("null\n", encoding="utf-8")
        elif hasattr(payload, "model_dump_json"):
            artifact_path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        else:
            artifact_path.write_text(json.dumps(payload, indent=2, default=lambda item: item.model_dump()), encoding="utf-8")


def save_evidence_index(scan_id: str, evidence: dict[str, Evidence]) -> None:
    ensure_storage()
    index_path = DATA_DIR / "evidence-index.json"
    tmp_path = DATA_DIR / "evidence-index.tmp"
    with EVIDENCE_INDEX_LOCK:
        index: dict[str, str] = {}
        if index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))
        for evidence_id in evidence:
            index[evidence_id] = scan_id
        tmp_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
        tmp_path.replace(index_path)


def find_evidence(evidence_id: str) -> Evidence | None:
    index_path = DATA_DIR / "evidence-index.json"
    if not index_path.exists():
        return None
    index = json.loads(index_path.read_text(encoding="utf-8"))
    scan_id = index.get(evidence_id)
    if not scan_id:
        return None
    result = load_result(scan_id)
    if not result:
        return None
    return result.evidence.get(evidence_id)


def fail_scan(scan_id: str, message: str) -> Scan:
    return update_scan(scan_id, status=ScanStatus.failed, progress=100, phase="failed", error=message)
