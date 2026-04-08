# Adding New Modules to the QAT Operations Hub

This guide explains how to create and register a new automation module.

## The BaseModule Interface

Every module must subclass `BaseModule` (from `src.core.module_registry`) and implement three methods:

```python
from src.core.module_registry import BaseModule, HubContext

class MyNewModule(BaseModule):
    def __init__(self, hub_context: HubContext) -> None:
        super().__init__(hub_context)
        # Access shared services via self.ctx:
        #   self.ctx.config          — application config
        #   self.ctx.zoho_auth       — Zoho OAuth manager
        #   self.ctx.claude_client   — Claude API wrapper
        #   self.ctx.metrics         — SQLite metrics collector
        #   self.ctx.notifications   — Teams webhook notifier

    def name(self) -> str:
        """Return a unique identifier, e.g. 'my_new_module'."""
        return "my_new_module"

    def run(self, **kwargs) -> dict:
        """Execute the module's work. Return a summary dict with at least a 'status' key."""
        run_id = self.ctx.metrics.start_run(self.name())
        # ... do work ...
        self.ctx.metrics.complete_run(run_id, "completed")
        return {"status": "completed"}

    def get_status(self) -> dict:
        """Return the latest run status from the metrics DB."""
        return self.ctx.metrics.get_module_status(self.name()) or {"status": "never_run"}
```

## File Layout

Create a new package under `src/modules/`:

```
src/modules/my_new_module/
├── __init__.py          # Can be empty
├── module.py            # Must contain a class derived from BaseModule
└── ...                  # Any helper files your module needs
```

## Auto-Discovery

The Hub automatically discovers modules at startup by scanning `src/modules/*/module.py` for classes that subclass `BaseModule`. No manual registration is needed — just place your package under `src/modules/` and restart the Hub.

## Running Your Module

```bash
# One-shot run
python src/main.py --run my_new_module

# Or trigger via the API
curl -X POST http://localhost:8100/run/my_new_module -H "Content-Type: application/json" -d "{}"
```

## Best Practices

1. **Metrics** — Call `metrics.start_run` / `record_event` / `complete_run` for observability.
2. **Dry run** — Accept a `dry_run` kwarg and respect it. Default to safe/read-only.
3. **Error isolation** — The registry catches top-level exceptions so your module cannot crash the Hub, but handle expected errors gracefully within your pipeline.
4. **Notifications** — Send a Teams summary when the run finishes and a critical alert on unrecoverable failures.
5. **Logging** — Use `get_logger(__name__)` for structured, namespaced logs.
6. **Configuration** — Add any new env vars to `.env.template` and load them in `src/core/config.py`.
