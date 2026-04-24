from __future__ import annotations

import os
import re
from typing import Any


DEFAULT_PARALLEL_RULE = "append_only_branching"


def resolve_memlink_host() -> str:
    value = str(os.getenv("MEMLINK_SHRINE_HOST_ID") or "default").strip().lower()
    normalized = re.sub(r"[^a-z0-9._-]+", "-", value).strip(".-_")
    return normalized or "default"


def infer_frontend_name(*, source_type: str, author: str | None, payload: dict[str, Any] | None = None) -> str:
    source = str(source_type or "").strip().lower()
    author_text = str(author or "").strip().lower()
    chain_author = str((payload or {}).get("chain_author") or "").strip().lower()
    combined = " ".join([source, author_text, chain_author])
    if "claude" in combined or re.search(r"\bcc\b", combined):
        return "claude_code"
    if "hermes" in combined:
        return "hermes"
    if "openclaw" in combined:
        return "openclaw"
    if "codex" in combined or "assistant_direct" in combined:
        return "codex"
    return "unknown_frontend"


def infer_write_mode(source_type: str, payload: dict[str, Any] | None = None) -> str:
    source = str(source_type or "").strip().lower()
    explicit = str((payload or {}).get("write_mode") or "").strip().lower()
    if explicit in {"manual", "passive", "auto"}:
        return explicit
    if "_passive" in source:
        return "passive"
    if "_auto" in source:
        return "auto"
    if "_manual" in source:
        return "manual"
    return "manual"


def ensure_memory_source_metadata(
    *,
    domain_facets: dict[str, Any] | None,
    source_type: str,
    source_id: str,
    author: str | None,
    author_role: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    facets = dict(domain_facets or {})
    source_meta = dict(facets.get("memory_source") or {})
    codex_session = dict(facets.get("codex_session") or {})

    source_meta.setdefault(
        "frontend",
        infer_frontend_name(source_type=source_type, author=author, payload=payload),
    )
    source_meta.setdefault("host", resolve_memlink_host())
    source_meta.setdefault(
        "thread",
        str(source_meta.get("thread") or codex_session.get("thread_name") or (payload or {}).get("thread_name") or "").strip(),
    )
    source_meta.setdefault(
        "session",
        str(source_meta.get("session") or codex_session.get("session_id") or source_id or "").strip(),
    )
    source_meta.setdefault("write_mode", infer_write_mode(source_type, payload))
    source_meta.setdefault("source_role", str(source_meta.get("source_role") or author_role or "unknown").strip())
    source_meta.setdefault("parallel_rule", DEFAULT_PARALLEL_RULE)
    source_meta.setdefault("relation_note", "")

    facets["memory_source"] = source_meta
    return facets
