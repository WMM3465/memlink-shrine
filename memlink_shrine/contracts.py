from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class WriteAdapterReceipt:
    adapter_id: str
    delivered: bool
    external_ref: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecallSelectionResult:
    delegate_id: str
    reasoning: str
    selected_raw_memory_ids: list[str]
    candidate_scope: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class MemlinkWriteAdapter(Protocol):
    adapter_id: str

    def is_enabled(self) -> bool:
        """Whether this adapter should receive write traffic in the current runtime."""

    def write_card(self, card: Any) -> tuple[Any, WriteAdapterReceipt | None]:
        """Project one Memlink card into an attached memory system."""


class MemlinkRecallDelegate(Protocol):
    delegate_id: str

    def is_enabled(self) -> bool:
        """Whether this delegate can serve recall requests in the current runtime."""

    def select_candidates(
        self,
        *,
        question: str,
        routing_limit: int,
    ) -> RecallSelectionResult:
        """Use the attached memory system's recall logic to return candidate card ids."""
