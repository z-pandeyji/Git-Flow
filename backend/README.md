# Business GitFlow Backend

Run locally:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m uvicorn backend.app.api:app --reload --port 8000
```

The backend stores V1 cloned repositories and analysis output in `.bfo-data` at the project root.
