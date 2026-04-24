from __future__ import annotations

import hashlib
import re
from datetime import datetime

from .models import BEIJING_TIMEZONE, CatalogCard


DEFAULT_ID_SCHEMA_ID = "memlink_shrine_default_v2"


ROLE_CODES = {
    "origin": "RT",
    "junction": "BR",
    "node": "MN",
    "merge": "IN",
    "exit": "EX",
}


def compact_date(value: str | None) -> str:
    if not value:
        return CatalogCard.now_iso()[:10].replace("-", "")
    try:
        text = value.strip().replace("Z", "+00:00")
        if text.replace(".", "", 1).isdigit():
            timestamp = float(text)
            if timestamp > 10_000_000_000:
                timestamp = timestamp / 1000
            parsed = datetime.fromtimestamp(timestamp, BEIJING_TIMEZONE)
        else:
            parsed = datetime.fromisoformat(text)
    except ValueError:
        match = re.search(r"(20\d{2})[-/年 ]?(\d{1,2})[-/月 ]?(\d{1,2})", value)
        if match:
            year, month, day = match.groups()
            return f"{year}{int(month):02d}{int(day):02d}"
        return CatalogCard.now_iso()[:10].replace("-", "")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BEIJING_TIMEZONE)
    return parsed.astimezone(BEIJING_TIMEZONE).strftime("%Y%m%d")


def stable_serial(raw_memory_id: str) -> str:
    digest = hashlib.sha1(raw_memory_id.encode("utf-8")).hexdigest()
    return f"{int(digest[:8], 16) % 10000:04d}"


def role_code(topology_role: str, path_status: str = "active", is_landmark: bool = False) -> str:
    if path_status == "dead_end":
        return "DD"
    if is_landmark:
        return "LM"
    return ROLE_CODES.get(topology_role, "MN")


def build_default_main_id(
    raw_memory_id: str,
    raw_memory_created_at: str | None,
    graph_domain: str = "ML",
    subgraph: str = "RET",
    position: str = "M00",
    topology_role: str = "node",
    path_status: str = "active",
    is_landmark: bool = False,
) -> str:
    return "-".join(
        [
            graph_domain,
            subgraph,
            position,
            role_code(topology_role, path_status, is_landmark),
            compact_date(raw_memory_created_at),
            stable_serial(raw_memory_id),
        ]
    )

