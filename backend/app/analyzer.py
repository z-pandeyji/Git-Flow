from __future__ import annotations

import json
import posixpath
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .confidence import confidence_label, score_from_legacy
from .models import Evidence, GraphEdge, GraphNode, Overview, Repo, Structure


TEXT_EXTENSIONS = {
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".py": "Python",
    ".java": "Java",
    ".go": "Go",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".rs": "Rust",
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".h": "C/C++ Header",
    ".hpp": "C/C++ Header",
    ".md": "Markdown",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".tf": "Terraform",
}

IGNORED_DIRS = {".git", "node_modules", "dist", "build", ".next", ".venv", "venv", "__pycache__"}
JS_TS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}
C_CPP_EXTENSIONS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"}
IMPORT_RE = re.compile(r"(?:import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\))")
ROUTE_RE = re.compile(r"\b(?:app|router)\.(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]")
CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
FUNC_RE = re.compile(r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)|(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\(")
CLASS_RE = re.compile(r"(?:export\s+)?class\s+([A-Za-z0-9_]+)")
CPP_FUNC_RE = re.compile(r"^\s*(?:[A-Za-z_:<>~*&]+\s+)+([A-Za-z_][A-Za-z0-9_:~]*)\s*\([^;{}]*\)\s*(?:const\s*)?(?:\{|$)", re.MULTILINE)
CPP_CLASS_RE = re.compile(r"^\s*(?:class|struct)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
WEAK_SYMBOLS = {
    "a",
    "an",
    "and",
    "as",
    "be",
    "const",
    "for",
    "from",
    "if",
    "in",
    "is",
    "it",
    "let",
    "of",
    "or",
    "that",
    "the",
    "this",
    "to",
    "var",
    "when",
    "would",
    "with",
}


@dataclass
class FileInfo:
    relative_path: str
    language: str
    line_count: int
    imports: list[str] = field(default_factory=list)
    routes: list[dict[str, object]] = field(default_factory=list)
    symbols: list[dict[str, object]] = field(default_factory=list)
    indicators: list[str] = field(default_factory=list)


@dataclass
class AnalyzerOutput:
    repo: Repo
    files: list[FileInfo]
    evidence: dict[str, Evidence]
    structure: Structure
    overview: Overview


def analyze_repo(repo: Repo) -> AnalyzerOutput:
    root = Path(repo.local_path)
    files = [_analyze_file(root, path) for path in _iter_source_files(root)]
    files = [file for file in files if file is not None]
    evidence: dict[str, Evidence] = {}
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    file_node_ids: dict[str, str] = {}

    for file in files:
        node_id = f"file:{file.relative_path}"
        file_node_ids[file.relative_path] = node_id
        evidence_id = _evidence_id(repo.id, file.relative_path, "file")
        evidence[evidence_id] = _file_evidence(repo.id, root, file, evidence_id)
        nodes.append(GraphNode(id=node_id, label=Path(file.relative_path).name, kind=_node_kind(file), file_path=file.relative_path, evidence_id=evidence_id))
        for route in file.routes:
            route_id = f"route:{file.relative_path}:{route['method']}:{route['path']}"
            route_evidence_id = _evidence_id(repo.id, file.relative_path, f"{route['method']}-{route['path']}")
            evidence[route_evidence_id] = _snippet_evidence(repo.id, root, file.relative_path, route_evidence_id, str(route["label"]), int(route["line"]), "route", "strong")
            nodes.append(GraphNode(id=route_id, label=str(route["label"]), kind="route", file_path=file.relative_path, evidence_id=route_evidence_id))
            edges.append(_edge(f"edge:{route_id}->{node_id}", route_id, node_id, "defined-in", "strong", [route_evidence_id], evidence))
        for symbol in file.symbols[:12]:
            symbol_id = f"symbol:{file.relative_path}:{symbol['name']}"
            symbol_evidence_id = _evidence_id(repo.id, file.relative_path, str(symbol["name"]))
            evidence[symbol_evidence_id] = _snippet_evidence(repo.id, root, file.relative_path, symbol_evidence_id, str(symbol["name"]), int(symbol["line"]), str(symbol["kind"]), "partial")
            nodes.append(GraphNode(id=symbol_id, label=str(symbol["name"]), kind=str(symbol["kind"]), file_path=file.relative_path, evidence_id=symbol_evidence_id))
            edges.append(_edge(f"edge:{node_id}->{symbol_id}", node_id, symbol_id, "contains", "partial", [symbol_evidence_id], evidence))

    source_paths = {file.relative_path for file in files}
    for file in files:
        source = file_node_ids[file.relative_path]
        for imported in file.imports:
            target_path = resolve_local_import(file.relative_path, imported, source_paths)
            if target_path and target_path in file_node_ids:
                target = file_node_ids[target_path]
                source_evidence_id = next((node.evidence_id for node in nodes if node.id == source), None)
                target_evidence_id = next((node.evidence_id for node in nodes if node.id == target), None)
                edge_evidence = [item for item in [source_evidence_id, target_evidence_id] if item]
                edges.append(_edge(f"edge:{source}->{target}", source, target, "imports", "strong", edge_evidence, evidence))

    languages = Counter(file.language for file in files)
    frameworks = detect_frameworks(root, files)
    classification = classify_repo(root, files, frameworks)
    overview = Overview(
        repo=repo,
        classification=classification,
        languages=dict(languages),
        frameworks=frameworks,
        counts={
            "files": len(files),
            "routes": sum(len(file.routes) for file in files),
            "symbols": sum(len(file.symbols) for file in files),
            "graphNodes": len(nodes),
            "graphEdges": len(edges),
        },
        confidence="partial" if files else "unknown",
        confidence_score=65 if files else 20,
        confidence_label=confidence_label(65 if files else 20),
        evidence_count=len(evidence),
        analysis_strategy=_analysis_strategy(str(classification.get("dominantType", "Unknown"))),
    )
    return AnalyzerOutput(repo=repo, files=files, evidence=evidence, structure=Structure(nodes=nodes, edges=edges), overview=overview)


def _iter_source_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        if (path.suffix.lower() in TEXT_EXTENSIONS or path.name.lower() in {"dockerfile"}) and path.stat().st_size < 350_000:
            paths.append(path)
    return sorted(paths, key=lambda path: _file_priority(path.relative_to(root)))[:500]


def _file_priority(path: Path) -> tuple[int, str]:
    parts = path.parts
    joined = path.as_posix().lower()
    suffix = path.suffix.lower()
    if len(parts) > 1 and parts[0] in {"src", "lib"}:
        base = 0
    elif joined.startswith("lib/internal/") or joined.startswith("src/"):
        base = 0
    elif suffix in JS_TS_EXTENSIONS or suffix in C_CPP_EXTENSIONS or suffix in {".py", ".go", ".java", ".rs"}:
        base = 1
    elif suffix in {".json", ".yaml", ".yml"}:
        base = 3
    elif suffix == ".md":
        base = 4
    else:
        base = 2
    return (base, joined)


def _analyze_file(root: Path, path: Path) -> FileInfo | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    relative = path.relative_to(root).as_posix()
    language = "Dockerfile" if path.name.lower() == "dockerfile" else TEXT_EXTENSIONS.get(path.suffix.lower(), "Unknown")
    lines = text.splitlines()
    is_js_ts = path.suffix.lower() in JS_TS_EXTENSIONS
    imports = [match.group(1) or match.group(2) for match in IMPORT_RE.finditer(text)] if is_js_ts else []
    routes = []
    if is_js_ts:
        for match in ROUTE_RE.finditer(text):
            method, route_path = match.groups()
            line = text[: match.start()].count("\n") + 1
            block = "\n".join(lines[line - 1 : min(len(lines), line + 12)])
            calls = [call.group(1) for call in CALL_RE.finditer(block) if _valid_symbol(call.group(1))]
            routes.append({"method": method.upper(), "path": route_path, "line": line, "label": f"{method.upper()} {route_path}", "calls": calls})
    symbols = []
    if is_js_ts:
        for match in FUNC_RE.finditer(text):
            name = match.group(1) or match.group(2)
            if _valid_symbol(name):
                symbols.append({"name": name, "kind": "function", "line": text[: match.start()].count("\n") + 1})
        for match in CLASS_RE.finditer(text):
            name = match.group(1)
            if _valid_symbol(name):
                symbols.append({"name": name, "kind": "class", "line": text[: match.start()].count("\n") + 1})
    if path.suffix.lower() in C_CPP_EXTENSIONS:
        for match in CPP_FUNC_RE.finditer(text):
            name = match.group(1).split("::")[-1]
            if _valid_symbol(name):
                symbols.append({"name": name, "kind": "function", "line": text[: match.start()].count("\n") + 1})
        for match in CPP_CLASS_RE.finditer(text):
            name = match.group(1)
            if _valid_symbol(name):
                symbols.append({"name": name, "kind": "class", "line": text[: match.start()].count("\n") + 1})
    indicators = _indicators(relative, text)
    return FileInfo(relative_path=relative, language=language, line_count=len(lines), imports=imports, routes=routes, symbols=symbols, indicators=indicators)


def _valid_symbol(name: str | None) -> bool:
    if not name:
        return False
    lowered = name.lower()
    return len(name) > 2 and lowered not in WEAK_SYMBOLS


def detect_frameworks(root: Path, files: list[FileInfo]) -> list[str]:
    frameworks: set[str] = set()
    package_json = root / "package.json"
    if package_json.exists():
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
            deps = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
            for package_name, framework_name in {
                "express": "Express",
                "@nestjs/core": "NestJS",
                "next": "Next.js",
                "react": "React",
                "fastify": "Fastify",
            }.items():
                if package_name in deps:
                    frameworks.add(framework_name)
        except json.JSONDecodeError:
            pass
    names = " ".join(file.relative_path.lower() for file in files)
    if "dockerfile" in names or "docker-compose" in names:
        frameworks.add("Docker")
    if any(file.relative_path.endswith(".py") for file in files):
        frameworks.add("Python")
    return sorted(frameworks)


def classify_repo(root: Path, files: list[FileInfo], frameworks: list[str]) -> dict[str, object]:
    names = [file.relative_path.lower() for file in files]
    indicators = Counter(indicator for file in files for indicator in file.indicators)
    tags: list[str] = []
    dominant = "Unknown"
    confidence = "inferred"
    runtime_signals = _runtime_signals(root, names)
    if runtime_signals:
        dominant = "Runtime"
        confidence = "partial"
        tags.extend(runtime_signals)
    if len([name for name in names if "/packages/" in name or name.startswith("packages/")]) >= 3:
        tags.append("Monorepo")
    if dominant == "Unknown" and any("bin/" in name or "cli" in name for name in names):
        dominant = "CLI"
        confidence = "partial"
    if dominant == "Unknown" and (any(name.endswith(("terraform.tf", ".tf")) for name in names) or ("Docker" in frameworks and not any(name.startswith(("src/", "lib/", "crates/", "packages/", "app/")) for name in names))):
        dominant = "Infrastructure"
        confidence = "partial"
    if dominant == "Unknown" and ("Express" in frameworks or "NestJS" in frameworks or any(file.routes for file in files)):
        dominant = "Business Application"
        confidence = "partial"
    if "Next.js" in frameworks and dominant == "Unknown":
        dominant = "Business Application"
    if dominant == "Unknown" and any(name in {"src/index.ts", "src/index.js", "lib/index.js"} for name in names) and not any(file.routes for file in files):
        dominant = "Library"
    if dominant == "Unknown" and any(token in root.name.lower() for token in ["runtime", "engine", "compiler"]):
        dominant = "Runtime"
    if dominant == "Unknown" and (indicators["controller"] or indicators["service"] or indicators["repository"]):
        dominant = "Business Application"
        confidence = "partial"
    if dominant == "Unknown" and files:
        dominant = "Library" if len(files) < 80 else "Framework"
        confidence = "inferred"
    score = score_from_legacy(confidence)
    return {
        "dominantType": dominant,
        "secondaryTags": tags,
        "confidence": confidence,
        "confidenceScore": score,
        "confidenceLabel": confidence_label(score),
        "analysisStrategy": _analysis_strategy(dominant),
    }


def _analysis_strategy(repo_type: str) -> str:
    return {
        "Business Application": "Business Flows",
        "Framework": "Framework Flows",
        "Runtime": "Runtime Flows",
        "Infrastructure": "System Flows",
        "Library": "Usage Flows",
        "CLI": "Command Execution Flows",
    }.get(repo_type, "Usage Flows")


def _runtime_signals(root: Path, names: list[str]) -> list[str]:
    tags: list[str] = []
    root_name = root.name.lower()
    if root_name == "node" or root_name.startswith("nodejs-node"):
        tags.append("Node.js")
    if "src/node.h" in names or "src/node.cc" in names or "src/api/environment.cc" in names:
        tags.append("Native Runtime Core")
    if any(name.startswith("lib/internal/") for name in names):
        tags.append("Internal Runtime Library")
    if any(name.startswith("deps/v8/") for name in names):
        tags.append("JavaScript Engine")
    if "node.gyp" in names:
        tags.append("Native Build")
    return list(dict.fromkeys(tags))


def _node_kind(file: FileInfo) -> str:
    if file.routes:
        return "controller"
    for marker in ["worker", "queue", "repository", "service", "controller"]:
        if marker in file.indicators:
            return marker
    return "file"


def _indicators(relative: str, text: str) -> list[str]:
    path_lowered = relative.lower()
    text_lowered = text.lower()
    lowered = f"{path_lowered}\n{text_lowered}"
    found = []
    for marker in ["controller", "service", "repository", "worker"]:
        if marker in path_lowered:
            found.append(marker)
    for marker in ["queue", "database", "schema", "route", "middleware", "bootstrap", "module", "event", "async"]:
        if marker in lowered:
            found.append(marker)
    if "fetch(" in text_lowered or "axios." in text_lowered:
        found.append("external-api")
    return found


def resolve_local_import(source_path: str, imported: str, source_paths: set[str]) -> str | None:
    if not imported.startswith("."):
        return None
    source_dir = Path(source_path).parent
    import_path = posixpath.normpath((source_dir / imported).as_posix())
    candidates = [
        import_path,
        f"{import_path}.ts",
        f"{import_path}.tsx",
        f"{import_path}.js",
        f"{import_path}.jsx",
        f"{import_path}/index.ts",
        f"{import_path}/index.tsx",
        f"{import_path}/index.js",
        f"{import_path}/index.jsx",
    ]
    for candidate in candidates:
        normalized = Path(candidate).as_posix()
        if normalized in source_paths:
            return normalized
    return None


def _evidence_id(repo_id: str, relative_path: str, subject: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "-", f"{repo_id}-{relative_path}-{subject}").strip("-").lower()
    return f"ev-{safe[:120]}"


def _file_evidence(repo_id: str, root: Path, file: FileInfo, evidence_id: str) -> Evidence:
    return _snippet_evidence(repo_id, root, file.relative_path, evidence_id, Path(file.relative_path).name, 1, ",".join(file.indicators) or file.language, "partial")


def _snippet_evidence(repo_id: str, root: Path, relative_path: str, evidence_id: str, symbol: str, line: int, indicator: str, confidence: str) -> Evidence:
    path = root / relative_path
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    start = max(1, line - 2)
    end = min(len(lines), line + 4)
    snippet = "\n".join(lines[start - 1 : end]) if lines else ""
    return Evidence(
        id=evidence_id,
        file_path=relative_path,
        symbol=symbol,
        indicator=indicator,
        snippet=snippet,
        start_line=start,
        end_line=end,
        confidence=confidence,  # type: ignore[arg-type]
        confidence_score=score_from_legacy(confidence),
        confidence_label=confidence_label(score_from_legacy(confidence)),
    )


def _edge(edge_id: str, source: str, target: str, kind: str, confidence: str, evidence_ids: list[str], evidence: dict[str, Evidence]) -> GraphEdge:
    evidence_items = [evidence[evidence_id] for evidence_id in evidence_ids if evidence_id in evidence]
    score = score_from_legacy(confidence)
    return GraphEdge(
        id=edge_id,
        source=source,
        target=target,
        kind=kind,
        confidence=confidence,  # type: ignore[arg-type]
        confidence_score=score,
        confidence_label=confidence_label(score),
        evidence_ids=[item.id for item in evidence_items],
        evidence_count=len(evidence_items),
        source_files=list(dict.fromkeys(item.file_path for item in evidence_items)),
        source_locations=list(dict.fromkeys(f"{item.file_path}:{item.start_line or 1}" for item in evidence_items)),
    )
