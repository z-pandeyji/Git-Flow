from __future__ import annotations

from collections import Counter, defaultdict

from .analyzer import AnalyzerOutput
from .confidence import confidence_label, evidence_files, evidence_locations
from .models import RiskFinding


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}


def find_risks(analysis: AnalyzerOutput) -> list[RiskFinding]:
    risks: list[RiskFinding] = []
    risks.extend(_circular_dependencies(analysis))
    risks.extend(_god_services(analysis))
    risks.extend(_missing_validation(analysis))
    risks.extend(_hotspots(analysis))
    risks = [_hydrate_risk_metadata(risk, analysis) for risk in risks if any(evidence_id in analysis.evidence for evidence_id in risk.evidence_ids)]
    risks.sort(key=lambda risk: (SEVERITY_ORDER[risk.severity], risk.category, risk.title))
    for index, risk in enumerate(risks, start=1):
        risk.rank = index
    return risks


def _circular_dependencies(analysis: AnalyzerOutput) -> list[RiskFinding]:
    imports = defaultdict(set)
    for edge in analysis.structure.edges:
        if edge.kind == "imports":
            imports[edge.source].add(edge.target)
    findings = []
    seen = set()
    for source, targets in imports.items():
        for target in targets:
            if source in imports.get(target, set()):
                key = tuple(sorted([source, target]))
                if key in seen:
                    continue
                seen.add(key)
                evidence_ids = [node.evidence_id for node in analysis.structure.nodes if node.id in key and node.evidence_id]
                findings.append(RiskFinding(id=f"risk-cycle-{len(findings)+1}", title="Circular dependency candidate", category="circular-dependency", severity="high", description="Two files appear to import each other. Confirm before refactoring shared contracts.", evidence_ids=evidence_ids, why_it_matters="Circular dependencies make flow boundaries harder to reason about and can create fragile initialization order.", rank=0))
    return findings


def _god_services(analysis: AnalyzerOutput) -> list[RiskFinding]:
    findings = []
    for file in analysis.files:
        path = file.relative_path.lower()
        if any(part in path for part in ["/test", "tests/", "benchmark", "fixtures/"]):
            continue
        if "service" in file.indicators and (file.line_count > 300 or len(file.symbols) > 18):
            evidence = _file_evidence(analysis, file.relative_path)
            findings.append(RiskFinding(id=f"risk-god-{len(findings)+1}", title=f"Large service: {file.relative_path}", category="god-service", severity="medium", description="Service size or symbol count suggests multiple responsibilities.", evidence_ids=[evidence] if evidence else [], why_it_matters="Large services often hide multiple business flows in one module, reducing traceability.", rank=0))
    return findings


def _missing_validation(analysis: AnalyzerOutput) -> list[RiskFinding]:
    if analysis.overview.classification.get("dominantType") != "Business Application":
        return []
    findings = []
    validation_files = [file for file in analysis.files if "validation" in file.relative_path.lower() or "zod" in " ".join(file.imports).lower() or "joi" in " ".join(file.imports).lower()]
    for file in analysis.files:
        for route in file.routes:
            if not validation_files and str(route["method"]) in {"POST", "PUT", "PATCH"}:
                evidence = _matching_evidence(analysis, file.relative_path, str(route["label"]))
                findings.append(RiskFinding(id=f"risk-validation-{len(findings)+1}", title=f"Missing validation candidate: {route['label']}", category="missing-validation", severity="medium", description="Write route detected without nearby validation library or validation file evidence.", evidence_ids=[evidence] if evidence else [], why_it_matters="Write routes without validation can allow invalid business events into downstream flows.", rank=0))
    return findings[:8]


def _dead_code_candidates(analysis: AnalyzerOutput) -> list[RiskFinding]:
    imported_targets = {edge.target for edge in analysis.structure.edges if edge.kind == "imports"}
    findings = []
    for node in analysis.structure.nodes:
        if node.kind in {"service", "repository", "worker", "file"} and node.id.startswith("file:") and node.id not in imported_targets:
            if any(node.label in root for root in ["app.ts", "index.ts", "main.ts", "server.ts", "package.json"]):
                continue
            findings.append(RiskFinding(id=f"risk-dead-{len(findings)+1}", title=f"Unused module candidate: {node.file_path}", category="dead-code", severity="informational", description="No local import edge points to this file in the deterministic graph.", evidence_ids=[node.evidence_id] if node.evidence_id else [], why_it_matters="Unreferenced modules may represent dead behavior or dynamic wiring the scanner could not resolve.", rank=0))
    return findings[:10]


def _hotspots(analysis: AnalyzerOutput) -> list[RiskFinding]:
    incoming = Counter(edge.target for edge in analysis.structure.edges if edge.kind == "imports")
    findings = []
    for node_id, count in incoming.items():
        if count >= 8:
            node = next((candidate for candidate in analysis.structure.nodes if candidate.id == node_id), None)
            if node:
                findings.append(RiskFinding(id=f"risk-hotspot-{len(findings)+1}", title=f"Dependency hotspot: {node.file_path}", category="complexity-hotspot", severity="medium", description=f"{count} files import this module. Changes here may affect several flows.", evidence_ids=[node.evidence_id] if node.evidence_id else [], why_it_matters="Hotspots deserve careful review because one source change can alter many flow paths.", rank=0))
    return findings


def _file_evidence(analysis: AnalyzerOutput, file_path: str) -> str | None:
    for evidence in analysis.evidence.values():
        if evidence.file_path == file_path:
            return evidence.id
    return None


def _matching_evidence(analysis: AnalyzerOutput, file_path: str, symbol: str) -> str | None:
    for evidence in analysis.evidence.values():
        if evidence.file_path == file_path and evidence.symbol == symbol:
            return evidence.id
    return _file_evidence(analysis, file_path)


def _hydrate_risk_metadata(risk: RiskFinding, analysis: AnalyzerOutput) -> RiskFinding:
    evidence_items = [analysis.evidence[evidence_id] for evidence_id in risk.evidence_ids if evidence_id in analysis.evidence]
    score = {
        "critical": 92,
        "high": 78,
        "medium": 62,
        "low": 42,
        "informational": 30,
    }[risk.severity]
    return risk.model_copy(
        update={
            "confidence_score": score,
            "confidence_label": confidence_label(score),
            "evidence_count": len(evidence_items),
            "source_files": evidence_files(evidence_items),
            "source_locations": evidence_locations(evidence_items),
        }
    )
