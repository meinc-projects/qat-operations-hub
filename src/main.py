"""QAT Operations Hub — Application entry point.

Usage::

    # Dry-run a specific module
    python src/main.py --run renewal_backfill --dry-run

    # Live-run a specific module
    python src/main.py --run renewal_backfill

    # Start in service mode (server only — modules triggered via API)
    python src/main.py --serve
"""

import argparse
import sys
import threading
from pathlib import Path

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="QAT Operations Hub")
    parser.add_argument("--run", type=str, help="Module name to run (e.g. renewal_backfill)")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode (no CRM writes)")
    parser.add_argument("--max-deals", type=int, default=0, help="Limit number of deals to process (0 = all)")
    parser.add_argument("--skip-renewals", action="store_true", default=None,
                        help="Skip renewal deal creation (overrides BACKFILL_SKIP_RENEWALS)")
    parser.add_argument("--create-renewals", action="store_true", default=None,
                        help="Enable renewal deal creation (overrides BACKFILL_SKIP_RENEWALS)")
    parser.add_argument("--serve", action="store_true", help="Start in service mode (server only)")
    args = parser.parse_args()

    # Ensure project root is on sys.path so imports like 'src.core.config' work
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from src.core.config import load_config
    from src.core.logger import setup_logging, get_logger

    config = load_config()
    setup_logging(log_level=config.log_level, project_root=config.project_root)
    logger = get_logger("hub.main")
    logger.info("QAT Operations Hub starting up")

    # Ensure runtime directories exist
    (config.project_root / "logs").mkdir(parents=True, exist_ok=True)
    (config.project_root / "data").mkdir(parents=True, exist_ok=True)

    from src.core.zoho_auth import ZohoAuthManager
    from src.core.claude_client import ClaudeClient
    from src.core.metrics import MetricsCollector
    from src.core.notifications import TeamsNotifier
    from src.core.module_registry import HubContext, ModuleRegistry
    from src.core.server import create_app

    zoho_auth = ZohoAuthManager(
        client_id=config.zoho.client_id,
        client_secret=config.zoho.client_secret,
        refresh_token=config.zoho.refresh_token,
        accounts_domain=config.zoho.accounts_domain,
        api_domain=config.zoho.api_domain,
    )

    metrics = MetricsCollector(data_dir=config.project_root / "data")
    claude_client = ClaudeClient(api_key=config.anthropic_api_key, metrics_collector=metrics)
    notifier = TeamsNotifier(webhook_url=config.teams_webhook_url)

    hub_context = HubContext(
        config=config,
        zoho_auth=zoho_auth,
        claude_client=claude_client,
        metrics=metrics,
        notifications=notifier,
    )

    registry = ModuleRegistry(hub_context)
    registry.discover_and_register()
    logger.info("Modules registered: %s", registry.registered_names)

    app = create_app(registry, zoho_auth)

    if args.run:
        # One-shot mode: start server in background then run the module
        server_thread = threading.Thread(
            target=uvicorn.run,
            kwargs={
                "app": app,
                "host": config.hub_host,
                "port": config.hub_port,
                "log_level": "warning",
            },
            daemon=True,
        )
        server_thread.start()
        logger.info("FastAPI server started on %s:%d (background)", config.hub_host, config.hub_port)

        kwargs = {}
        if args.dry_run:
            kwargs["dry_run"] = True
        if args.max_deals > 0:
            kwargs["max_deals"] = args.max_deals
        if args.skip_renewals:
            kwargs["skip_renewals"] = True
        elif args.create_renewals:
            kwargs["skip_renewals"] = False

        logger.info("Running module '%s' with kwargs=%s", args.run, kwargs)
        result = registry.run_module(args.run, **kwargs)
        logger.info("Module '%s' finished: %s", args.run, result.get("status", "unknown"))
        sys.exit(0 if result.get("status") != "failed" else 1)

    else:
        # Service mode: run the server in the foreground
        logger.info("Starting in service mode — FastAPI on %s:%d", config.hub_host, config.hub_port)
        uvicorn.run(app, host=config.hub_host, port=config.hub_port, log_level="info")


if __name__ == "__main__":
    main()
