from __future__ import annotations

from .config import Settings
from .contracts import MemlinkWriteAdapter
from .models import CatalogCard
from .vcp_bridge import VcpBridgeWriteAdapter


def load_write_adapters(settings: Settings) -> list[MemlinkWriteAdapter]:
    adapters: list[MemlinkWriteAdapter] = []
    for adapter_name in settings.write_adapters:
        if adapter_name == "vcp_bridge":
            adapters.append(VcpBridgeWriteAdapter(settings))
    return [adapter for adapter in adapters if adapter.is_enabled()]


def dispatch_card_to_write_adapters(card: CatalogCard, settings: Settings) -> CatalogCard:
    current = card
    for adapter in load_write_adapters(settings):
        updated, _receipt = adapter.write_card(current)
        current = updated
    return current
