from __future__ import annotations

import posixpath
from pathlib import Path

from .analyzer import AnalyzerOutput
from .models import Coverage, Diagnostics, PipelineStage, Summary, Unknowns


PIPELINE_STAGES = [
    ("fetch", "fetch"),
    ("classify", "classify repository"),
    ("graph", "build structure graph"),
    ("paths", "detect execution paths"),
    ("flows", "generate behavior flows"),
    ("confidence", "calculate confidence"),
    ("risks", "rank risks"),
    ("persist", "persist artifacts"),
]

ARTIFACT_FILES = [
    "repository.json",
    "graph.json",
    "flows.json",
    "risks.json",
    "evidence.json",
    "diagnostics.json",
    "summary.json",
]


def stage_status(active_key: str | None = None, completed: set[str] | None = None, failed: bool = False) -> list[PipelineStage]:
    completed = completed or set()
    stages = []
    for index, (key, label) in enumerate(PIPELINE_STAGES):
        status = "queued"
        progress = 0
        if key in completed:
            status = "completed"
            progress = 100
        if key == active_key:
            status = "failed" if failed else "running"
            progress = 50 if not failed else 100
        stages.append(PipelineStage(key=key, label=label, status=status, progress=progress))
    return stages


def build_diagnostics(analysis: AnalyzerOutput, flows_count: int, ai_available: bool) -> Diagnostics:
    files_total = len(analysis.files)
    routes_total = sum(len(file.routes) for file in analysis.files)
    resolved_imports = len([edge for edge in analysis.structure.edges if edge.kind == "imports"])
    import_refs = sum(len([imported for imported in file.imports if imported.startswith(".")]) for file in analysis.files)
    unknowns = _unknowns(analysis)
    unknown_count = sum(len(value) for value in unknowns.model_dump().values())
    coverage = Coverage(
        routesAnalyzed=_percent(routes_total, routes_total),
        filesParsed=_percent(files_total, files_total),
        dependenciesResolved=_percent(resolved_imports, import_refs),
        flowsDetected=flows_count,
        unknownRegions=unknown_count,
    )
    return Diagnostics(
        pipeline=stage_status(completed={key for key, _ in PIPELINE_STAGES}),
        coverage=coverage,
        unknowns=unknowns,
        artifactFiles=ARTIFACT_FILES,
        ai={"available": ai_available, "role": "Optional summaries, naming improvements, and explanations only."},
    )


def build_summary(analysis: AnalyzerOutput, flows_count: int, risks_count: int, ai_available: bool) -> Summary:
    repo_type = str(analysis.overview.classification.get("dominantType", "Unknown"))
    return Summary(
        title=f"{analysis.repo.owner}/{analysis.repo.name} Flow Map",
        positioning="GitDiagram shows structure. Business GitFlow shows structure + flows + evidence.",
        deterministic=f"{repo_type} analysis produced {flows_count} evidence-backed flows and {risks_count} ranked risks from {analysis.overview.evidence_count} evidence sources.",
        ai_available=ai_available,
    )


def _unknowns(analysis: AnalyzerOutput) -> Unknowns:
    files_not_parsed = []
    unsupported_syntax = []
    dynamic_imports = []
    reflection_usage = []
    generated_code = []
    missing_dependencies = []
    for file in analysis.files:
        path = file.relative_path
        lowered = path.lower()
        text = _snippet_text(analysis, path).lower()
        if file.language not in {"JavaScript", "TypeScript", "Python", "Go", "Java", "Rust", "C", "C++", "C/C++ Header", "Markdown", "JSON", "YAML", "Terraform", "Dockerfile"}:
            unsupported_syntax.append(path)
        if "import(" in text:
            dynamic_imports.append(path)
        if "reflect" in text or "getattr(" in text or "eval(" in text:
            reflection_usage.append(path)
        if "generated" in lowered or ".generated." in lowered or "gen/" in lowered:
            generated_code.append(path)
        for imported in file.imports:
            if imported.startswith(".") and not _local_import_resolved(analysis, file.relative_path, imported):
                missing_dependencies.append(f"{path} -> {imported}")
    return Unknowns(
        filesNotParsed=files_not_parsed[:20],
        unsupportedSyntax=unsupported_syntax[:20],
        dynamicImports=list(dict.fromkeys(dynamic_imports))[:20],
        reflectionUsage=list(dict.fromkeys(reflection_usage))[:20],
        generatedCode=generated_code[:20],
        missingDependencies=list(dict.fromkeys(missing_dependencies))[:20],
    )


def _snippet_text(analysis: AnalyzerOutput, file_path: str) -> str:
    item = next((evidence for evidence in analysis.evidence.values() if evidence.file_path == file_path), None)
    return item.snippet if item else ""


def _local_import_resolved(analysis: AnalyzerOutput, file_path: str, imported: str) -> bool:
    source_id = f"file:{file_path}"
    source_dir = Path(file_path).parent
    import_path = posixpath.normpath((source_dir / imported).as_posix())
    candidate_paths = {
        import_path,
        f"{import_path}.ts",
        f"{import_path}.tsx",
        f"{import_path}.js",
        f"{import_path}.jsx",
        f"{import_path}/index.ts",
        f"{import_path}/index.tsx",
        f"{import_path}/index.js",
        f"{import_path}/index.jsx",
    }
    for edge in analysis.structure.edges:
        if edge.kind != "imports" or edge.source != source_id:
            continue
        target_path = edge.target.removeprefix("file:")
        if target_path in candidate_paths:
            return True
    return False


def _percent(done: int, total: int) -> int:
    if total <= 0:
        return 100
    return round((done / total) * 100)
