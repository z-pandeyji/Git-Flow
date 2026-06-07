from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import uuid
from threading import BoundedSemaphore

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .analyzer import analyze_repo
from .flow_engine import build_flows
from .models import AnalysisResult, Scan, ScanRequest, ScanResponse, ScanStatus
from .pipeline import build_diagnostics, build_summary
from .risk_engine import find_risks
from .scanner import ScanInputError, clone_public_repo, create_demo_repo
from .storage import SCANS_DIR, fail_scan, find_evidence, load_result, load_scan, save_evidence_index, save_result, save_scan, update_scan


SCAN_MAX_WORKERS = int(os.getenv("BFO_SCAN_MAX_WORKERS", "2"))
SCAN_QUEUE_CAPACITY = int(os.getenv("BFO_SCAN_QUEUE_CAPACITY", "8"))
SCAN_EXECUTOR = ThreadPoolExecutor(max_workers=SCAN_MAX_WORKERS)
SCAN_CAPACITY = BoundedSemaphore(SCAN_QUEUE_CAPACITY)

app = FastAPI(title="Business GitFlow API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
def recover_interrupted_scans() -> None:
    if not SCANS_DIR.exists():
        return
    for scan_file in SCANS_DIR.glob("*/scan.json"):
        scan = load_scan(scan_file.parent.name)
        if scan and scan.status in {ScanStatus.queued, ScanStatus.running} and not load_result(scan.id):
            fail_scan(scan.id, "Scan interrupted before completion. Start a new scan.")


@app.post("/api/scans", response_model=ScanResponse)
def create_scan(request: ScanRequest) -> ScanResponse:
    if not SCAN_CAPACITY.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Too many scans in progress. Try again later.")
    scan_id = uuid.uuid4().hex
    scan = Scan(id=scan_id, repo_id="pending", status=ScanStatus.queued, progress=0, phase="queued")
    save_scan(scan)
    SCAN_EXECUTOR.submit(_run_scan_with_capacity_release, scan_id, request)
    return ScanResponse(scanId=scan_id)


@app.get("/api/scans/{scan_id}")
def get_scan(scan_id: str) -> dict[str, object]:
    scan = load_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return {
        "scanId": scan.id,
        "status": scan.status,
        "progress": scan.progress,
        "currentPhase": scan.phase,
        "errors": [scan.error] if scan.error else [],
    }


@app.get("/api/scans/{scan_id}/overview")
def get_overview(scan_id: str):
    return _result(scan_id).overview


@app.get("/api/scans/{scan_id}/structure")
def get_structure(scan_id: str):
    return _result(scan_id).structure


@app.get("/api/scans/{scan_id}/flows")
def get_flows(scan_id: str):
    return _result(scan_id).flows


@app.get("/api/scans/{scan_id}/risks")
def get_risks(scan_id: str):
    return _result(scan_id).risks


@app.get("/api/scans/{scan_id}/diagnostics")
def get_diagnostics(scan_id: str):
    return _result(scan_id).diagnostics


@app.get("/api/scans/{scan_id}/summary")
def get_summary(scan_id: str):
    return _result(scan_id).summary


@app.get("/api/evidence/{evidence_id}")
def get_evidence(evidence_id: str):
    evidence = find_evidence(evidence_id)
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return evidence


def _result(scan_id: str) -> AnalysisResult:
    scan = load_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan.status == ScanStatus.failed:
        raise HTTPException(status_code=422, detail=scan.error or "Scan failed")
    result = load_result(scan_id)
    if not result:
        raise HTTPException(status_code=202, detail="Scan is still running")
    return result


def _run_scan(scan_id: str, request: ScanRequest) -> None:
    try:
        update_scan(scan_id, status=ScanStatus.running, progress=10, phase="fetch")
        repo = create_demo_repo() if request.mode == "demo" else clone_public_repo(request.repoUrl)
        update_scan(scan_id, repo_id=repo.id, progress=25, phase="classify repository")
        analysis = analyze_repo(repo)
        update_scan(scan_id, progress=38, phase="build structure graph")
        update_scan(scan_id, progress=52, phase="detect execution paths")
        update_scan(scan_id, progress=65, phase="generate behavior flows")
        flows = build_flows(analysis)
        update_scan(scan_id, progress=74, phase="calculate confidence")
        update_scan(scan_id, progress=84, phase="rank risks")
        risks = find_risks(analysis)
        update_scan(scan_id, progress=92, phase="persist artifacts")
        ai_available = any(flow.ai_summary_available for flow in flows)
        diagnostics = build_diagnostics(analysis, len(flows), ai_available)
        summary = build_summary(analysis, len(flows), len(risks), ai_available)
        result = AnalysisResult(overview=analysis.overview, structure=analysis.structure, flows=flows, risks=risks, evidence=analysis.evidence, diagnostics=diagnostics, summary=summary)
        save_result(scan_id, result)
        save_evidence_index(scan_id, analysis.evidence)
        update_scan(scan_id, status=ScanStatus.completed, progress=100, phase="completed")
    except ScanInputError as exc:
        fail_scan(scan_id, str(exc))
    except Exception as exc:
        fail_scan(scan_id, f"Unexpected scan failure: {exc}")


def _run_scan_with_capacity_release(scan_id: str, request: ScanRequest) -> None:
    try:
        _run_scan(scan_id, request)
    finally:
        SCAN_CAPACITY.release()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.api:app", host="127.0.0.1", port=8000, reload=True)
