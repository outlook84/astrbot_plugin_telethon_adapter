from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "TelethonProfileService",
    "TelethonPruneService",
    "TelethonDispatcherHost",
    "TelethonEventContext",
    "TelethonMessageDispatcher",
    "TelethonMessageExecutor",
    "TelethonRuntimeHost",
    "TelethonSender",
    "TelethonStickerService",
    "TelethonStatusService",
]

_EXPORTS = {
    "TelethonProfileService": (".profile_service", "TelethonProfileService"),
    "TelethonPruneService": (".prune_service", "TelethonPruneService"),
    "TelethonDispatcherHost": (".contracts", "TelethonDispatcherHost"),
    "TelethonEventContext": (".contracts", "TelethonEventContext"),
    "TelethonRuntimeHost": (".contracts", "TelethonRuntimeHost"),
    "TelethonMessageDispatcher": (".message_dispatcher", "TelethonMessageDispatcher"),
    "TelethonMessageExecutor": (".message_executor", "TelethonMessageExecutor"),
    "TelethonSender": (".sender", "TelethonSender"),
    "TelethonStickerService": (".sticker_service", "TelethonStickerService"),
    "TelethonStatusService": (".status_service", "TelethonStatusService"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
