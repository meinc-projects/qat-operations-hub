import importlib
import pkgutil
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from src.core.logger import get_logger

logger = get_logger("hub.module_registry")


@dataclass
class HubContext:
    """Shared context passed to every module — provides access to all Hub services."""
    config: Any
    zoho_auth: Any
    claude_client: Any
    metrics: Any
    notifications: Any


class BaseModule(ABC):
    """Abstract base class that all Hub modules must implement."""

    def __init__(self, hub_context: HubContext) -> None:
        self.ctx = hub_context

    @abstractmethod
    def name(self) -> str:
        """Unique module identifier."""

    @abstractmethod
    def run(self, **kwargs: Any) -> dict:
        """Execute the module's primary function. Returns a summary dict."""

    @abstractmethod
    def get_status(self) -> dict:
        """Return current module status."""


class ModuleRegistry:
    """Discovers, registers and manages all Hub modules."""

    def __init__(self, hub_context: HubContext) -> None:
        self.ctx = hub_context
        self._modules: dict[str, BaseModule] = {}

    def discover_and_register(self) -> None:
        """Auto-discover modules under src.modules.* that expose a module.py
        containing a class derived from BaseModule."""
        import src.modules as modules_pkg

        for importer, modname, ispkg in pkgutil.iter_modules(modules_pkg.__path__):
            if not ispkg:
                continue
            fqn = f"src.modules.{modname}.module"
            try:
                mod = importlib.import_module(fqn)
            except Exception as exc:
                logger.error("Failed to import module '%s': %s", fqn, exc)
                continue

            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseModule)
                    and attr is not BaseModule
                ):
                    try:
                        instance = attr(self.ctx)
                        self._modules[instance.name()] = instance
                        logger.info("Registered module: %s", instance.name())
                    except Exception as exc:
                        logger.error("Failed to instantiate module '%s': %s", attr_name, exc)

    def register(self, module: BaseModule) -> None:
        self._modules[module.name()] = module
        logger.info("Registered module: %s", module.name())

    @property
    def registered_names(self) -> list[str]:
        return list(self._modules.keys())

    def run_module(self, name: str, **kwargs: Any) -> dict:
        """Run a module by name. Catches all exceptions so a crash never brings down the Hub."""
        if name not in self._modules:
            raise ValueError(f"Module '{name}' is not registered. Available: {self.registered_names}")
        module = self._modules[name]
        try:
            result = module.run(**kwargs)
            return result
        except Exception as exc:
            logger.error("Module '%s' crashed: %s\n%s", name, exc, traceback.format_exc())
            try:
                self.ctx.notifications.send_critical(name, exc)
            except Exception:
                logger.error("Additionally failed to send crash notification")
            return {"status": "failed", "error": str(exc)}

    def get_module_status(self, name: str) -> dict:
        if name not in self._modules:
            raise ValueError(f"Module '{name}' is not registered")
        return self._modules[name].get_status()

    def get_all_status(self) -> dict[str, dict]:
        result = {}
        for name, module in self._modules.items():
            try:
                result[name] = module.get_status()
            except Exception as exc:
                result[name] = {"status": "error", "error": str(exc)}
        return result
