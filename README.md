# Business GitFlow

Business GitFlow is a working prototype for exploring how a repository behaves, not just how its files are arranged.

It scans a public GitHub repository, builds a small structure graph, tries to find behavior flows, and shows the source evidence used for each detected flow or risk. The analysis is heuristic, so the app also reports unknowns instead of pretending it understood everything.

## Why I Built It

Most repo visualization tools are good at showing folders, files, and dependencies.

When I read larger codebases, I usually need a different answer:

> What actually happens when this system runs?

This prototype is my attempt at that question. It is not a finished product or a full static-analysis engine yet, but it is a working version of the idea.

## What Currently Works

The current test suite covers these behaviors:

- Public GitHub URL validation and local scan creation.
- Generated test repository analysis that produces behavior flows with evidence IDs, confidence labels, source files, and source locations.
- Repository classification for sample business app, infrastructure, CLI, library, and runtime repositories.
- Structure graph generation from files, routes, symbols, and local JS/TS imports.
- Directory `index.ts` import resolution, including flow expansion through that import.
- Unknown-region reporting for missing local imports.
- Ranked risk findings with evidence metadata.
- Local Ollama summaries disabled by default, with deterministic summaries still working.
- GitHub archive fallback when a shallow Git clone fails.

## Tech Stack

- Frontend: React, TypeScript, Vite, React Flow.
- Backend: FastAPI, Pydantic, Python.
- Storage: local `.bfo-data/` folder for cloned repos and scan artifacts.
- Optional summaries: local Ollama, disabled by default.

## Quick Start

Install frontend dependencies:

```sh
npm install
```

Create the backend environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
```

Start the backend:

```sh
.venv/bin/python -m uvicorn backend.app.api:app --reload --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal:

```sh
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## How To Use

1. Enter a public GitHub repo URL, for example `https://github.com/expressjs/express`.
2. Click `Scan`, or choose one of the smaller demo-friendly open-source business examples.
3. Review the Flow Map, Structure Graph, Risks, Unknowns, and Summary tabs.
4. Select a flow step, risk, or graph node to inspect the source evidence.

Scan artifacts are written locally under `.bfo-data/scans/{scan_id}/`.

## Testing

Run backend tests:

```sh
.venv/bin/python -m unittest discover -s backend/tests
```

Build the frontend:

```sh
npm run build
```

## Limitations

- Public GitHub repositories only.
- Static heuristic analysis, not a compiler, runtime tracer, or full security scanner.
- JS/TS route and import flow detection is the strongest tested path right now.
- Results can miss dynamic behavior, generated code, reflection, framework magic, or runtime wiring.
- AI summaries are optional wording only. They are not the source of truth.

## License

MIT License. See [LICENSE](LICENSE).
