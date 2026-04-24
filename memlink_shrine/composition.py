from __future__ import annotations

from .config import Settings, load_settings
from .db import init_db
from .gemini_librarian import GeminiLibrarian
from .openmemory_adapter import OpenMemoryAdapter
from .recall_delegate import LocalCatalogRecallDelegate, VcpRecallDelegate
from .service import MemlinkShrineService


def _resolve_recall_delegate_id(settings: Settings, selected_memory_engine: str | None) -> str:
    label = str(selected_memory_engine or "").strip()
    if label:
        if label in settings.memory_engine_map:
            return settings.memory_engine_map[label]
        lowered = label.lower()
        if "vcp" in lowered:
            return "vcp"
        if "openmemory" in lowered:
            return "openmemory"
        if "local" in lowered or "catalog" in lowered:
            return "local_catalog"
    return settings.recall_delegate


def build_service_from_settings(
    settings: Settings | None = None,
    *,
    require_google: bool = False,
    selected_memory_engine: str | None = None,
) -> MemlinkShrineService:
    resolved = settings or load_settings()
    if require_google and not resolved.google_api_key:
        raise RuntimeError("缺少 GOOGLE_API_KEY")

    init_db(resolved.db_path)
    openmemory = OpenMemoryAdapter(resolved.openmemory_base_url, resolved.openmemory_user_id)
    librarian = (
        GeminiLibrarian(resolved.google_api_key, resolved.gemini_model)
        if resolved.google_api_key
        else None
    )
    recall_delegate = None
    recall_delegate_id = _resolve_recall_delegate_id(resolved, selected_memory_engine)
    if recall_delegate_id == "vcp":
        recall_delegate = VcpRecallDelegate(settings=resolved, db_path=resolved.db_path)
    elif recall_delegate_id == "local_catalog":
        recall_delegate = LocalCatalogRecallDelegate(resolved.db_path, librarian)

    return MemlinkShrineService(
        openmemory=openmemory,
        librarian=librarian,
        db_path=resolved.db_path,
        recall_delegate=recall_delegate,
    )
