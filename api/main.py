"""Scalp5 API (FastAPI). The web app (web/, on GitHub Pages) talks to it; the trading engine lives in scalpbot/.

    uvicorn api.main:app --reload --port 8000          # local development (the web dev server proxies /api here)

Environment: DATABASE_URL, SCALP_MASTER_KEY, ADMIN_EMAILS (see scalpbot/accounts.py); CORS_ORIGINS, the web app's
origin(s), e.g. https://kdkapsikar.github.io; APP_URL, the web app's address (for the Upstox redirect URI).
If web/dist exists (npm run build in web/), the API also serves the web app itself, for single-machine installs.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from scalpbot import creds

from . import account, market
from .core import accounts, app_url

creds.strict()           # this process serves many users: never fall back to keys in the server's environment

app = FastAPI(title="Scalp5 API", docs_url=None, redoc_url=None, openapi_url=None)

origins = [o.strip().rstrip("/") for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
origins += ["http://localhost:5173", "http://127.0.0.1:5173"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PUT", "DELETE"],
                   allow_headers=["Authorization", "Content-Type"], max_age=600)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(x) for x in first.get("loc", [])[1:])
    return JSONResponse({"error": f"Check {where or 'the form'}: {first.get('msg', 'invalid value')}."}, status_code=422)


@app.get("/api/health")
def health():
    accounts()                 # touches the database settings, so a broken DATABASE_URL shows up here
    return {"ok": True}


app.include_router(account.router)
app.include_router(market.router)

# --------------------------------------------------------------------------- optional: serve the built web app
WEB = Path(os.getenv("SCALP_WEB_DIST", Path(__file__).resolve().parent.parent / "web" / "dist"))
if not (WEB / "index.html").exists():
    @app.get("/", include_in_schema=False)
    def home(request: Request):
        """Hosted API: send visitors (and Upstox logins still using the API's address as redirect URI) to the app."""
        target = app_url()
        if "code" in request.query_params:
            target += "/upstox/callback?" + urlencode({k: v for k, v in request.query_params.items() if k in ("code", "state")})
        return RedirectResponse(target, status_code=302)
else:
    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str):
        f = (WEB / path).resolve()
        if path and f.is_file() and WEB.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(WEB / "index.html")          # client-side routes
