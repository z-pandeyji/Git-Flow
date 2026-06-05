from __future__ import annotations

from .models import ConfidenceLabel, Evidence


LEGACY_SCORE = {
    "unknown": 20,
    "inferred": 45,
    "partial": 65,
    "strong": 85,
}


def confidence_label(score: int) -> ConfidenceLabel:
    if score >= 90:
        return "Very High"
    if score >= 70:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def legacy_confidence(score: int) -> str:
    if score >= 80:
        return "strong"
    if score >= 55:
        return "partial"
    if score >= 25:
        return "inferred"
    return "unknown"


def score_from_legacy(confidence: str) -> int:
    return LEGACY_SCORE.get(confidence, 40)


def evidence_location(evidence: Evidence) -> str:
    line = evidence.start_line or 1
    if evidence.end_line and evidence.end_line != line:
        return f"{evidence.file_path}:{line}-{evidence.end_line}"
    return f"{evidence.file_path}:{line}"


def evidence_files(evidence_items: list[Evidence]) -> list[str]:
    return list(dict.fromkeys(item.file_path for item in evidence_items))


def evidence_locations(evidence_items: list[Evidence]) -> list[str]:
    return list(dict.fromkeys(evidence_location(item) for item in evidence_items))
