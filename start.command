#!/bin/bash
# Double-click on a Mac (or run ./start.command) to run Scalp5 on this computer: the API serves the web app at
# http://localhost:8000. Needs Python 3.12+ and Node 20+.
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; }
[ -f web/dist/index.html ] || (cd web && npm ci && npm run build)
(sleep 3 && open http://localhost:8000) &
exec .venv/bin/uvicorn api.main:app --port 8000
