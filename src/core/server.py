import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from src.core.logger import get_logger

logger = get_logger("hub.server")

_start_time: float = 0.0
_registry: Any = None
_zoho_auth: Any = None


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
        }

    @app.get("/metrics")
    async def metrics() -> dict:
        all_status = _registry.get_all_status()
        return all_status

    @app.get("/status/{module_name}")
    async def module_status(module_name: str) -> dict:
        try:
            return _registry.get_module_status(module_name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.post("/run/{module_name}")
    async def run_module(module_name: str, body: dict | None = None) -> dict:
        kwargs = body or {}
        try:
            result = _registry.run_module(module_name, **kwargs)
            return result
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    return app
