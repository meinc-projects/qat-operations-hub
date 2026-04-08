import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_LOG_DIR: Path | None = None
_initialized = False


def setup_logging(log_level: str = "INFO", project_root: Path | None = None) -> None:
    """Configure the root 'hub' logger with file rotation and stdout output."""
    global _LOG_DIR, _initialized
    if _initialized:
        return

    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent.parent

    _LOG_DIR = project_root / "logs"
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_file = _LOG_DIR / "hub.log"
    level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger("hub")
    root_logger.setLevel(level)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    _initialized = True
    root_logger.info("Logging initialised — level=%s, file=%s", log_level.upper(), log_file)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'hub' namespace.

    Usage::

        logger = get_logger(__name__)   # e.g. hub.modules.renewal_backfill.module
    """
    if name.startswith("src."):
        name = name[len("src."):]
    if name.startswith("core."):
        name = "hub." + name[len("core."):]
    elif name.startswith("modules."):
        name = "hub." + name
    elif not name.startswith("hub"):
        name = f"hub.{name}"
    return logging.getLogger(name)
