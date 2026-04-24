from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .adapter_runtime import dispatch_card_to_write_adapters
from .config import load_settings
from .db import get_card_by_id, rebuild_chain_mirrors, upsert_card
from .id_schema import build_default_main_id
from .models import CatalogCard
from .source_rules import ensure_memory_source_metadata


TRUSTED_CHAIN_AUTHOR_ROLES = {"witness_model", "human"}
CHAIN_ROLE_DEFAULT_STATUS = {
    "assistant_suggestion": "suggested",
    "witness_model": "witness_confirmed",
    "human": "human_confirmed",
}


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    return [str(value).strip()] if str(value).strip() else []


def normalize_chain_author_role(value: str | None) -> str:
    role = str(value or "").strip()
    if role in {"assistant_suggestion", "witness_model", "human"}:
        return role
    return "assistant_suggestion"


def normalize_chain_status(role: str, value: str | None) -> str:
    text = str(value or "").strip()
    if text:
        return text
    return CHAIN_ROLE_DEFAULT_STATUS.get(role, "suggested")


def default_base_facets(base: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(base or {})
    data.setdefault("entity", [])
    data.setdefault("topic", [])
    data.setdefault("time", [])
    data.setdefault("status", [])
    data.setdefault("memory_type", "method")
    data.setdefault("memory_subtype", "")
    data.setdefault("relevance_scope_core", [])
    data.setdefault("relevance_scope_extra", [])
    return data


def default_governance(governance: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(governance or {})
    data.setdefault("shelf_state", "half_open")
    data.setdefault("importance", "normal")
    data.setdefault("pinned", False)
    data.setdefault("confidence", 0.6)
    data.setdefault("promotion_rule_text", "")
    data.setdefault("degradation_rule_text", "")
    data.setdefault("rationale", "")
    data.setdefault("promotion_signals", {})
    data.setdefault("degradation_signals", {})
    data.setdefault("reactivation_rule", {})
    return data


def create_direct_card(
    db_path: Path,
    payload: dict[str, Any],
    *,
    author_role: str | None = None,
    author: str | None = None,
) -> CatalogCard:
    """Write one card directly from the live assistant/witness channel.

    This is the Codex/Claude entry point. OpenMemory is not involved here:
    the caller is responsible for summarizing the current live context, and
    this function stores the resulting shadow card into Memlink Shrine.
    """

    base_facets = default_base_facets(payload.get("base_facets"))
    domain_facets = dict(payload.get("domain_facets") or {})
    governance = default_governance(payload.get("governance"))
    role = normalize_chain_author_role(author_role or payload.get("chain_author_role"))
    chain_status = normalize_chain_status(role, payload.get("chain_status"))
    raw_memory_created_at = CatalogCard.to_beijing_iso(payload.get("raw_memory_created_at")) or CatalogCard.now_iso()
    projection_created_at = CatalogCard.to_beijing_iso(payload.get("projection_created_at")) or CatalogCard.now_iso()
    raw_memory_id = str(payload.get("raw_memory_id") or f"assistant-{uuid.uuid4()}").strip()
    source_type = str(payload.get("source_type") or "assistant_direct").strip() or "assistant_direct"
    source_id = payload.get("source_id") or raw_memory_id
    inferred_pack = payload.get("facet_pack_id")
    if not inferred_pack and isinstance(domain_facets.get("enterprise"), dict) and domain_facets.get("enterprise"):
        inferred_pack = "enterprise"
    domain_facets = ensure_memory_source_metadata(
        domain_facets=domain_facets,
        source_type=source_type,
        source_id=str(source_id),
        author=author or payload.get("chain_author"),
        author_role=role,
        payload=payload,
    )

    if role in TRUSTED_CHAIN_AUTHOR_ROLES:
        main_id = str(payload.get("main_id") or "").strip() or build_default_main_id(
            raw_memory_id,
            raw_memory_created_at,
            subgraph=str(payload.get("subgraph") or "PEND"),
            position=str(payload.get("position") or "U00"),
            topology_role=str(payload.get("topology_role") or "node"),
            path_status=str(payload.get("path_status") or "active"),
            is_landmark=bool(payload.get("is_landmark")),
        )
        upstream_main_ids = as_list(payload.get("upstream_main_ids"))
        downstream_main_ids = as_list(payload.get("downstream_main_ids"))
        relation_type = str(payload.get("relation_type") or "unassigned").strip() or "unassigned"
        topology_role = str(payload.get("topology_role") or "node").strip() or "node"
        path_status = str(payload.get("path_status") or "active").strip() or "active"
        focus_anchor_main_id = str(payload.get("focus_anchor_main_id") or "").strip()
        focus_confidence = float(payload.get("focus_confidence") or 0.0)
        focus_reason = str(payload.get("focus_reason") or "").strip()
        is_landmark = bool(payload.get("is_landmark"))
        chain_confidence = float(payload.get("chain_confidence") or 0.0)
    else:
        main_id = build_default_main_id(
            raw_memory_id,
            raw_memory_created_at,
            subgraph="PEND",
            position="U00",
            topology_role="node",
            path_status="active",
            is_landmark=False,
        )
        upstream_main_ids = []
        downstream_main_ids = []
        relation_type = "unassigned"
        topology_role = "node"
        path_status = "active"
        focus_anchor_main_id = str(payload.get("focus_anchor_main_id") or "").strip()
        focus_confidence = float(payload.get("focus_confidence") or 0.0)
        focus_reason = str(payload.get("focus_reason") or "").strip()
        is_landmark = False
        chain_confidence = 0.0

    card = CatalogCard(
        raw_memory_id=raw_memory_id,
        title=str(payload.get("title") or "").strip(),
        fact_summary=str(payload.get("fact_summary") or "").strip(),
        meaning_summary=str(payload.get("meaning_summary") or "").strip(),
        posture_summary=str(payload.get("posture_summary") or "").strip(),
        emotion_trajectory=str(payload.get("emotion_trajectory") or "").strip(),
        body_text=str(payload.get("body_text") or "").strip(),
        raw_text=str(payload.get("raw_text") or "").strip(),
        base_facets=base_facets,
        domain_facets=domain_facets,
        governance=governance,
        semantic_facets={},
        main_id=main_id,
        upstream_main_ids=upstream_main_ids,
        downstream_main_ids=downstream_main_ids,
        relation_type=relation_type,
        topology_role=topology_role,
        path_status=path_status,
        focus_anchor_main_id=focus_anchor_main_id,
        focus_confidence=focus_confidence,
        focus_reason=focus_reason,
        is_landmark=is_landmark,
        chain_author=str(author or payload.get("chain_author") or role).strip() or role,
        chain_author_role=role,
        chain_status=chain_status,
        chain_confidence=chain_confidence,
        id_schema_id=str(payload.get("id_schema_id") or "memlink_shrine_default_v2"),
        source_id=str(source_id),
        source_type=source_type,
        owner=payload.get("owner"),
        visibility=str(payload.get("visibility") or "private"),
        confidence_source=str(payload.get("confidence_source") or "assistant_direct"),
        last_verified_at=payload.get("last_verified_at"),
        card_id=payload.get("card_id"),
        facet_pack_id=str(inferred_pack or ""),
        facet_pack_version=str(payload.get("facet_pack_version") or ("v1" if inferred_pack else "")),
        projection_status=str(payload.get("projection_status") or "active"),
        projection_created_at=projection_created_at,
        projection_based_on=str(payload.get("projection_based_on") or "assistant_direct"),
        raw_memory_created_at=raw_memory_created_at,
    )
    upsert_card(db_path, card)
    rebuild_chain_mirrors(db_path, raw_memory_id)
    created = get_card_by_id(db_path, raw_memory_id)
    if not created:
        raise RuntimeError("直写卡片失败")
    bridged = dispatch_card_to_write_adapters(created, load_settings())
    if bridged.semantic_facets != created.semantic_facets:
        upsert_card(db_path, bridged)
        rebuild_chain_mirrors(db_path, raw_memory_id)
        created = get_card_by_id(db_path, raw_memory_id) or bridged
    return created

