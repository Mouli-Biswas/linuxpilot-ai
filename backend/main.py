"""
main.py
-------
FastAPI application entrypoint for LinuxPilot AI's backend. Wires
together the intent classifier, diagnostics, services, logs, file
search, command execution, and agent orchestrator routers behind a
single app instance.

Run locally:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

Interactive API docs (Swagger) are then available at /docs.
"""

from __future__ import annotations
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ✅ FIXED IMPORTS
from backend.api.routes_agent import router as agent_router
from backend.api.routes_diagnostics import router as diagnostics_router
from backend.api.routes_intent import router as intent_router
from backend.api.routes_search_exec import exec_router, search_router
from backend.api.routes_services_logs import logs_router, services_router

from backend.database.db import init_db
from backend.utils.config import settings
from backend.utils.logger import setup_logging

setup_logging()
logger = logging.getLogger("linuxpilot.main")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Starting LinuxPilot AI backend (env=%s)", settings.APP_ENV)
    init_db()
    yield
    logger.info("Shutting down LinuxPilot AI backend")


app = FastAPI(
    title="LinuxPilot AI",
    description=(
        "AI Operations Agent for Linux: intent detection, task planning, "
        "diagnostics, service management, log analysis, safe command "
        "execution, and natural-language explanations."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Tauri desktop app / local dev frontend origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://localhost:1420", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(intent_router)
app.include_router(diagnostics_router)
app.include_router(services_router)
app.include_router(logs_router)
app.include_router(search_router)
app.include_router(exec_router)
app.include_router(agent_router)


from fastapi.responses import JSONResponse


@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled server exception on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": f"Internal server error: {exc}"},
    )


@app.get("/api/health", tags=["health"])
def health_check() -> dict:
    return {
        "status": "ok",
        "env": settings.APP_ENV,
        "ollama_model": settings.OLLAMA_MODEL,
        "command_execution_enabled": settings.ALLOW_COMMAND_EXECUTION,
    }



