from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

class PluginKind(str, Enum):
    INDICATOR="INDICATOR"; STRATEGY="STRATEGY"; FILTER="FILTER"; MARKET_REGIME="MARKET_REGIME"; RISK_RULE="RISK_RULE"

@runtime_checkable
class Plugin(Protocol):
    name: str
    version: str
    kind: PluginKind

@dataclass(frozen=True)
class PluginDescriptor:
    name: str
    version: str
    kind: PluginKind

class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[tuple[PluginKind, str], Plugin] = {}
    def register(self, plugin: Plugin) -> None:
        if not isinstance(plugin, Plugin):
            raise TypeError("plugin does not satisfy protocol")
        key=(plugin.kind, plugin.name)
        if key in self._plugins:
            raise ValueError("plugin already registered")
        self._plugins[key]=plugin
    def get(self, kind: PluginKind, name: str) -> Plugin:
        return self._plugins[(kind,name)]
    def descriptors(self) -> tuple[PluginDescriptor,...]:
        return tuple(sorted((PluginDescriptor(p.name,p.version,p.kind) for p in self._plugins.values()), key=lambda x:(x.kind.value,x.name)))
