from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .id_schema import build_default_main_id
from .models import CatalogCard


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS catalog_cards (
    raw_memory_id TEXT PRIMARY KEY,
    card_id TEXT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    fact_summary TEXT NOT NULL DEFAULT '',
    meaning_summary TEXT NOT NULL DEFAULT '',
    posture_summary TEXT NOT NULL DEFAULT '',
    emotion_trajectory TEXT NOT NULL DEFAULT '',
    shelf_state TEXT NOT NULL DEFAULT 'half_open',
    importance TEXT NOT NULL DEFAULT 'normal',
    rationale TEXT NOT NULL DEFAULT '',
    pinned INTEGER NOT NULL DEFAULT 0,
    base_facets_json TEXT NOT NULL DEFAULT '{}',
    domain_facets_json TEXT NOT NULL DEFAULT '{}',
    governance_json TEXT NOT NULL DEFAULT '{}',
    body_text TEXT NOT NULL DEFAULT '',
    raw_text TEXT NOT NULL DEFAULT '',
    semantic_facets_json TEXT NOT NULL DEFAULT '{}',
    main_id TEXT NOT NULL DEFAULT '',
    upstream_main_ids_json TEXT NOT NULL DEFAULT '[]',
    downstream_main_ids_json TEXT NOT NULL DEFAULT '[]',
    relation_type TEXT NOT NULL DEFAULT 'derived_from',
    topology_role TEXT NOT NULL DEFAULT 'node',
    path_status TEXT NOT NULL DEFAULT 'active',
    focus_anchor_main_id TEXT NOT NULL DEFAULT '',
    focus_confidence REAL NOT NULL DEFAULT 0,
    focus_reason TEXT NOT NULL DEFAULT '',
    is_landmark INTEGER NOT NULL DEFAULT 0,
    chain_author TEXT NOT NULL DEFAULT '',
    chain_author_role TEXT NOT NULL DEFAULT 'none',
    chain_status TEXT NOT NULL DEFAULT 'unassigned',
    chain_confidence REAL NOT NULL DEFAULT 0,
    id_schema_id TEXT NOT NULL DEFAULT 'memlink_shrine_default_v2',
    source_id TEXT,
    source_type TEXT NOT NULL DEFAULT 'openmemory',
    owner TEXT,
    visibility TEXT NOT NULL DEFAULT 'private',
    confidence_source TEXT NOT NULL DEFAULT 'ai_generated',
    last_verified_at TEXT,
    first_activated_at TEXT,
    last_activated_at TEXT,
    activation_count INTEGER NOT NULL DEFAULT 0,
    facet_pack_id TEXT NOT NULL DEFAULT 'enterprise',
    facet_pack_version TEXT NOT NULL DEFAULT 'v1',
    projection_status TEXT NOT NULL DEFAULT 'active',
    projection_created_at TEXT,
    projection_based_on TEXT,
    raw_memory_created_at TEXT,
    last_accessed_at TEXT,
    last_reinforced_at TEXT,
    created_at TEXT,
    updated_at TEXT
);
"""


EXPECTED_COLUMNS: dict[str, str] = {
    "card_id": "TEXT",
    "fact_summary": "TEXT NOT NULL DEFAULT ''",
    "meaning_summary": "TEXT NOT NULL DEFAULT ''",
    "posture_summary": "TEXT NOT NULL DEFAULT ''",
    "emotion_trajectory": "TEXT NOT NULL DEFAULT ''",
    "shelf_state": "TEXT NOT NULL DEFAULT 'half_open'",
    "importance": "TEXT NOT NULL DEFAULT 'normal'",
    "rationale": "TEXT NOT NULL DEFAULT ''",
    "pinned": "INTEGER NOT NULL DEFAULT 0",
    "base_facets_json": "TEXT NOT NULL DEFAULT '{}'",
    "domain_facets_json": "TEXT NOT NULL DEFAULT '{}'",
    "governance_json": "TEXT NOT NULL DEFAULT '{}'",
    "body_text": "TEXT NOT NULL DEFAULT ''",
    "raw_text": "TEXT NOT NULL DEFAULT ''",
    "semantic_facets_json": "TEXT NOT NULL DEFAULT '{}'",
    "main_id": "TEXT NOT NULL DEFAULT ''",
    "upstream_main_ids_json": "TEXT NOT NULL DEFAULT '[]'",
    "downstream_main_ids_json": "TEXT NOT NULL DEFAULT '[]'",
    "relation_type": "TEXT NOT NULL DEFAULT 'derived_from'",
    "topology_role": "TEXT NOT NULL DEFAULT 'node'",
    "path_status": "TEXT NOT NULL DEFAULT 'active'",
    "focus_anchor_main_id": "TEXT NOT NULL DEFAULT ''",
    "focus_confidence": "REAL NOT NULL DEFAULT 0",
    "focus_reason": "TEXT NOT NULL DEFAULT ''",
    "is_landmark": "INTEGER NOT NULL DEFAULT 0",
    "chain_author": "TEXT NOT NULL DEFAULT ''",
    "chain_author_role": "TEXT NOT NULL DEFAULT 'none'",
    "chain_status": "TEXT NOT NULL DEFAULT 'unassigned'",
    "chain_confidence": "REAL NOT NULL DEFAULT 0",
    "id_schema_id": "TEXT NOT NULL DEFAULT 'memlink_shrine_default_v2'",
    "source_id": "TEXT",
    "source_type": "TEXT NOT NULL DEFAULT 'openmemory'",
    "owner": "TEXT",
    "visibility": "TEXT NOT NULL DEFAULT 'private'",
    "confidence_source": "TEXT NOT NULL DEFAULT 'ai_generated'",
    "last_verified_at": "TEXT",
    "first_activated_at": "TEXT",
    "last_activated_at": "TEXT",
    "activation_count": "INTEGER NOT NULL DEFAULT 0",
    "facet_pack_id": "TEXT NOT NULL DEFAULT 'enterprise'",
    "facet_pack_version": "TEXT NOT NULL DEFAULT 'v1'",
    "projection_status": "TEXT NOT NULL DEFAULT 'active'",
    "projection_created_at": "TEXT",
    "projection_based_on": "TEXT",
    "raw_memory_created_at": "TEXT",
    "last_accessed_at": "TEXT",
    "last_reinforced_at": "TEXT",
}


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(CREATE_TABLE_SQL)
        _ensure_expected_columns(conn)
        _backfill_v2_fields(conn)
        conn.commit()


def _ensure_expected_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(catalog_cards)")
    }
    for column_name, column_def in EXPECTED_COLUMNS.items():
        if column_name not in existing:
            conn.execute(
                f"ALTER TABLE catalog_cards ADD COLUMN {column_name} {column_def}"
            )


def _backfill_v2_fields(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT
            raw_memory_id,
            raw_memory_created_at,
            main_id,
            body_text,
            fact_summary,
            meaning_summary,
            domain_facets_json,
            topology_role,
            path_status,
            is_landmark
        FROM catalog_cards
        WHERE main_id = '' OR body_text = '' OR semantic_facets_json = '{}'
        """
    ).fetchall()
    for row in rows:
        main_id = row["main_id"] or build_default_main_id(
            row["raw_memory_id"],
            row["raw_memory_created_at"],
            topology_role=row["topology_role"] or "node",
            path_status=row["path_status"] or "active",
            is_landmark=bool(row["is_landmark"]),
        )
        body_text = row["body_text"] or row["fact_summary"] or row["meaning_summary"] or ""
        semantic_facets = _loads_json(row["domain_facets_json"]).get("enterprise", {})
        conn.execute(
            """
            UPDATE catalog_cards
            SET
                main_id = ?,
                body_text = ?,
                semantic_facets_json = ?
            WHERE raw_memory_id = ?
            """,
            (
                main_id,
                body_text,
                json.dumps(semantic_facets, ensure_ascii=False),
                row["raw_memory_id"],
            ),
        )


def _loads_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _loads_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if isinstance(loaded, list):
        return [str(item) for item in loaded if str(item).strip()]
    return []


def row_to_card(row: sqlite3.Row) -> CatalogCard:
    governance = _loads_json(row["governance_json"])
    governance.setdefault("shelf_state", row["shelf_state"] or "half_open")
    governance.setdefault("importance", row["importance"] or "normal")
    governance.setdefault("pinned", bool(row["pinned"]))
    governance.setdefault("rationale", row["rationale"] or "")
    if row["last_accessed_at"]:
        governance.setdefault("last_accessed_at", row["last_accessed_at"])
    if row["last_reinforced_at"]:
        governance.setdefault("last_reinforced_at", row["last_reinforced_at"])

    return CatalogCard(
        raw_memory_id=row["raw_memory_id"],
        title=row["title"],
        fact_summary=row["fact_summary"] or row["summary"] or "",
        meaning_summary=row["meaning_summary"] or row["summary"] or "",
        posture_summary=row["posture_summary"] or "",
        emotion_trajectory=row["emotion_trajectory"] or "",
        base_facets=_loads_json(row["base_facets_json"]),
        domain_facets=_loads_json(row["domain_facets_json"]),
        governance=governance,
        body_text=row["body_text"] or "",
        raw_text=row["raw_text"] or "",
        semantic_facets=_loads_json(row["semantic_facets_json"]),
        main_id=row["main_id"] or "",
        upstream_main_ids=_loads_list(row["upstream_main_ids_json"]),
        downstream_main_ids=_loads_list(row["downstream_main_ids_json"]),
        relation_type=row["relation_type"] or "derived_from",
        topology_role=row["topology_role"] or "node",
        path_status=row["path_status"] or "active",
        focus_anchor_main_id=row["focus_anchor_main_id"] or "",
        focus_confidence=float(row["focus_confidence"] or 0.0),
        focus_reason=row["focus_reason"] or "",
        is_landmark=bool(row["is_landmark"]),
        chain_author=row["chain_author"] or "",
        chain_author_role=row["chain_author_role"] or "none",
        chain_status=row["chain_status"] or "unassigned",
        chain_confidence=float(row["chain_confidence"] or 0.0),
        id_schema_id=row["id_schema_id"] or "memlink_shrine_default_v2",
        source_id=row["source_id"],
        source_type=row["source_type"] or "openmemory",
        owner=row["owner"],
        visibility=row["visibility"] or "private",
        confidence_source=row["confidence_source"] or "ai_generated",
        last_verified_at=row["last_verified_at"],
        first_activated_at=row["first_activated_at"],
        last_activated_at=row["last_activated_at"],
        activation_count=int(row["activation_count"] or 0),
        card_id=row["card_id"],
        facet_pack_id=row["facet_pack_id"] or "enterprise",
        facet_pack_version=row["facet_pack_version"] or "v1",
        projection_status=row["projection_status"] or "active",
        projection_created_at=row["projection_created_at"],
        projection_based_on=row["projection_based_on"],
        raw_memory_created_at=row["raw_memory_created_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def upsert_card(db_path: Path, card: CatalogCard) -> None:
    now = CatalogCard.now_iso()
    created_at = card.created_at or now
    updated_at = now
    governance = dict(card.governance)

    if card.last_accessed_at:
        governance["last_accessed_at"] = card.last_accessed_at
    if card.last_reinforced_at:
        governance["last_reinforced_at"] = card.last_reinforced_at

    record = {
        "raw_memory_id": card.raw_memory_id,
        "card_id": card.card_id,
        "title": card.title,
        "summary": card.summary,
        "fact_summary": card.fact_summary,
        "meaning_summary": card.meaning_summary,
        "posture_summary": card.posture_summary,
        "emotion_trajectory": card.emotion_trajectory,
        "shelf_state": card.shelf_state,
        "importance": card.importance,
        "rationale": governance.get("rationale", ""),
        "pinned": 1 if card.pinned else 0,
        "base_facets_json": json.dumps(card.base_facets, ensure_ascii=False),
        "domain_facets_json": json.dumps(card.domain_facets, ensure_ascii=False),
        "governance_json": json.dumps(governance, ensure_ascii=False),
        "body_text": card.body_text,
        "raw_text": card.raw_text,
        "semantic_facets_json": json.dumps(card.semantic_facets, ensure_ascii=False),
        "main_id": card.main_id,
        "upstream_main_ids_json": json.dumps(card.upstream_main_ids, ensure_ascii=False),
        "downstream_main_ids_json": json.dumps(card.downstream_main_ids, ensure_ascii=False),
        "relation_type": card.relation_type,
        "topology_role": card.topology_role,
        "path_status": card.path_status,
        "focus_anchor_main_id": card.focus_anchor_main_id,
        "focus_confidence": card.focus_confidence,
        "focus_reason": card.focus_reason,
        "is_landmark": 1 if card.is_landmark else 0,
        "chain_author": card.chain_author,
        "chain_author_role": card.chain_author_role,
        "chain_status": card.chain_status,
        "chain_confidence": card.chain_confidence,
        "id_schema_id": card.id_schema_id,
        "source_id": card.source_id,
        "source_type": card.source_type,
        "owner": card.owner,
        "visibility": card.visibility,
        "confidence_source": card.confidence_source,
        "last_verified_at": card.last_verified_at,
        "first_activated_at": card.first_activated_at,
        "last_activated_at": card.last_activated_at,
        "activation_count": card.activation_count,
        "facet_pack_id": card.facet_pack_id,
        "facet_pack_version": card.facet_pack_version,
        "projection_status": card.projection_status,
        "projection_created_at": card.projection_created_at or now,
        "projection_based_on": card.projection_based_on,
        "raw_memory_created_at": card.raw_memory_created_at,
        "last_accessed_at": governance.get("last_accessed_at"),
        "last_reinforced_at": governance.get("last_reinforced_at"),
        "created_at": created_at,
        "updated_at": updated_at,
    }
    columns = list(record)
    placeholders = ", ".join("?" for _ in columns)
    updates = ",\n                ".join(
        f"{column} = excluded.{column}"
        for column in columns
        if column not in {"raw_memory_id", "created_at"}
    )
    updates = updates.replace(
        "last_accessed_at = excluded.last_accessed_at",
        "last_accessed_at = COALESCE(excluded.last_accessed_at, catalog_cards.last_accessed_at)",
    ).replace(
        "last_reinforced_at = excluded.last_reinforced_at",
        "last_reinforced_at = COALESCE(excluded.last_reinforced_at, catalog_cards.last_reinforced_at)",
    ).replace(
        "first_activated_at = excluded.first_activated_at",
        "first_activated_at = COALESCE(catalog_cards.first_activated_at, excluded.first_activated_at)",
    )

    with connect(db_path) as conn:
        conn.execute(
            f"""
            INSERT INTO catalog_cards ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(raw_memory_id) DO UPDATE SET
                {updates}
            """,
            tuple(record[column] for column in columns),
        )
        conn.commit()


def _normalize_main_id_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    clean: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        clean.append(text)
    return clean


def rebuild_chain_mirrors(db_path: Path, raw_memory_id: str, previous_main_id: str | None = None) -> None:
    target = get_card_by_id(db_path, raw_memory_id)
    if not target or not target.main_id:
        return

    current_main_id = target.main_id.strip()
    old_main_id = str(previous_main_id or "").strip()
    target_upstreams = _normalize_main_id_list(target.upstream_main_ids)
    collected_downstreams: list[str] = []
    now = CatalogCard.now_iso()

    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT raw_memory_id, main_id, upstream_main_ids_json, downstream_main_ids_json
            FROM catalog_cards
            """
        ).fetchall()

        for row in rows:
            other_raw_id = row["raw_memory_id"]
            if other_raw_id == raw_memory_id:
                continue

            other_main_id = str(row["main_id"] or "").strip()
            upstream_ids = _normalize_main_id_list(json.loads(row["upstream_main_ids_json"] or "[]"))
            downstream_ids = _normalize_main_id_list(json.loads(row["downstream_main_ids_json"] or "[]"))
            original_upstreams = list(upstream_ids)
            original_downstreams = list(downstream_ids)

            if old_main_id and old_main_id != current_main_id:
                upstream_ids = [current_main_id if item == old_main_id else item for item in upstream_ids]
                downstream_ids = [current_main_id if item == old_main_id else item for item in downstream_ids]

            if other_main_id and other_main_id in target_upstreams:
                if current_main_id not in downstream_ids:
                    downstream_ids.append(current_main_id)
            else:
                downstream_ids = [item for item in downstream_ids if item != current_main_id]

            upstream_ids = _normalize_main_id_list(upstream_ids)
            downstream_ids = _normalize_main_id_list(downstream_ids)

            if current_main_id in upstream_ids and other_main_id:
                collected_downstreams.append(other_main_id)

            if upstream_ids != original_upstreams or downstream_ids != original_downstreams:
                conn.execute(
                    """
                    UPDATE catalog_cards
                    SET upstream_main_ids_json = ?, downstream_main_ids_json = ?, updated_at = ?
                    WHERE raw_memory_id = ?
                    """,
                    (
                        json.dumps(upstream_ids, ensure_ascii=False),
                        json.dumps(downstream_ids, ensure_ascii=False),
                        now,
                        other_raw_id,
                    ),
                )

        normalized_target_downstreams = _normalize_main_id_list(collected_downstreams)
        if normalized_target_downstreams != _normalize_main_id_list(target.downstream_main_ids):
            conn.execute(
                """
                UPDATE catalog_cards
                SET downstream_main_ids_json = ?, updated_at = ?
                WHERE raw_memory_id = ?
                """,
                (
                    json.dumps(normalized_target_downstreams, ensure_ascii=False),
                    now,
                    raw_memory_id,
                ),
            )
        conn.commit()


def list_cards(db_path: Path, limit: int = 20) -> list[CatalogCard]:
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            SELECT *
            FROM catalog_cards
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [row_to_card(row) for row in cur.fetchall()]


def list_all_cards(db_path: Path) -> list[CatalogCard]:
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            SELECT *
            FROM catalog_cards
            ORDER BY updated_at DESC, created_at DESC
            """
        )
        return [row_to_card(row) for row in cur.fetchall()]


def list_cards_for_routing(db_path: Path, limit: int = 120) -> list[CatalogCard]:
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            SELECT *
            FROM catalog_cards
            ORDER BY
                CASE importance
                    WHEN 'pinned' THEN 4
                    WHEN 'high' THEN 3
                    WHEN 'normal' THEN 2
                    ELSE 1
                END DESC,
                COALESCE(last_activated_at, last_accessed_at, updated_at) DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [row_to_card(row) for row in cur.fetchall()]


def search_cards(db_path: Path, query: str = "", limit: int = 50) -> list[CatalogCard]:
    with connect(db_path) as conn:
        if query.strip():
            like = f"%{query.strip()}%"
            cur = conn.execute(
                """
                SELECT *
                FROM catalog_cards
                WHERE
                    title LIKE ?
                    OR summary LIKE ?
                    OR fact_summary LIKE ?
                    OR meaning_summary LIKE ?
                    OR posture_summary LIKE ?
                    OR emotion_trajectory LIKE ?
                    OR body_text LIKE ?
                    OR main_id LIKE ?
                    OR upstream_main_ids_json LIKE ?
                    OR downstream_main_ids_json LIKE ?
                    OR semantic_facets_json LIKE ?
                    OR base_facets_json LIKE ?
                    OR domain_facets_json LIKE ?
                    OR governance_json LIKE ?
                    OR focus_anchor_main_id LIKE ?
                    OR focus_reason LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (like, like, like, like, like, like, like, like, like, like, like, like, like, like, like, like, limit),
            )
        else:
            cur = conn.execute(
                """
                SELECT *
                FROM catalog_cards
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        return [row_to_card(row) for row in cur.fetchall()]


def get_card_by_id(db_path: Path, raw_memory_id: str) -> CatalogCard | None:
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM catalog_cards WHERE raw_memory_id = ?",
            (raw_memory_id,),
        )
        row = cur.fetchone()
    return row_to_card(row) if row else None


def update_card(
    db_path: Path,
    raw_memory_id: str,
    updates: dict[str, Any],
) -> CatalogCard:
    existing = get_card_by_id(db_path, raw_memory_id)
    if not existing:
        raise KeyError(f"Card not found: {raw_memory_id}")

    def keep_existing_if_none(key: str, current: Any) -> Any:
        value = updates.get(key)
        return current if value is None else value

    previous_main_id = existing.main_id
    merged = CatalogCard(
        raw_memory_id=existing.raw_memory_id,
        title=keep_existing_if_none("title", existing.title),
        fact_summary=keep_existing_if_none("fact_summary", existing.fact_summary),
        meaning_summary=keep_existing_if_none("meaning_summary", existing.meaning_summary),
        posture_summary=keep_existing_if_none("posture_summary", existing.posture_summary),
        emotion_trajectory=keep_existing_if_none("emotion_trajectory", existing.emotion_trajectory),
        base_facets=keep_existing_if_none("base_facets", existing.base_facets),
        domain_facets=keep_existing_if_none("domain_facets", existing.domain_facets),
        governance=keep_existing_if_none("governance", existing.governance),
        body_text=keep_existing_if_none("body_text", existing.body_text),
        raw_text=keep_existing_if_none("raw_text", existing.raw_text),
        semantic_facets=keep_existing_if_none("semantic_facets", existing.semantic_facets),
        main_id=keep_existing_if_none("main_id", existing.main_id),
        upstream_main_ids=keep_existing_if_none("upstream_main_ids", existing.upstream_main_ids),
        downstream_main_ids=keep_existing_if_none("downstream_main_ids", existing.downstream_main_ids),
        relation_type=keep_existing_if_none("relation_type", existing.relation_type),
        topology_role=keep_existing_if_none("topology_role", existing.topology_role),
        path_status=keep_existing_if_none("path_status", existing.path_status),
        focus_anchor_main_id=keep_existing_if_none("focus_anchor_main_id", existing.focus_anchor_main_id),
        focus_confidence=keep_existing_if_none("focus_confidence", existing.focus_confidence),
        focus_reason=keep_existing_if_none("focus_reason", existing.focus_reason),
        is_landmark=keep_existing_if_none("is_landmark", existing.is_landmark),
        chain_author=keep_existing_if_none("chain_author", existing.chain_author),
        chain_author_role=keep_existing_if_none("chain_author_role", existing.chain_author_role),
        chain_status=keep_existing_if_none("chain_status", existing.chain_status),
        chain_confidence=keep_existing_if_none("chain_confidence", existing.chain_confidence),
        id_schema_id=keep_existing_if_none("id_schema_id", existing.id_schema_id),
        source_id=keep_existing_if_none("source_id", existing.source_id),
        source_type=keep_existing_if_none("source_type", existing.source_type),
        owner=keep_existing_if_none("owner", existing.owner),
        visibility=keep_existing_if_none("visibility", existing.visibility),
        confidence_source=keep_existing_if_none("confidence_source", existing.confidence_source),
        last_verified_at=keep_existing_if_none("last_verified_at", existing.last_verified_at),
        first_activated_at=keep_existing_if_none("first_activated_at", existing.first_activated_at),
        last_activated_at=keep_existing_if_none("last_activated_at", existing.last_activated_at),
        activation_count=keep_existing_if_none("activation_count", existing.activation_count),
        card_id=keep_existing_if_none("card_id", existing.card_id),
        facet_pack_id=keep_existing_if_none("facet_pack_id", existing.facet_pack_id),
        facet_pack_version=keep_existing_if_none("facet_pack_version", existing.facet_pack_version),
        projection_status=keep_existing_if_none("projection_status", existing.projection_status),
        projection_created_at=keep_existing_if_none("projection_created_at", existing.projection_created_at),
        projection_based_on=keep_existing_if_none("projection_based_on", existing.projection_based_on),
        raw_memory_created_at=keep_existing_if_none("raw_memory_created_at", existing.raw_memory_created_at),
        created_at=existing.created_at,
        updated_at=CatalogCard.now_iso(),
    )
    upsert_card(db_path, merged)
    rebuild_chain_mirrors(db_path, raw_memory_id, previous_main_id=previous_main_id)
    refreshed = get_card_by_id(db_path, raw_memory_id)
    if not refreshed:
        raise RuntimeError(f"Card update failed: {raw_memory_id}")
    return refreshed


def get_cards_by_ids(db_path: Path, raw_memory_ids: list[str]) -> list[CatalogCard]:
    if not raw_memory_ids:
        return []
    placeholders = ",".join("?" for _ in raw_memory_ids)
    with connect(db_path) as conn:
        cur = conn.execute(
            f"SELECT * FROM catalog_cards WHERE raw_memory_id IN ({placeholders})",
            tuple(raw_memory_ids),
        )
        rows = [row_to_card(row) for row in cur.fetchall()]
    index = {row.raw_memory_id: row for row in rows}
    return [index[memory_id] for memory_id in raw_memory_ids if memory_id in index]


def get_card_by_main_id(db_path: Path, main_id: str) -> CatalogCard | None:
    if not main_id:
        return None
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM catalog_cards WHERE main_id = ?",
            (main_id,),
        )
        row = cur.fetchone()
    return row_to_card(row) if row else None


def get_cards_by_main_ids(db_path: Path, main_ids: list[str]) -> list[CatalogCard]:
    clean_ids = [main_id for main_id in main_ids if main_id]
    if not clean_ids:
        return []
    placeholders = ",".join("?" for _ in clean_ids)
    with connect(db_path) as conn:
        cur = conn.execute(
            f"SELECT * FROM catalog_cards WHERE main_id IN ({placeholders})",
            tuple(clean_ids),
        )
        rows = [row_to_card(row) for row in cur.fetchall()]
    index = {row.main_id: row for row in rows}
    return [index[main_id] for main_id in clean_ids if main_id in index]


def touch_cards_access(db_path: Path, raw_memory_ids: list[str]) -> None:
    if not raw_memory_ids:
        return
    placeholders = ",".join("?" for _ in raw_memory_ids)
    now = CatalogCard.now_iso()
    with connect(db_path) as conn:
        conn.execute(
            f"""
            UPDATE catalog_cards
            SET
                last_accessed_at = ?,
                first_activated_at = COALESCE(first_activated_at, ?),
                last_activated_at = ?,
                activation_count = activation_count + 1,
                updated_at = ?
            WHERE raw_memory_id IN ({placeholders})
            """,
            (now, now, now, now, *raw_memory_ids),
        )
        conn.commit()


def list_cards_by_project(db_path: Path, project_name: str) -> list[CatalogCard]:
    if not project_name:
        return []
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            SELECT *
            FROM catalog_cards
            WHERE domain_facets_json LIKE ?
            ORDER BY updated_at DESC, created_at DESC
            """,
            (f"%{project_name}%",),
        )
        rows = [row_to_card(row) for row in cur.fetchall()]
    filtered: list[CatalogCard] = []
    for card in rows:
        enterprise = card.domain_facets.get("enterprise", {})
        projects = enterprise.get("项目", [])
        if isinstance(projects, list) and project_name in [str(item) for item in projects]:
            filtered.append(card)
    return filtered


def sanitize_untrusted_chains(db_path: Path) -> int:
    """Remove untrusted chain decisions without deleting memory content.

    Chain fields are only trusted when they were written by a witness model or
    explicitly confirmed by a human. External cataloging models may summarize
    and tag, but they do not have authority to decide upstream/downstream links.
    """
    now = CatalogCard.now_iso()
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT raw_memory_id, raw_memory_created_at
            FROM catalog_cards
            WHERE COALESCE(chain_author_role, 'none') NOT IN ('witness_model', 'human')
               OR COALESCE(chain_status, 'unassigned') NOT IN ('witness_confirmed', 'human_confirmed')
            """
        ).fetchall()
        for row in rows:
            main_id = build_default_main_id(
                row["raw_memory_id"],
                row["raw_memory_created_at"],
                subgraph="PEND",
                position="U00",
                topology_role="node",
                path_status="active",
                is_landmark=False,
            )
            conn.execute(
                """
                UPDATE catalog_cards
                SET
                    main_id = ?,
                    upstream_main_ids_json = '[]',
                    downstream_main_ids_json = '[]',
                    relation_type = 'unassigned',
                    topology_role = 'node',
                    path_status = 'active',
                    focus_anchor_main_id = '',
                    focus_confidence = 0,
                    focus_reason = '',
                    is_landmark = 0,
                    chain_author = '',
                    chain_author_role = 'none',
                    chain_status = 'unassigned',
                    chain_confidence = 0,
                    updated_at = ?
                WHERE raw_memory_id = ?
                """,
                (main_id, now, row["raw_memory_id"]),
            )
        conn.commit()
        return len(rows)


