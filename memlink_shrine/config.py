from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Settings:
    google_api_key: str
    gemini_model: str
    recall_delegate: str
    write_adapters: tuple[str, ...]
    openmemory_base_url: str
    openmemory_user_id: str
    openmemory_app_name: str
    vcp_base_url: str
    vcp_root_path: Path | None
    vcp_admin_username: str
    vcp_admin_password: str
    vcp_timeout_seconds: float
    vcp_bridge_root_path: Path | None
    vcp_bridge_namespace: str
    memory_engine_map: dict[str, str]
    db_path: Path


def load_settings() -> Settings:
    default_db_path = PROJECT_ROOT / "data" / "memlink_shrine.db"
    bridge_root_text = os.getenv("VCP_BRIDGE_ROOT_PATH", "").strip()
    bridge_root = Path(bridge_root_text).resolve() if bridge_root_text else None
    vcp_root_text = os.getenv("VCP_ROOT_PATH", "").strip()
    vcp_root = Path(vcp_root_text).resolve() if vcp_root_text else None
    write_adapters_text = os.getenv("MEMLINK_SHRINE_WRITE_ADAPTERS", "vcp_bridge").strip()
    write_adapters = tuple(
        item.strip()
        for item in write_adapters_text.replace("，", ",").split(",")
        if item.strip()
    )
    memory_engine_map_text = os.getenv("MEMLINK_SHRINE_MEMORY_ENGINE_MAP", "").strip()
    memory_engine_map: dict[str, str] = {}
    for line in memory_engine_map_text.replace("||", "\n").splitlines():
        if "=" not in line:
            continue
        label, delegate_id = line.split("=", 1)
        clean_label = label.strip()
        clean_delegate = delegate_id.strip()
        if clean_label and clean_delegate:
            memory_engine_map[clean_label] = clean_delegate
    db_path = Path(os.getenv("MEMLINK_SHRINE_DB") or default_db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        gemini_model=os.getenv("MEMLINK_SHRINE_GEMINI_MODEL", "gemini-3-flash-preview"),
        recall_delegate=os.getenv("MEMLINK_SHRINE_RECALL_DELEGATE", "local_catalog").strip() or "local_catalog",
        write_adapters=write_adapters,
        openmemory_base_url=os.getenv("OPENMEMORY_BASE_URL", "http://localhost:8765").rstrip("/"),
        openmemory_user_id=os.getenv("OPENMEMORY_USER_ID", "administrator-main"),
        openmemory_app_name=os.getenv("OPENMEMORY_APP_NAME", "codex"),
        vcp_base_url=os.getenv("VCP_BASE_URL", "").rstrip("/"),
        vcp_root_path=vcp_root,
        vcp_admin_username=os.getenv("VCP_ADMIN_USERNAME", "").strip(),
        vcp_admin_password=os.getenv("VCP_ADMIN_PASSWORD", "").strip(),
        vcp_timeout_seconds=float(os.getenv("VCP_TIMEOUT_SECONDS", "12")),
        vcp_bridge_root_path=bridge_root,
        vcp_bridge_namespace=os.getenv("VCP_BRIDGE_NAMESPACE", "MemlinkShrineBridge").strip() or "MemlinkShrineBridge",
        memory_engine_map=memory_engine_map,
        db_path=db_path,
    )



