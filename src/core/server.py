import threading
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from src.core.logger import get_logger

logger = get_logger("hub.server")

_start_time: float = 0.0
_registry: Any = None
_zoho_auth: Any = None
_active_runs: dict[str, dict] = {}  # module_name -> run info


def create_app(registry: Any, zoho_auth: Any) -> FastAPI:
    global _start_time, _registry, _zoho_auth
    _start_time = time.time()
    _registry = registry
    _zoho_auth = zoho_auth

    app = FastAPI(title="QAT Operations Hub", version="1.0.0")

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "healthy",
            "uptime_seconds": int(time.time() - _start_time),
            "modules_registered": _registry.registered_names,
            "zoho_auth_valid": _zoho_auth.is_token_valid,
            "active_runs": {k: v["status"] for k, v in _active_runs.items()},
        }

    @app.get("/metrics")
    async def metrics() -> dict:
        all_status = _registry.get_all_status()
        return all_status

    @app.get("/status/{module_name}")
    async def module_status(module_name: str) -> dict:
        try:
            status = _registry.get_module_status(module_name)
            if module_name in _active_runs:
                status["active_run"] = _active_runs[module_name]
            return status
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.post("/run/{module_name}")
    async def run_module(module_name: str, body: dict | None = None) -> dict:
        kwargs = body or {}

        # Check if already running
        if module_name in _active_runs and _active_runs[module_name]["status"] == "running":
            return {
                "accepted": True,
                "message": f"{module_name} is already running",
                "started_at": _active_runs[module_name]["started_at"],
            }

        # Launch in background thread so we respond immediately
        def _run():
            try:
                _active_runs[module_name] = {
                    "status": "running",
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                result = _registry.run_module(module_name, **kwargs)
                _active_runs[module_name] = {
                    "status": "completed",
                    "started_at": _active_runs[module_name]["started_at"],
                    "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "result": result,
                }
            except Exception as exc:
                logger.error("Background run of %s failed: %s", module_name, exc)
                _active_runs[module_name] = {
                    "status": "failed",
                    "started_at": _active_runs[module_name].get("started_at", ""),
                    "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "error": str(exc),
                }

        try:
            _registry.get_module_status(module_name)  # validate module exists
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        return {
            "accepted": True,
            "message": f"{module_name} started in background",
            "check_status": f"/status/{module_name}",
        }

    return app
