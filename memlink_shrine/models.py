from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal


ShelfState = Literal["open", "half_open", "closed"]
Importance = Literal["pinned", "high", "normal", "low"]
TopologyRole = Literal["origin", "junction", "node", "merge", "exit"]
PathStatus = Literal["active", "dead_end", "superseded", "open_head", "paused"]
BEIJING_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")


@dataclass
class RawMemory:
    id: str
    user_id: str
    app_name: str | None
    content: str
    created_at: str | None
    metadata: dict[str, Any] | None


@dataclass
class CatalogCard:
    raw_memory_id: str
    title: str
    fact_summary: str
    meaning_summary: str
    base_facets: dict[str, Any]
    domain_facets: dict[str, Any]
    governance: dict[str, Any]
    posture_summary: str = ""
    emotion_trajectory: str = ""
    body_text: str = ""
    raw_text: str = ""
    semantic_facets: dict[str, Any] = field(default_factory=dict)
    main_id: str = ""
    upstream_main_ids: list[str] = field(default_factory=list)
    downstream_main_ids: list[str] = field(default_factory=list)
    relation_type: str = "derived_from"
    topology_role: TopologyRole = "node"
    path_status: PathStatus = "active"
    focus_anchor_main_id: str = ""
    focus_confidence: float = 0.0
    focus_reason: str = ""
    is_landmark: bool = False
    chain_author: str = ""
    chain_author_role: str = "none"
    chain_status: str = "unassigned"
    chain_confidence: float = 0.0
    id_schema_id: str = "memlink_shrine_default_v2"
    source_id: str | None = None
    source_type: str = "openmemory"
    owner: str | None = None
    visibility: str = "private"
    confidence_source: str = "ai_generated"
    last_verified_at: str | None = None
    first_activated_at: str | None = None
    last_activated_at: str | None = None
    activation_count: int = 0
    card_id: str | None = None
    facet_pack_id: str = "enterprise"
    facet_pack_version: str = "v1"
    projection_status: str = "active"
    projection_created_at: str | None = None
    projection_based_on: str | None = None
    raw_memory_created_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @staticmethod
    def now_iso() -> str:
        # Memlink Shrine is for the user's China work context. Do not use the
        # computer's local timezone, because the OS may be set to Pacific time
        # for overseas network routing; system-owned event records use Beijing time.
        return datetime.now(BEIJING_TIMEZONE).isoformat(timespec="seconds")

    @staticmethod
    def to_beijing_iso(value: str | None) -> str | None:
        if not value:
            return value
        try:
            text = value.strip().replace("Z", "+00:00")
            if text.replace(".", "", 1).isdigit():
                timestamp = float(text)
                if timestamp > 10_000_000_000:
                    timestamp = timestamp / 1000
                parsed = datetime.fromtimestamp(timestamp, timezone.utc)
            else:
                parsed = datetime.fromisoformat(text)
        except ValueError:
            return value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=BEIJING_TIMEZONE)
        return parsed.astimezone(BEIJING_TIMEZONE).isoformat(timespec="seconds")

    @property
    def shelf_state(self) -> ShelfState:
        return self.governance.get("shelf_state", "half_open")

    @property
    def importance(self) -> Importance:
        return self.governance.get("importance", "normal")

    @property
    def pinned(self) -> bool:
        return bool(self.governance.get("pinned", False))

    @property
    def confidence(self) -> float:
        try:
            return float(self.governance.get("confidence", 0.0))
        except (TypeError, ValueError):
            return 0.0

    @property
    def tags(self) -> dict[str, list[str]]:
        return {
            "entity": list(self.base_facets.get("entity", [])),
            "topic": list(self.base_facets.get("topic", [])),
            "time": list(self.base_facets.get("time", [])),
            "status": list(self.base_facets.get("status", [])),
        }

    @property
    def summary(self) -> str:
        return self.meaning_summary

    @property
    def display_main_id(self) -> str:
        return self.main_id or self.card_id or self.raw_memory_id

    @property
    def last_accessed_at(self) -> str | None:
        return self.governance.get("last_accessed_at")

    @property
    def last_reinforced_at(self) -> str | None:
        return self.governance.get("last_reinforced_at")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QuerySelection:
    question: str
    reasoning: str
    selected_raw_memory_ids: list[str]
    selected_titles: list[str] = field(default_factory=list)
    candidate_scope: str | None = None


@dataclass
class MemoryBrief:
    question: str
    brief: str
    relevance_reason: str
    applied_raw_memory_ids: list[str]
    applied_titles: list[str]
    confidence: float
    evidence_snippets: list[str] = field(default_factory=list)
    routing_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

