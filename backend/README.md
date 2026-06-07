# Business GitFlow Backend

FastAPI backend for the Business GitFlow prototype.

Run locally:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m uvicorn backend.app.api:app --reload --port 8000
```

The backend stores cloned repositories and analysis output in `.bfo-data` at the project root.

The repository is licensed under the MIT License. See the root `LICENSE` file.
