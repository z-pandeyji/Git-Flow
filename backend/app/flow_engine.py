from __future__ import annotations

import os
from pathlib import Path

from .analyzer import AnalyzerOutput, FileInfo, resolve_local_import
from .confidence import confidence_label, evidence_files, evidence_locations, legacy_confidence
from .llm_service import summarize_flow
from .models import BehaviorFlow, Evidence, FlowCategory, FlowStep


def build_flows(analysis: AnalyzerOutput) -> list[BehaviorFlow]:
    repo_type = str(analysis.overview.classification.get("dominantType", "Unknown"))
    if repo_type == "Business Application":
        flows = _business_flows(analysis)
    elif repo_type in {"Framework", "Runtime"}:
        flows = _framework_flows(analysis, repo_type)
    elif repo_type == "Infrastructure":
        flows = _infrastructure_flows(analysis)
    else:
        flows = _fallback_flows(analysis, repo_type)
    flows = [_hydrate_flow_metadata(flow, analysis) for flow in flows if flow.evidence_ids and flow.steps]
    for flow in flows:
        for evidence_id in flow.evidence_ids:
            evidence = analysis.evidence.get(evidence_id)
            if evidence and flow.id not in evidence.related_flows:
                evidence.related_flows.append(flow.id)
    return flows


def _business_flows(analysis: AnalyzerOutput) -> list[BehaviorFlow]:
    flows: list[BehaviorFlow] = []
    max_flows = int(os.getenv("BFO_MAX_FLOWS", "40"))
    route_files = [file for file in analysis.files if file.routes]
    for file in route_files:
        for route in file.routes:
            if len(flows) >= max_flows:
                return flows
            related_files = _related_files(file, analysis.files, route)
            steps = []
            evidence_ids = []
            route_evidence = _find_evidence(analysis.evidence, file.relative_path, str(route["label"]))
            if route_evidence:
                evidence_ids.append(route_evidence.id)
                steps.append(_step("request", str(route["label"]), "API request", route_evidence))
            for related in related_files[:4]:
                evidence = _find_evidence(analysis.evidence, related.relative_path, Path(related.relative_path).name)
                if evidence:
                    evidence_ids.append(evidence.id)
                    steps.append(_step(related.indicators[0] if related.indicators else "module", _business_label(related), related.relative_path, evidence))
            if not steps:
                continue
            technical = [step.technical_label for step in steps]
            summary, ai_available = summarize_flow(str(route["label"]), technical)
            flow_id = f"flow-{len(flows)+1}"
            flows.append(
                BehaviorFlow(
                    id=flow_id,
                    name=_flow_name(str(route["path"])),
                    repo_type="Business Application",
                    summary=summary,
                    confidence="strong" if len(steps) > 1 else "partial",
                    category=_route_category(str(route["path"])),
                    steps=steps,
                    evidence_ids=list(dict.fromkeys(evidence_ids)),
                    ai_summary_available=ai_available,
                )
            )
    if flows:
        return flows
    return _fallback_flows(analysis, "Business Application")


def _framework_flows(analysis: AnalyzerOutput, repo_type: str) -> list[BehaviorFlow]:
    if repo_type == "Runtime":
        return _runtime_flows(analysis)
    files = _rank_source_files(analysis.files, ["src/", "lib/", "packages/"])[:5]
    return [_candidate_flow(analysis, repo_type, "Framework Lifecycle Flow", files, "Framework lifecycle inferred from source modules, exports, and internal wiring.", "partial", "Framework Flow")]


def _runtime_flows(analysis: AnalyzerOutput) -> list[BehaviorFlow]:
    flow_specs = [
        (
            "Runtime Bootstrap Flow",
            ["src/node", "src/api/environment", "lib/internal/bootstrap", "lib/internal/process"],
            "Initializes the runtime process, native environment, and internal JavaScript bootstrap modules.",
        ),
        (
            "Module Loading Flow",
            ["lib/internal/modules", "lib/module", "src/module", "src/node_contextify"],
            "Resolves, compiles, and loads JavaScript modules through internal loader paths.",
        ),
        (
            "Event Loop And Async Work Flow",
            ["src/node_task_queue", "src/env", "src/api/callback", "lib/internal/timers", "lib/internal/process/task_queues"],
            "Coordinates queued callbacks, timers, and native async work across the runtime boundary.",
        ),
    ]
    flows: list[BehaviorFlow] = []
    for index, (name, patterns, summary) in enumerate(flow_specs, start=1):
        files = _matching_source_files(analysis.files, patterns)[:5]
        if files:
            flow = _candidate_flow(analysis, "Runtime", name, files, summary, "partial", "Runtime Flow")
            flows.append(flow.model_copy(update={"id": f"flow-{index}"}))
    if flows:
        return flows
    files = _rank_source_files(analysis.files, ["src/", "lib/internal/", "lib/"])[:5]
    return [_candidate_flow(analysis, "Runtime", "Runtime Behavior Candidate", files, "Runtime behavior inferred from core source files.", "inferred", "Runtime Flow")]


def _infrastructure_flows(analysis: AnalyzerOutput) -> list[BehaviorFlow]:
    files = _rank_source_files([file for file in analysis.files if any(indicator in file.indicators for indicator in ["queue", "database", "worker"])], ["src/", "lib/", "infra/", "deploy/"])[:5]
    if not files:
        files = _rank_source_files(analysis.files, ["src/", "lib/", "infra/", "deploy/"])[:5]
    return [_candidate_flow(analysis, "Infrastructure", "System Data Flow", files, "Inferred system flow from infrastructure and data files.", "inferred", "System Flow")]


def _fallback_flows(analysis: AnalyzerOutput, repo_type: str) -> list[BehaviorFlow]:
    files = _rank_source_files([file for file in analysis.files if file.symbols or file.imports or file.indicators], ["src/", "lib/", "app/", "packages/"])[:5]
    if not files:
        files = _rank_source_files(analysis.files, ["src/", "lib/", "app/", "packages/"])[:5]
    category: FlowCategory = "Command Execution Flow" if repo_type == "CLI" else "Usage Flow"
    return [_candidate_flow(analysis, repo_type, f"{category} Candidate", files, "Low-confidence behavior candidate from source structure and symbols.", "inferred", category)]


def _candidate_flow(analysis: AnalyzerOutput, repo_type: str, name: str, files: list[FileInfo], summary: str, confidence: str = "inferred", category: FlowCategory = "Usage Flow") -> BehaviorFlow:
    steps: list[FlowStep] = []
    evidence_ids: list[str] = []
    for file in files:
        evidence = _find_evidence(analysis.evidence, file.relative_path, Path(file.relative_path).name)
        if evidence:
            evidence_ids.append(evidence.id)
            steps.append(_step(file.indicators[0] if file.indicators else "module", _source_label(file), file.relative_path, evidence, confidence))
    ai_summary, ai_available = summarize_flow(name, [step.technical_label for step in steps])
    return BehaviorFlow(id="flow-1", name=name, repo_type=repo_type, summary=ai_summary if ai_available else summary, confidence=confidence, category=category, steps=steps, evidence_ids=list(dict.fromkeys(evidence_ids)), ai_summary_available=ai_available)


def _rank_source_files(files: list[FileInfo], preferred_patterns: list[str]) -> list[FileInfo]:
    def score(file: FileInfo) -> tuple[int, str]:
        path = file.relative_path.lower()
        if path.endswith((".md", ".json", ".yaml", ".yml")):
            base = 50
        elif file.language in {"C", "C++", "C/C++ Header", "JavaScript", "TypeScript", "Python", "Go", "Java", "Rust"}:
            base = 10
        else:
            base = 30
        for index, pattern in enumerate(preferred_patterns):
            if path.startswith(pattern) or pattern in path:
                base = min(base, index)
        if file.symbols:
            base -= 2
        if file.imports:
            base -= 1
        return (base, path)

    return sorted(files, key=score)


def _matching_source_files(files: list[FileInfo], patterns: list[str]) -> list[FileInfo]:
    matched = []
    for file in files:
        path = file.relative_path.lower()
        if path.endswith((".md", ".json", ".yaml", ".yml")):
            continue
        if any(pattern in path for pattern in patterns):
            matched.append(file)
    return _rank_source_files(matched, patterns)


def _source_label(file: FileInfo) -> str:
    stem = Path(file.relative_path).stem.replace("_", " ").replace("-", " ")
    return " ".join(word.capitalize() for word in stem.split()) or Path(file.relative_path).name


def _related_files(file: FileInfo, files: list[FileInfo], route: dict[str, object]) -> list[FileInfo]:
    called = {str(call) for call in route.get("calls", []) if call}
    symbol_to_file = {
        str(symbol["name"]): candidate
        for candidate in files
        for symbol in candidate.symbols
        if candidate.relative_path != file.relative_path
    }
    first_hop = _dedupe_files([symbol_to_file[name] for name in called if name in symbol_to_file])
    if not first_hop:
        return []

    file_by_path = {candidate.relative_path: candidate for candidate in files}
    source_paths = set(file_by_path)
    related = list(first_hop)
    for candidate in first_hop:
        for imported in candidate.imports:
            imported_path = resolve_local_import(candidate.relative_path, imported, source_paths)
            imported_file = file_by_path.get(imported_path) if imported_path else None
            if imported_file and imported_file not in related:
                related.append(imported_file)
    return related


def _dedupe_files(files: list[FileInfo]) -> list[FileInfo]:
    seen = set()
    deduped = []
    for file in files:
        if file.relative_path in seen:
            continue
        seen.add(file.relative_path)
        deduped.append(file)
    return deduped


def _find_evidence(evidence: dict[str, Evidence], file_path: str, symbol_or_label: str) -> Evidence | None:
    for item in evidence.values():
        if item.file_path == file_path and item.symbol == symbol_or_label:
            return item
    for item in evidence.values():
        if item.file_path == file_path:
            return item
    return None


def _step(kind: str, label: str, technical: str, evidence: Evidence, confidence: str = "partial") -> FlowStep:
    score = 85 if confidence == "strong" else 65 if confidence == "partial" else 45
    actor, action, target, operation = _step_semantics(kind, label, technical, evidence)
    side_effects = _side_effects(kind, label, technical, evidence)
    conditions = _conditions(evidence)
    inputs = _inputs(kind, evidence)
    outputs = _outputs(kind, label, evidence)
    return FlowStep(
        id=f"step-{evidence.id}",
        label=label,
        technical_label=technical,
        kind=kind,
        evidence_id=evidence.id,
        confidence=confidence,  # type: ignore[arg-type]
        actor=actor,
        action=action,
        target=target,
        operation=operation,
        side_effects=side_effects,
        conditions=conditions,
        inputs=inputs,
        outputs=outputs,
        narrative=_step_narrative(actor, action, target, side_effects, outputs),
        confidence_score=score,
        confidence_label=confidence_label(score),
        evidence_count=1,
        source_files=[evidence.file_path],
        source_locations=[f"{evidence.file_path}:{evidence.start_line or 1}"],
    )


def _step_semantics(kind: str, label: str, technical: str, evidence: Evidence) -> tuple[str, str, str, str]:
    lowered = f"{kind} {label} {technical} {evidence.snippet}".lower()
    if kind == "request":
        return ("Client", "sends", label, "HTTP request")
    if "repository" in lowered or "persist" in lowered or "save" in lowered:
        return ("Repository", "persists", _clean_target(label), "database write")
    if "external-api" in lowered or "notify" in lowered or "fetch(" in lowered or "axios." in lowered:
        return ("Integration", "calls", _clean_target(label), "external API call")
    if "queue" in lowered or "worker" in lowered:
        return ("Worker", "processes", _clean_target(label), "async work")
    if "validation" in lowered or "schema" in lowered:
        return ("Validator", "checks", _clean_target(label), "validation")
    if "service" in lowered:
        return ("Service", "executes", _clean_target(label), "business logic")
    if "bootstrap" in lowered:
        return ("Runtime", "initializes", _clean_target(label), "runtime bootstrap")
    if "module" in lowered:
        return ("Runtime", "loads", _clean_target(label), "module loading")
    return ("System", "runs", _clean_target(label), "source execution")


def _side_effects(kind: str, label: str, technical: str, evidence: Evidence) -> list[str]:
    lowered = f"{kind} {label} {technical} {evidence.snippet}".lower()
    effects = []
    if "repository" in lowered or "save" in lowered or "database" in lowered:
        effects.append("Database state may change")
    if "fetch(" in lowered or "axios." in lowered or "notify" in lowered:
        effects.append("External service may be called")
    if "queue" in lowered or "worker" in lowered:
        effects.append("Async work may be queued or processed")
    if "res.json" in lowered or "return " in lowered:
        effects.append("Response or return value is produced")
    return effects


def _conditions(evidence: Evidence) -> list[str]:
    snippet = evidence.snippet.lower()
    conditions = []
    if "if " in snippet or "if(" in snippet:
        conditions.append("Conditional branch detected in source")
    if "catch" in snippet or "except" in snippet:
        conditions.append("Error handling branch detected in source")
    return conditions


def _inputs(kind: str, evidence: Evidence) -> list[str]:
    snippet = evidence.snippet.lower()
    inputs = []
    if kind == "request":
        inputs.append("HTTP request")
    if "req.body" in snippet:
        inputs.append("Request body")
    if "providerid" in snippet:
        inputs.append("Provider id")
    if "location" in snippet:
        inputs.append("Location")
    return inputs


def _outputs(kind: str, label: str, evidence: Evidence) -> list[str]:
    snippet = evidence.snippet.lower()
    outputs = []
    if "res.json" in snippet:
        outputs.append("JSON response")
    if "return " in snippet:
        outputs.append(f"{_clean_target(label)} result")
    if kind == "request" and not outputs:
        outputs.append("Request enters application flow")
    return outputs


def _step_narrative(actor: str, action: str, target: str, side_effects: list[str], outputs: list[str]) -> str:
    sentence = f"{actor} {action} {target}."
    if side_effects:
        sentence += f" Side effect: {side_effects[0]}."
    if outputs:
        sentence += f" Output: {outputs[0]}."
    return sentence


def _clean_target(label: str) -> str:
    return label.replace("POST ", "").replace("GET ", "").replace("PUT ", "").replace("PATCH ", "").replace("DELETE ", "").strip() or "target"


def _business_label(file: FileInfo) -> str:
    name = Path(file.relative_path).stem.replace(".", " ").replace("-", " ").replace("_", " ")
    words = [word.capitalize() for word in name.split() if word not in {"service", "repository", "controller"}]
    suffix = " ".join(words) or Path(file.relative_path).name
    if "repository" in file.indicators:
        return f"Persist {suffix}"
    if "external-api" in file.indicators or "notification" in file.relative_path.lower():
        return f"Notify via {suffix}"
    return suffix


def _flow_name(route_path: str) -> str:
    cleaned = route_path.strip("/").replace("-", " ").replace("_", " ")
    if not cleaned:
        return "Root Request Flow"
    return " ".join(word.capitalize() for word in cleaned.split("/")[0].split()) + " Flow"


def _route_category(route_path: str) -> FlowCategory:
    lowered = route_path.lower()
    if "auth" in lowered or "login" in lowered or "signup" in lowered or "user" in lowered:
        return "Authentication Flow"
    if "webhook" in lowered or "integration" in lowered:
        return "Integration Flow"
    return "Business Flow"


def _hydrate_flow_metadata(flow: BehaviorFlow, analysis: AnalyzerOutput) -> BehaviorFlow:
    evidence_items = [analysis.evidence[evidence_id] for evidence_id in flow.evidence_ids if evidence_id in analysis.evidence]
    factors = _confidence_factors(flow, evidence_items)
    score = _confidence_score(factors, len(flow.steps), len(evidence_items))
    actors = list(dict.fromkeys(step.actor for step in flow.steps))
    side_effects = list(dict.fromkeys(effect for step in flow.steps for effect in step.side_effects))
    decision_points = list(dict.fromkeys(condition for step in flow.steps for condition in step.conditions))
    inputs = list(dict.fromkeys(item for step in flow.steps for item in step.inputs))
    outputs = list(dict.fromkeys(item for step in flow.steps for item in step.outputs))
    trigger = _flow_trigger(flow)
    answer = _flow_answer(flow, trigger, side_effects, outputs)
    return flow.model_copy(
        update={
            "answer": answer,
            "trigger": trigger,
            "actors": actors,
            "side_effects": side_effects,
            "decision_points": decision_points,
            "inputs": inputs,
            "outputs": outputs,
            "confidence_score": score,
            "confidence_label": confidence_label(score),
            "confidence": legacy_confidence(score),
            "evidence_count": len(evidence_items),
            "source_files": evidence_files(evidence_items),
            "source_locations": evidence_locations(evidence_items),
            "confidence_factors": factors,
        }
    )


def _flow_trigger(flow: BehaviorFlow) -> str:
    first = flow.steps[0] if flow.steps else None
    if not first:
        return "Unknown trigger"
    if first.kind == "request":
        return first.label
    if flow.category == "Runtime Flow":
        return "Runtime startup or internal runtime operation"
    if flow.category == "Command Execution Flow":
        return "Command or library entry point"
    return first.target or first.label


def _flow_answer(flow: BehaviorFlow, trigger: str, side_effects: list[str], outputs: list[str]) -> str:
    narratives = [step.narrative for step in flow.steps if step.narrative]
    if narratives:
        answer = f"When {trigger} occurs, " + " ".join(narratives)
    else:
        answer = flow.summary
    extras = []
    if side_effects:
        extras.append(f"Side effects include {', '.join(side_effects[:3]).lower()}.")
    if outputs:
        extras.append(f"Expected outputs include {', '.join(outputs[:3]).lower()}.")
    if extras:
        answer = f"{answer} {' '.join(extras)}"
    return answer


def _confidence_factors(flow: BehaviorFlow, evidence_items: list[Evidence]) -> dict[str, bool]:
    joined = "\n".join(f"{item.file_path}\n{item.indicator or ''}\n{item.snippet}" for item in evidence_items).lower()
    return {
        "entry point discovered": any(step.kind in {"request", "route", "controller", "bootstrap"} for step in flow.steps),
        "complete execution path": len(flow.steps) >= 3,
        "database interaction detected": "database" in joined or "repository" in joined or "save" in joined,
        "queue interaction detected": "queue" in joined or "worker" in joined,
        "external API interaction detected": "external-api" in joined or "fetch(" in joined or "axios." in joined,
        "naming consistency": _naming_consistency(flow, evidence_items),
    }


def _confidence_score(factors: dict[str, bool], step_count: int, evidence_count: int) -> int:
    score = 25
    score += 18 if factors["entry point discovered"] else 0
    score += 18 if factors["complete execution path"] else 0
    score += 10 if factors["database interaction detected"] else 0
    score += 8 if factors["queue interaction detected"] else 0
    score += 8 if factors["external API interaction detected"] else 0
    score += 12 if factors["naming consistency"] else 0
    score += min(8, max(0, evidence_count - 1) * 2)
    score += min(6, max(0, step_count - 1) * 2)
    return min(100, score)


def _naming_consistency(flow: BehaviorFlow, evidence_items: list[Evidence]) -> bool:
    tokens = {token.lower() for token in flow.name.replace("-", " ").split() if len(token) > 3}
    haystack = " ".join(item.file_path for item in evidence_items).lower()
    return bool(tokens and any(token in haystack for token in tokens))
