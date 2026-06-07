import "@xyflow/react/dist/style.css";
import { StrictMode, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Background, Controls, MiniMap, ReactFlow } from "@xyflow/react";
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  CircleHelp,
  Filter,
  GitBranch,
  Loader2,
  Map,
  Play,
  Search,
  ShieldAlert,
  Sparkles,
  Workflow
} from "lucide-react";
import "./styles.css";

const API = "";
const FLOW_CATEGORIES = [
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
  "Command Execution Flow"
];
const CONFIDENCE_LABELS = ["Low", "Medium", "High", "Very High"];

type ScanState = {
  scanId: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  currentPhase: string;
  errors: string[];
};

type ConfidenceLabel = "Low" | "Medium" | "High" | "Very High";

type Overview = {
  repo: { name: string; owner: string; url: string };
  classification: Record<string, unknown>;
  languages: Record<string, number>;
  frameworks: string[];
  counts: Record<string, number>;
  confidence_score: number;
  confidence_label: ConfidenceLabel;
  evidence_count: number;
  analysis_strategy: string;
};

type Structure = {
  nodes: { id: string; label: string; kind: string; file_path?: string; evidence_id?: string }[];
  edges: { id: string; source: string; target: string; kind: string; confidence_score: number; confidence_label: ConfidenceLabel; evidence_count: number; source_files: string[]; source_locations: string[]; evidence_ids: string[] }[];
};

type Flow = {
  id: string;
  name: string;
  repo_type: string;
  summary: string;
  answer: string;
  trigger: string;
  actors: string[];
  side_effects: string[];
  decision_points: string[];
  inputs: string[];
  outputs: string[];
  confidence_score: number;
  confidence_label: ConfidenceLabel;
  category: string;
  evidence_count: number;
  source_files: string[];
  source_locations: string[];
  confidence_factors: Record<string, boolean>;
  ai_summary_available: boolean;
  evidence_ids: string[];
  steps: { id: string; label: string; technical_label: string; kind: string; evidence_id: string; actor: string; action: string; target: string; operation: string; side_effects: string[]; conditions: string[]; inputs: string[]; outputs: string[]; narrative: string; confidence_score: number; confidence_label: ConfidenceLabel; evidence_count: number; source_files: string[]; source_locations: string[] }[];
};

type Risk = {
  id: string;
  title: string;
  category: string;
  severity: "critical" | "high" | "medium" | "low" | "informational";
  description: string;
  why_it_matters: string;
  evidence_ids: string[];
  confidence_score: number;
  confidence_label: ConfidenceLabel;
  evidence_count: number;
  source_files: string[];
  source_locations: string[];
  rank: number;
};

type Evidence = {
  id: string;
  file_path: string;
  symbol?: string;
  indicator?: string;
  snippet: string;
  start_line?: number;
  end_line?: number;
  confidence_score: number;
  confidence_label: ConfidenceLabel;
  related_flows: string[];
};

type Diagnostics = {
  pipeline: { key: string; label: string; status: string; progress: number }[];
  coverage: { routesAnalyzed: number; filesParsed: number; dependenciesResolved: number; flowsDetected: number; unknownRegions: number };
  unknowns: Record<string, string[]>;
  artifactFiles: string[];
  ai: { available?: boolean; role?: string };
};

type Summary = {
  title: string;
  positioning: string;
  deterministic: string;
  ai_available: boolean;
};

type Claim = {
  title: string;
  kind: string;
  confidenceScore: number;
  confidenceLabel: ConfidenceLabel;
  evidenceCount: number;
  sourceFiles: string[];
  sourceLocations: string[];
  evidenceId?: string;
};

function App() {
  const [repoUrl, setRepoUrl] = useState("https://github.com/expressjs/express");
  const [scan, setScan] = useState<ScanState | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [structure, setStructure] = useState<Structure | null>(null);
  const [flows, setFlows] = useState<Flow[]>([]);
  const [risks, setRisks] = useState<Risk[]>([]);
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<Evidence | null>(null);
  const [selectedClaim, setSelectedClaim] = useState<Claim | null>(null);
  const [view, setView] = useState<"flows" | "structure" | "risks" | "unknowns" | "summary">("flows");
  const [categoryFilter, setCategoryFilter] = useState("All");
  const [confidenceFilter, setConfidenceFilter] = useState("All");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);

  async function startScan(mode: "scan" | "demo") {
    setBusy(true);
    setOverview(null);
    setStructure(null);
    setFlows([]);
    setRisks([]);
    setDiagnostics(null);
    setSummary(null);
    setSelectedEvidence(null);
    setSelectedClaim(null);
    try {
      const data = await fetchJson<{ scanId: string }>(`${API}/api/scans`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repoUrl, mode })
      });
      setScan({ scanId: data.scanId, status: "queued", progress: 0, currentPhase: "fetch", errors: [] });
    } catch (error) {
      setScan(failedScan(errorMessage(error)));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!scan || scan.status === "completed" || scan.status === "failed") return;
    const timer = window.setInterval(async () => {
      try {
        const next = await fetchJson<ScanState>(`${API}/api/scans/${scan.scanId}`);
        setScan(next);
      } catch (error) {
        setScan((current) => failedScan(errorMessage(error), current?.scanId));
      }
    }, 800);
    return () => window.clearInterval(timer);
  }, [scan?.scanId, scan?.status]);

  useEffect(() => {
    if (!scan || scan.status !== "completed") return;
    Promise.all([
      fetchJson<Overview>(`${API}/api/scans/${scan.scanId}/overview`),
      fetchJson<Structure>(`${API}/api/scans/${scan.scanId}/structure`),
      fetchJson<Flow[]>(`${API}/api/scans/${scan.scanId}/flows`),
      fetchJson<Risk[]>(`${API}/api/scans/${scan.scanId}/risks`),
      fetchJson<Diagnostics>(`${API}/api/scans/${scan.scanId}/diagnostics`),
      fetchJson<Summary>(`${API}/api/scans/${scan.scanId}/summary`)
    ]).then(([overviewData, structureData, flowData, riskData, diagnosticsData, summaryData]) => {
      setOverview(overviewData);
      setStructure(structureData);
      setFlows(flowData);
      setRisks(riskData);
      setDiagnostics(diagnosticsData);
      setSummary(summaryData);
      const firstFlow = flowData[0];
      if (firstFlow) {
        setSelectedClaim(flowClaim(firstFlow));
        void loadEvidence(firstFlow.steps[0]?.evidence_id);
      }
    }).catch((error) => {
      setScan((current) => failedScan(errorMessage(error), current?.scanId));
    });
  }, [scan?.scanId, scan?.status]);

  async function loadEvidence(evidenceId?: string) {
    if (!evidenceId) return;
    try {
      setSelectedEvidence(await fetchJson<Evidence>(`${API}/api/evidence/${evidenceId}`));
    } catch (error) {
      setSelectedEvidence(null);
      setScan((current) => failedScan(errorMessage(error), current?.scanId));
    }
  }

  const filteredFlows = useMemo(() => {
    return flows.filter((flow) => {
      const matchesCategory = categoryFilter === "All" || flow.category === categoryFilter;
      const matchesConfidence = confidenceFilter === "All" || flow.confidence_label === confidenceFilter;
      const haystack = `${flow.name} ${flow.summary} ${flow.source_files.join(" ")}`.toLowerCase();
      return matchesCategory && matchesConfidence && haystack.includes(query.toLowerCase());
    });
  }, [flows, categoryFilter, confidenceFilter, query]);

  const filteredRisks = useMemo(() => {
    return risks.filter((risk) => {
      const matchesConfidence = confidenceFilter === "All" || risk.confidence_label === confidenceFilter;
      const haystack = `${risk.title} ${risk.category} ${risk.severity} ${risk.description} ${risk.source_files.join(" ")}`.toLowerCase();
      return matchesConfidence && haystack.includes(query.toLowerCase());
    });
  }, [risks, confidenceFilter, query]);

  const graph = useMemo(() => toFlowGraph(structure), [structure]);
  const repoType = String(overview?.classification.dominantType ?? "No scan");
  const classificationScore = Number(overview?.classification.confidenceScore ?? overview?.confidence_score ?? 0);

  return (
    <main className="app-shell">
      <aside className="left-rail">
        <div className="brand">
          <Map size={22} />
          <div>
            <p>Business GitFlow</p>
            <strong>Flow Map</strong>
          </div>
        </div>

        <section className="scan-box">
          <label>Repository</label>
          <div className="repo-field">
            <Search size={16} />
            <input value={repoUrl} onChange={(event) => setRepoUrl(event.target.value)} placeholder="https://github.com/owner/repo" />
          </div>
          <div className="scan-actions">
            <button onClick={() => void startScan("scan")} disabled={busy}>
              {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
              Scan
            </button>
            <button className="secondary" onClick={() => void startScan("demo")} disabled={busy}>Demo</button>
          </div>
        </section>

        <section className="rail-section">
          <header><GitBranch size={16} /> Scan</header>
          <StatusLine scan={scan} />
          <Pipeline diagnostics={diagnostics} activePhase={scan?.currentPhase} />
        </section>

        <section className="rail-section">
          <header><Filter size={16} /> Filters</header>
          <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
            <option>All</option>
            {FLOW_CATEGORIES.map((category) => <option key={category}>{category}</option>)}
          </select>
          <select value={confidenceFilter} onChange={(event) => setConfidenceFilter(event.target.value)}>
            <option>All</option>
            {CONFIDENCE_LABELS.map((label) => <option key={label}>{label}</option>)}
          </select>
          <input className="query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find what happens when..." />
        </section>

        <section className="rail-section">
          <header><CircleHelp size={16} /> Coverage</header>
          <Coverage diagnostics={diagnostics} />
        </section>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">GitDiagram shows structure. Business GitFlow shows structure + flows + evidence.</p>
            <h1>{overview ? `${overview.repo.owner}/${overview.repo.name}` : "What happens when X occurs?"}</h1>
          </div>
          <div className="classification-card">
            <span>{repoType}</span>
            <strong>{overview?.analysis_strategy ?? "Analysis pending"}</strong>
            <small>{classificationScore}% confidence · {overview?.evidence_count ?? 0} evidence sources</small>
          </div>
        </header>

        <section className="metrics-row">
          <Metric title="Flows Detected" value={String(diagnostics?.coverage.flowsDetected ?? flows.length)} detail={`${filteredFlows.length} visible`} />
          <Metric title="Files Parsed" value={`${diagnostics?.coverage.filesParsed ?? 0}%`} detail={`${overview?.counts.files ?? 0} files scanned`} />
          <Metric title="Dependencies" value={`${diagnostics?.coverage.dependenciesResolved ?? 0}%`} detail={`${overview?.counts.graphEdges ?? 0} relationships`} />
          <Metric title="Unknown Regions" value={String(diagnostics?.coverage.unknownRegions ?? 0)} detail="shown honestly" />
        </section>

        <nav className="view-tabs">
          <button className={view === "flows" ? "active" : ""} onClick={() => setView("flows")}><Workflow size={16} /> Flow Map</button>
          <button className={view === "structure" ? "active" : ""} onClick={() => setView("structure")}><Boxes size={16} /> Structure Graph</button>
          <button className={view === "risks" ? "active" : ""} onClick={() => setView("risks")}><ShieldAlert size={16} /> Risks</button>
          <button className={view === "unknowns" ? "active" : ""} onClick={() => setView("unknowns")}><AlertTriangle size={16} /> Unknowns</button>
          <button className={view === "summary" ? "active" : ""} onClick={() => setView("summary")}><Sparkles size={16} /> Summary</button>
        </nav>

        <section className="analysis-panel">
          {view === "flows" && <FlowMap flows={filteredFlows} hasScan={Boolean(overview || diagnostics || scan?.status === "completed")} activeEvidenceId={selectedEvidence?.id} onSelect={(flow, evidenceId) => { setSelectedClaim(flowClaim(flow)); void loadEvidence(evidenceId); }} />}
          {view === "structure" && (
            <div className="graph-panel">
              <ReactFlow
                nodes={graph.nodes}
                edges={graph.edges}
                fitView
                onNodeClick={(_, node) => {
                  const evidenceId = node.data.evidenceId;
                  if (typeof evidenceId === "string") {
                    setSelectedClaim({ title: String(node.data.label), kind: "Structure node", confidenceScore: 65, confidenceLabel: "Medium", evidenceCount: 1, sourceFiles: [], sourceLocations: [], evidenceId });
                    void loadEvidence(evidenceId);
                  }
                }}
              >
                <MiniMap />
                <Controls />
                <Background />
              </ReactFlow>
            </div>
          )}
          {view === "risks" && <RiskPanel risks={filteredRisks} onSelect={(risk) => { setSelectedClaim(riskClaim(risk)); void loadEvidence(risk.evidence_ids[0]); }} />}
          {view === "unknowns" && <Unknowns diagnostics={diagnostics} />}
          {view === "summary" && <SummaryPanel summary={summary} diagnostics={diagnostics} overview={overview} />}
        </section>
      </section>

      <aside className="inspector">
        <EvidenceInspector claim={selectedClaim} evidence={selectedEvidence} />
      </aside>
    </main>
  );
}

function Metric({ title, value, detail }: { title: string; value: string; detail: string }) {
  return <article className="metric"><span>{title}</span><strong>{value}</strong><small>{detail}</small></article>;
}

function StatusLine({ scan }: { scan: ScanState | null }) {
  return (
    <div className={`status-line ${scan?.status ?? "idle"}`}>
      {scan?.status === "completed" ? <CheckCircle2 size={16} /> : scan?.status === "failed" ? <AlertTriangle size={16} /> : <GitBranch size={16} />}
      <span>{scan ? `${scan.status} · ${scan.progress}%` : "ready"}</span>
      {scan?.errors[0] && <small>{scan.errors[0]}</small>}
    </div>
  );
}

function Pipeline({ diagnostics, activePhase }: { diagnostics: Diagnostics | null; activePhase?: string }) {
  const stages = diagnostics?.pipeline ?? ["fetch", "classify repository", "build structure graph", "detect execution paths", "generate behavior flows", "calculate confidence", "rank risks", "persist artifacts"].map((label) => ({ key: label, label, status: activePhase === label ? "running" : "queued", progress: 0 }));
  return <ol className="pipeline">{stages.map((stage) => <li className={stage.status} key={stage.key}>{stage.label}</li>)}</ol>;
}

function Coverage({ diagnostics }: { diagnostics: Diagnostics | null }) {
  const coverage = diagnostics?.coverage;
  const rows = [
    ["Routes Analyzed", coverage?.routesAnalyzed ?? 0],
    ["Files Parsed", coverage?.filesParsed ?? 0],
    ["Dependencies Resolved", coverage?.dependenciesResolved ?? 0]
  ];
  return <div className="coverage-list">{rows.map(([label, value]) => <p key={label}><span>{label}</span><strong>{value}%</strong></p>)}</div>;
}

function FlowMap({ flows, hasScan, activeEvidenceId, onSelect }: { flows: Flow[]; hasScan: boolean; activeEvidenceId?: string; onSelect: (flow: Flow, evidenceId: string) => void }) {
  if (!flows.length) return <Empty text={hasScan ? "No flows match the current filters." : "Run a scan to build an evidence-backed Flow Map."} />;
  return (
    <div className="flow-grid">
      {flows.map((flow) => (
        <article className="flow-card" key={flow.id}>
          <header>
            <div>
              <span className="category">{flow.category}</span>
              <h2>{flow.name}</h2>
            </div>
            <Confidence score={flow.confidence_score} label={flow.confidence_label} />
          </header>
          <section className="flow-answer">
            <span>What Happens</span>
            <p>{flow.answer || flow.summary}</p>
          </section>
          <div className="flow-context">
            <InfoBlock label="Trigger" value={flow.trigger || "Unknown trigger"} />
            <InfoBlock label="Actors" value={flow.actors.join(", ") || "System"} />
            <InfoBlock label="Inputs" value={flow.inputs.join(", ") || "Not detected"} />
            <InfoBlock label="Outputs" value={flow.outputs.join(", ") || "Not detected"} />
          </div>
          {(flow.side_effects.length > 0 || flow.decision_points.length > 0) && (
            <div className="effect-row">
              {flow.side_effects.map((effect) => <span key={effect}>{effect}</span>)}
              {flow.decision_points.map((condition) => <span className="condition" key={condition}>{condition}</span>)}
            </div>
          )}
          <EvidenceMeta count={flow.evidence_count} files={flow.source_files} locations={flow.source_locations} />
          <div className="factor-row">
            {Object.entries(flow.confidence_factors).map(([factor, active]) => <span className={active ? "on" : ""} key={factor}>{factor}</span>)}
          </div>
          <ol>
            {flow.steps.map((step) => (
              <li key={step.id}>
                <button className={activeEvidenceId === step.evidence_id ? "selected" : ""} onClick={() => onSelect(flow, step.evidence_id)}>
                  <span>{step.actor} {step.action} {step.target}</span>
                  <small>{step.operation} · {step.technical_label} · {step.confidence_score}% · {step.evidence_count} evidence</small>
                  {step.narrative && <em>{step.narrative}</em>}
                </button>
              </li>
            ))}
          </ol>
        </article>
      ))}
    </div>
  );
}

function InfoBlock({ label, value }: { label: string; value: string }) {
  return <div className="info-block"><span>{label}</span><strong>{value}</strong></div>;
}

function RiskPanel({ risks, onSelect }: { risks: Risk[]; onSelect: (risk: Risk) => void }) {
  if (!risks.length) return <Empty text="No evidence-backed risks are currently ranked." />;
  return (
    <div className="risk-list">
      {risks.map((risk) => (
        <article className={`risk ${risk.severity}`} key={risk.id}>
          <header>
            <span>#{risk.rank} · {risk.category}</span>
            <strong>{risk.severity}</strong>
          </header>
          <h2>{risk.title}</h2>
          <p>{risk.description}</p>
          <small>{risk.why_it_matters}</small>
          <EvidenceMeta count={risk.evidence_count} files={risk.source_files} locations={risk.source_locations} />
          <button onClick={() => onSelect(risk)}>Open evidence</button>
        </article>
      ))}
    </div>
  );
}

function Unknowns({ diagnostics }: { diagnostics: Diagnostics | null }) {
  if (!diagnostics) return <Empty text="Unknown regions will appear after a scan completes." />;
  return (
    <div className="unknown-grid">
      {Object.entries(diagnostics.unknowns).map(([key, values]) => (
        <article key={key}>
          <h2>{titleCase(key)}</h2>
          <strong>{values.length}</strong>
          {values.length ? <ul>{values.slice(0, 8).map((value) => <li key={value}>{value}</li>)}</ul> : <p>No items detected.</p>}
        </article>
      ))}
    </div>
  );
}

function SummaryPanel({ summary, diagnostics, overview }: { summary: Summary | null; diagnostics: Diagnostics | null; overview: Overview | null }) {
  if (!summary) return <Empty text="Summary artifacts will appear after a completed scan." />;
  return (
    <div className="summary-panel">
      <h2>{summary.title}</h2>
      <p>{summary.positioning}</p>
      <p>{summary.deterministic}</p>
      <div className="artifact-list">
        {diagnostics?.artifactFiles.map((file) => <span key={file}>{file}</span>)}
      </div>
      <div className="ai-note">
        <Sparkles size={16} />
        <span>{summary.ai_available ? "AI summaries available." : "AI unavailable or unused. Deterministic analysis is complete."}</span>
      </div>
      <pre>{JSON.stringify({ classification: overview?.classification, ai: diagnostics?.ai }, null, 2)}</pre>
    </div>
  );
}

function EvidenceInspector({ claim, evidence }: { claim: Claim | null; evidence: Evidence | null }) {
  return (
    <>
      <header className="inspector-head">
        <span>Evidence Inspector</span>
        {claim && <Confidence score={claim.confidenceScore} label={claim.confidenceLabel} />}
      </header>
      {claim ? (
        <section className="claim-box">
          <p>{claim.kind}</p>
          <h2>{claim.title}</h2>
          <EvidenceMeta count={claim.evidenceCount} files={claim.sourceFiles} locations={claim.sourceLocations} />
        </section>
      ) : <p className="empty-copy">Select a flow step, risk, or graph node.</p>}
      {evidence && (
        <section className="source-box">
          <p className="file-path">{evidence.file_path}:{evidence.start_line ?? 1}</p>
          <p className="symbol">{evidence.symbol ?? evidence.indicator ?? "source evidence"}</p>
          <pre>{evidence.snippet}</pre>
        </section>
      )}
    </>
  );
}

function EvidenceMeta({ count, files, locations }: { count: number; files: string[]; locations: string[] }) {
  return (
    <div className="evidence-meta">
      <span>{count} evidence</span>
      <span>{files.slice(0, 2).join(", ") || "source pending"}</span>
      <span>{locations.slice(0, 2).join(", ") || "location pending"}</span>
    </div>
  );
}

function Confidence({ score, label }: { score: number; label: ConfidenceLabel }) {
  return <span className={`confidence ${label.toLowerCase().replace(" ", "-")}`}>{score}% {label}</span>;
}

function Empty({ text }: { text: string }) {
  return <div className="empty-state"><Workflow size={28} /><p>{text}</p></div>;
}

function flowClaim(flow: Flow): Claim {
  return { title: flow.name, kind: flow.category, confidenceScore: flow.confidence_score, confidenceLabel: flow.confidence_label, evidenceCount: flow.evidence_count, sourceFiles: flow.source_files, sourceLocations: flow.source_locations, evidenceId: flow.evidence_ids[0] };
}

function riskClaim(risk: Risk): Claim {
  return { title: risk.title, kind: `Risk · ${risk.severity}`, confidenceScore: risk.confidence_score, confidenceLabel: risk.confidence_label, evidenceCount: risk.evidence_count, sourceFiles: risk.source_files, sourceLocations: risk.source_locations, evidenceId: risk.evidence_ids[0] };
}

function toFlowGraph(structure: Structure | null) {
  if (!structure) return { nodes: [], edges: [] };
  const nodes = structure.nodes.slice(0, 140).map((node, index) => ({
    id: node.id,
    data: { label: `${node.kind}: ${node.label}`, evidenceId: node.evidence_id },
    position: { x: (index % 5) * 230, y: Math.floor(index / 5) * 112 },
    className: `graph-node ${node.kind}`,
    sourcePosition: "right" as const,
    targetPosition: "left" as const,
    selectable: true,
    draggable: true
  }));
  const edges = structure.edges.filter((edge) => edge.evidence_count > 0).slice(0, 220).map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, label: `${edge.kind} · ${edge.confidence_score}%`, animated: edge.kind === "imports" }));
  return { nodes, edges };
}

function titleCase(value: string) {
  return value.replace(/([A-Z])/g, " $1").replace(/^./, (letter) => letter.toUpperCase());
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

function failedScan(message: string, scanId = "unavailable"): ScanState {
  return { scanId, status: "failed", progress: 100, currentPhase: "failed", errors: [message] };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected request failure.";
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
