from __future__ import annotations

from enum import Enum
from typing import Dict, Literal, Optional, Union

from pydantic import BaseModel, Field


Confidence = Literal["strong", "partial", "inferred", "unknown"]
ConfidenceLabel = Literal["Low", "Medium", "High", "Very High"]
RiskSeverity = Literal["critical", "high", "medium", "low", "informational"]
FlowCategory = Literal[
    "Business Flow",
    "Request Flow",
    "Queue Flow",
    "Worker Flow",
    "Cron Flow",
    "Authentication Flow",
    "Integration Flow",
    "Runtime Flow",
    "Framework Flow",
    "System Flow",
    "Usage Flow",
    "Command Execution Flow",
]


class ScanStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class Repo(BaseModel):
    id: str
    url: str
    name: str
    owner: str = "local"
    default_branch: Optional[str] = None
    local_path: str
    retention: Dict[str, Union[str, bool, int, None]] = Field(
        default_factory=lambda: {
            "storesSource": True,
            "policy": "local-v1",
            "deleteSupported": False,
            "privateRepoDeletionPlanned": True,
        }
    )


class Scan(BaseModel):
    id: str
    repo_id: str
    status: ScanStatus = ScanStatus.queued
    progress: int = 0
    phase: str = "queued"
    error: Optional[str] = None


class Evidence(BaseModel):
    id: str
    file_path: str
    symbol: Optional[str] = None
    indicator: Optional[str] = None
    snippet: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    confidence: Confidence = "inferred"
    confidence_score: int = 40
    confidence_label: ConfidenceLabel = "Medium"
    related_flows: list[str] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    label: str
    kind: str
    file_path: Optional[str] = None
    evidence_id: Optional[str] = None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    kind: str
    confidence: Confidence = "partial"
    confidence_score: int = 65
    confidence_label: ConfidenceLabel = "Medium"
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    source_files: list[str] = Field(default_factory=list)
    source_locations: list[str] = Field(default_factory=list)


class FlowStep(BaseModel):
    id: str
    label: str
    technical_label: str
    kind: str
    evidence_id: str
    confidence: Confidence
    actor: str = "System"
    action: str = "Inspect"
    target: str = "source module"
    operation: str = "execution"
    side_effects: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    narrative: str = ""
    confidence_score: int = 65
    confidence_label: ConfidenceLabel = "Medium"
    evidence_count: int = 1
    source_files: list[str] = Field(default_factory=list)
    source_locations: list[str] = Field(default_factory=list)


class BehaviorFlow(BaseModel):
    id: str
    name: str
    repo_type: str
    summary: str
    answer: str = ""
    trigger: str = ""
    actors: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)
    decision_points: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    confidence: Confidence
    confidence_score: int = 65
    confidence_label: ConfidenceLabel = "Medium"
    category: FlowCategory = "Business Flow"
    evidence_count: int = 0
    source_files: list[str] = Field(default_factory=list)
    source_locations: list[str] = Field(default_factory=list)
    confidence_factors: dict[str, bool] = Field(default_factory=dict)
    steps: list[FlowStep]
    evidence_ids: list[str]
    ai_summary_available: bool = False


class RiskFinding(BaseModel):
    id: str
    title: str
    category: str
    severity: RiskSeverity
    description: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence_score: int = 55
    confidence_label: ConfidenceLabel = "Medium"
    evidence_count: int = 0
    source_files: list[str] = Field(default_factory=list)
    source_locations: list[str] = Field(default_factory=list)
    why_it_matters: str = ""
    rank: int


class Overview(BaseModel):
    repo: Repo
    classification: dict[str, object]
    languages: dict[str, int]
    frameworks: list[str]
    counts: dict[str, int]
    confidence: Confidence
    confidence_score: int = 55
    confidence_label: ConfidenceLabel = "Medium"
    evidence_count: int = 0
    analysis_strategy: str = "Usage Flows"


class Structure(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class PipelineStage(BaseModel):
    key: str
    label: str
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    progress: int = 0


class Coverage(BaseModel):
    routesAnalyzed: int = 0
    filesParsed: int = 0
    dependenciesResolved: int = 0
    flowsDetected: int = 0
    unknownRegions: int = 0


class Unknowns(BaseModel):
    filesNotParsed: list[str] = Field(default_factory=list)
    unsupportedSyntax: list[str] = Field(default_factory=list)
    dynamicImports: list[str] = Field(default_factory=list)
    reflectionUsage: list[str] = Field(default_factory=list)
    generatedCode: list[str] = Field(default_factory=list)
    missingDependencies: list[str] = Field(default_factory=list)


class Diagnostics(BaseModel):
    pipeline: list[PipelineStage]
    coverage: Coverage
    unknowns: Unknowns
    artifactFiles: list[str]
    ai: dict[str, object] = Field(default_factory=dict)


class Summary(BaseModel):
    title: str
    positioning: str
    deterministic: str
    ai_available: bool = False


class ScanRequest(BaseModel):
    repoUrl: str
    mode: Literal["scan", "demo"] = "scan"


class ScanResponse(BaseModel):
    scanId: str


class AnalysisResult(BaseModel):
    overview: Overview
    structure: Structure
    flows: list[BehaviorFlow]
    risks: list[RiskFinding]
    evidence: dict[str, Evidence]
    diagnostics: Optional[Diagnostics] = None
    summary: Optional[Summary] = None
