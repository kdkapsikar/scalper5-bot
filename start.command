#!/bin/bash
# Double-click on a Mac (or run ./start.command) to open the Scalp5 portal in your browser.
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; }
exec .venv/bin/streamlit run app.py
