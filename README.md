# Business GitFlow

Evidence-first repository analysis for turning source code into business flow maps.

Business GitFlow is a working prototype that scans a public GitHub repository, builds a structure graph, detects behavior flows, ranks risky areas, and links every claim back to source-level evidence.

Most repository visualization tools answer:

> What files exist?

Business GitFlow tries to answer:

> How does this system actually work?

It is designed for developers joining larger codebases who need more than folders, files, and dependency edges. The goal is to show structure, workflows, confidence, risks, unknowns, and the source snippets behind each claim.

## What It Does

- Scans a public GitHub repository.
- Classifies the repository type, such as business application, CLI, runtime, library, or infrastructure.
- Builds a structure graph from files, routes, imports, services, and detected code relationships.
- Detects execution and behavior flows from source evidence.
- Generates business-facing flow summaries.
- Calculates confidence scores for flows, graph edges, and risks.
- Ranks risk areas such as missing validation, broad service files, external side effects, and low-confidence paths.
- Shows source evidence for each detected claim.
- Reports unknown regions, including dynamic imports, unresolved local dependencies, generated code, or unsupported syntax.

## Why This Exists

Architecture diagrams explain where things are.

Developers also need to know what happens:

- What happens when a customer signs up?
- Where does the payment flow move?
- Which files participate in an approval process?
- Which execution paths look risky?
- Which claims are actually backed by code evidence?

Business GitFlow is built around one rule:

> No workflow, risk, summary, or relationship should be shown unless there is source-level evidence behind it.

Every claim should be able to answer:

- Where did this come from?
- Which file supports it?
- How confident is the system?
- What part of the code proves it?

## Tech Stack

- Frontend: React, TypeScript, Vite, React Flow, Lucide icons.
- Backend: FastAPI, Pydantic, Python.
- Repository access: shallow Git clone with sparse checkout and GitHub archive fallback.
- Optional AI summaries: local Ollama only, disabled by default.
- Storage: local `.bfo-data/` directory for cloned repos, scan metadata, artifacts, and evidence indexes.

## Quick Start

### 1. Clone and install frontend dependencies

```sh
npm install
```

### 2. Create the backend virtual environment

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
```

### 3. Start the backend

```sh
.venv/bin/python -m uvicorn backend.app.api:app --reload --host 127.0.0.1 --port 8000
```

### 4. Start the frontend

In another terminal:

```sh
npm run dev
```

Open the Vite URL, usually:

```text
http://127.0.0.1:5173
```

## Usage

1. Enter a public GitHub repository URL, for example `https://github.com/expressjs/express`.
2. Click `Scan`.
3. Wait for the pipeline to complete:
   - fetch
   - classify repository
   - build structure graph
   - detect execution paths
   - generate behavior flows
   - calculate confidence
   - rank risks
   - persist artifacts
4. Explore:
   - Flow Map
   - Structure Graph
   - Risks
   - Unknowns
   - Summary
5. Select a flow step, risk, or graph node to inspect the source evidence behind it.

You can also use `Demo` to scan the built-in demo repository without entering a GitHub URL.

## API Endpoints

The backend exposes these local endpoints:

```text
GET  /health
POST /api/scans
GET  /api/scans/{scan_id}
GET  /api/scans/{scan_id}/overview
GET  /api/scans/{scan_id}/structure
GET  /api/scans/{scan_id}/flows
GET  /api/scans/{scan_id}/risks
GET  /api/scans/{scan_id}/diagnostics
GET  /api/scans/{scan_id}/summary
GET  /api/evidence/{evidence_id}
```

Example scan request:

```sh
curl -X POST http://127.0.0.1:8000/api/scans \
  -H "Content-Type: application/json" \
  -d '{"repoUrl":"https://github.com/expressjs/express","mode":"scan"}'
```

## Generated Artifacts

Scan output is stored locally in `.bfo-data/scans/{scan_id}/`.

Generated files include:

- `repository.json`
- `graph.json`
- `flows.json`
- `risks.json`
- `evidence.json`
- `diagnostics.json`
- `summary.json`

The `.bfo-data/` folder is intentionally ignored by Git.

## Optional AI Summaries

Business GitFlow works without AI. By default, summaries are deterministic and evidence-backed.

To enable local AI-assisted wording through Ollama:

```sh
BFO_ENABLE_AI=1 OLLAMA_MODEL=gemma4 .venv/bin/python -m uvicorn backend.app.api:app --reload --host 127.0.0.1 --port 8000
```

AI is used only for optional summary wording. The detected flows, evidence, confidence, and risk ranking are still produced by deterministic repository analysis.

## Testing

Run backend tests:

```sh
.venv/bin/python -m unittest discover -s backend/tests
```

Build the frontend:

```sh
npm run build
```

## Current Limitations

- Public GitHub repositories only.
- Private repository support and deletion controls are not complete yet.
- Analysis is heuristic and evidence-first, not a full compiler or runtime tracer.
- Dynamic language behavior, reflection, generated code, and unresolved dependencies are reported as unknowns when detected.
- Large repositories may take longer and are scanned through a sparse checkout strategy.

## Repository Status

This repo contains the working prototype/code for Business GitFlow. Some demo or video visuals may use AI-assisted presenter imagery or slightly different product styling for explanation, but this repository is the implementation source.

## License

No license has been selected yet.
