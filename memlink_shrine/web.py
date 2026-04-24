from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from textwrap import dedent
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .composition import build_service_from_settings
from .config import load_settings
from .db import (
    get_card_by_id,
    init_db,
    list_all_cards,
    search_cards,
    update_card,
)
from .direct_write import (
    as_list as _as_list,
    create_direct_card,
)
from .models import CatalogCard
from .project_fusion import ProjectFusionResolver
from .session_auto_writer import (
    load_state as load_session_auto_writer_state,
    read_session_gate,
    resolve_host_id as resolve_session_host_id,
)
from .session_auto_writer import (
    confirm_pending_draft,
    list_pending_drafts,
    reject_pending_draft,
)
from .writing_spec import writing_spec_as_dict


settings = load_settings()
init_db(settings.db_path)
app = FastAPI(title="Memlink Shrine")

def build_service(require_google: bool = False):
    try:
        return build_service_from_settings(settings, require_google=require_google)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class UpdateCardRequest(BaseModel):
    title: str
    fact_summary: str
    meaning_summary: str
    posture_summary: str = ""
    emotion_trajectory: str = ""
    body_text: str = ""
    raw_text: str = ""
    base_facets: dict = Field(default_factory=dict)
    domain_facets: dict = Field(default_factory=dict)
    semantic_facets: dict | None = None
    main_id: str = ""
    upstream_main_ids: list[str] = Field(default_factory=list)
    downstream_main_ids: list[str] = Field(default_factory=list)
    relation_type: str = "unassigned"
    topology_role: str = "node"
    path_status: str = "active"
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
    governance: dict
    facet_pack_id: str | None = None
    facet_pack_version: str | None = None
    projection_status: str | None = None


class CreateCardRequest(BaseModel):
    raw_memory_id: str | None = None
    title: str
    fact_summary: str
    meaning_summary: str
    posture_summary: str = ""
    emotion_trajectory: str = ""
    body_text: str = ""
    raw_text: str = ""
    base_facets: dict = Field(default_factory=dict)
    domain_facets: dict = Field(default_factory=dict)
    semantic_facets: dict | None = None
    main_id: str = ""
    upstream_main_ids: list[str] = Field(default_factory=list)
    downstream_main_ids: list[str] = Field(default_factory=list)
    relation_type: str = "unassigned"
    topology_role: str = "node"
    path_status: str = "active"
    focus_anchor_main_id: str = ""
    focus_confidence: float = 0.0
    focus_reason: str = ""
    is_landmark: bool = False
    chain_author: str = ""
    chain_author_role: str = "assistant_suggestion"
    chain_status: str = ""
    chain_confidence: float = 0.0
    id_schema_id: str = "memlink_shrine_default_v2"
    source_id: str | None = None
    source_type: str = "assistant_direct"
    owner: str | None = None
    visibility: str = "private"
    confidence_source: str = "assistant_direct"
    last_verified_at: str | None = None
    governance: dict = Field(default_factory=dict)
    facet_pack_id: str | None = None
    facet_pack_version: str | None = None
    projection_status: str | None = None
    projection_based_on: str | None = None
    projection_created_at: str | None = None
    raw_memory_created_at: str | None = None


class BriefRequest(BaseModel):
    question: str
    routing_limit: int = 40


class SyncRequest(BaseModel):
    days: int = 30


class SessionMemoryGateRequest(BaseModel):
    mode: str
    confirm_before_write: bool = True
    selected_models: dict[str, str] | None = None
    available_graphs: list[str] | None = None


class AgentModelReportRequest(BaseModel):
    roles: dict[str, Any] = Field(default_factory=dict)


class DraftConfirmRequest(BaseModel):
    memory_points: list[str] = Field(default_factory=list)
    raw_excerpt: str = ""
    graph_assignments: list[str] = Field(default_factory=list)


CLIENT_ALIASES = {
    "沃尔玛": ["沃尔玛", "walmart"],
    "ALDI": ["ALDI", "阿尔迪", "alid"],
    "PB": ["PB", "Pottery Barn", "potterybarn"],
    "山姆": ["山姆", "Sam", "Sam's", "Sams"],
}


def _enterprise_facets(card: Any) -> dict[str, Any]:
    domain = card.domain_facets or {}
    enterprise = domain.get("enterprise", {})
    return enterprise if isinstance(enterprise, dict) else {}


def _card_project_name(card: Any) -> str:
    enterprise = _enterprise_facets(card)
    for value in _as_list(enterprise.get("项目")):
        clean = str(value or "").strip()
        if clean:
            return clean
    return "未归属项目"


def _build_project_resolver() -> ProjectFusionResolver:
    return ProjectFusionResolver(list_all_cards(settings.db_path))


def _serialize_card(card: CatalogCard, resolver: ProjectFusionResolver) -> dict[str, Any]:
    return resolver.enrich_card_dict(card)


def _nested_mapping_value(payload: Any, *keys: str) -> Any:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _normalize_vcp_path(value: Any) -> str:
    clean = str(value or "").strip().replace("\\", "/")
    return clean.lstrip("/") if clean else ""


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        values = value
    else:
        values = re.split(r"[，,;；\n]", str(value or ""))
    seen: list[str] = []
    for item in values:
        clean = str(item or "").strip()
        if clean and clean not in seen:
            seen.append(clean)
    return seen


def _extract_vcp_source_path(card: CatalogCard) -> str:
    semantic = card.semantic_facets or {}
    domain = card.domain_facets or {}
    candidates = [
        semantic.get("vcp_source_path"),
        _nested_mapping_value(semantic, "vcp", "source_file_path"),
        _nested_mapping_value(semantic, "vcp", "sourceFilePath"),
        _nested_mapping_value(domain, "vcp", "source_file_path"),
        _nested_mapping_value(domain, "vcp", "sourceFilePath"),
    ]
    if str(card.source_type or "").lower().startswith("vcp"):
        candidates.append(card.source_id)
    for candidate in candidates:
        clean = _normalize_vcp_path(candidate)
        if clean:
            return clean
    return ""


def _extract_vcp_range(card: CatalogCard) -> list[str]:
    semantic = card.semantic_facets or {}
    domain = card.domain_facets or {}
    candidates = [
        semantic.get("vcp_range"),
        _nested_mapping_value(semantic, "vcp", "range"),
        _nested_mapping_value(domain, "vcp", "range"),
    ]
    for candidate in candidates:
        values = _normalize_string_list(candidate)
        if values:
            return values
    return []


def _vcp_associative_endpoints() -> list[str]:
    base_url = settings.vcp_base_url.rstrip("/")
    if not base_url:
        return []
    if base_url.endswith("/associative-discovery"):
        return [base_url]

    candidates: list[str] = []
    if base_url.endswith("/admin_api/dailynotes") or base_url.endswith("/dailynotes"):
        candidates.append(f"{base_url}/associative-discovery")
    else:
        candidates.append(f"{base_url}/associative-discovery")
        candidates.append(f"{base_url}/admin_api/dailynotes/associative-discovery")
    return list(dict.fromkeys(candidates))


def _request_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }
    if settings.vcp_admin_username and settings.vcp_admin_password:
        token = base64.b64encode(
            f"{settings.vcp_admin_username}:{settings.vcp_admin_password}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=settings.vcp_timeout_seconds) as response:
        body = response.read().decode("utf-8")
    return json.loads(body or "{}")


def _call_vcp_associative_discovery(source_file_path: str, range_names: list[str] | None = None) -> dict[str, Any]:
    payload = {
        "sourceFilePath": source_file_path,
        "k": 12,
        "range": range_names or [],
        "tagBoost": 0.15,
    }
    errors: list[str] = []
    for url in _vcp_associative_endpoints():
        try:
            return _request_json(url, payload)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in {404, 405}:
                errors.append(f"{url} -> {exc.code}")
                continue
            raise RuntimeError(f"VCP 返回 {exc.code}: {detail or exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            errors.append(f"{url} -> {exc}")
    if errors:
        raise RuntimeError("；".join(errors))
    raise RuntimeError("未配置可用的 VCP 联想接口。")


def _empty_graph_payload(card: CatalogCard, message: str, project_name: str | None = None) -> dict[str, Any]:
    return {
        "mode": "vcp",
        "nodes": [],
        "edges": [],
        "focus_main_id": card.main_id or card.raw_memory_id,
        "project": project_name or _card_project_name(card),
        "message": message,
    }


def _normalize_vcp_graph_payload(
    card: CatalogCard,
    payload: dict[str, Any],
    project_name: str | None = None,
) -> dict[str, Any]:
    source_file_path = _extract_vcp_source_path(card)
    focus_id = card.main_id or f"seed:{card.raw_memory_id}"
    warning = str(payload.get("warning") or "").strip()
    results = payload.get("results")
    result_items = results if isinstance(results, list) else []

    nodes = [
        {
            "id": focus_id,
            "raw_memory_id": card.raw_memory_id,
            "title": card.title or source_file_path.split("/")[-1] or "当前记忆",
            "short_title": card.title or source_file_path.split("/")[-1] or "当前记忆",
            "role": "VCP 种子",
            "topology_role": "origin",
            "path_status": "",
            "relation_type": "seed",
            "current": True,
            "is_landmark": True,
            "graph_kind": "vcp",
            "level": 0,
            "lane": 0,
        }
    ]
    edges: list[dict[str, Any]] = []

    for index, item in enumerate(result_items, start=1):
        path_value = _normalize_vcp_path(
            item.get("path") or item.get("sourceFilePath") or item.get("name") or f"vcp-result-{index}"
        )
        score_raw = item.get("score")
        try:
            score_value = float(score_raw)
        except (TypeError, ValueError):
            score_value = 0.0
        title = str(item.get("name") or path_value.split("/")[-1] or f"联想结果 {index}").strip()
        node_id = f"vcp:{path_value or index}"
        nodes.append(
            {
                "id": node_id,
                "raw_memory_id": path_value or node_id,
                "title": title,
                "short_title": title,
                "role": f"匹配度 {score_value:.3f}",
                "match_score": score_value,
                "recall_rank": index,
                "topology_role": "node",
                "path_status": "",
                "relation_type": "associative",
                "current": False,
                "is_landmark": False,
                "graph_kind": "vcp",
                "level": 1,
                "lane": index - 1,
            }
        )
        edges.append(
            {
                "source": focus_id,
                "target": node_id,
                "relation_type": "associative",
                "association_score": score_value,
                "path_status": "",
                "reconnect": False,
            }
        )

    message_parts: list[str] = []
    if warning:
        message_parts.append(warning)
    if not result_items:
        message_parts.append("VCP 这次没有返回联想结果。")

    return {
        "mode": "vcp",
        "nodes": nodes,
        "edges": edges,
        "focus_main_id": focus_id,
        "project": project_name or _card_project_name(card),
        "source_file_path": source_file_path,
        "message": " ".join(message_parts).strip(),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }


SESSION_MEMORY_MODES = {
    "off": "熄火",
    "passive": "被动写入",
    "auto": "自动写入",
}
LEGACY_SESSION_MODE_ALIASES = {
    "ask": "passive",
}


def _hosted_settings_path(name: str, host_id: str | None = None):
    host = resolve_session_host_id(host_id)
    dot = name.rfind(".")
    host_name = f"{name[:dot]}.{host}{name[dot:]}" if dot > 0 else f"{name}.{host}"
    return settings.db_path.with_name(host_name)


def _session_gate_path(host_id: str | None = None):
    return _hosted_settings_path("session_memory_gate.json", host_id)


def _agent_model_report_path(host_id: str | None = None):
    return _hosted_settings_path("agent_model_report.json", host_id)


def _read_json_with_legacy(path, legacy_name: str, default: dict[str, Any]) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
    legacy_path = settings.db_path.with_name(legacy_name)
    if legacy_path.exists():
        try:
            return json.loads(legacy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
    return default


def _read_agent_model_report(host_id: str | None = None) -> dict[str, Any]:
    path = _agent_model_report_path(host_id)
    host_roles: dict[str, Any] = {}
    legacy_roles: dict[str, Any] = {}

    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            roles = payload.get("roles")
            if isinstance(roles, dict):
                host_roles = roles
        except (OSError, json.JSONDecodeError):
            host_roles = {}

    legacy_path = settings.db_path.with_name("agent_model_report.json")
    if legacy_path.exists():
        try:
            payload = json.loads(legacy_path.read_text(encoding="utf-8"))
            roles = payload.get("roles")
            if isinstance(roles, dict):
                legacy_roles = roles
        except (OSError, json.JSONDecodeError):
            legacy_roles = {}

    merged: dict[str, Any] = {}
    for key in set(legacy_roles.keys()) | set(host_roles.keys()):
        legacy_value = legacy_roles.get(key)
        host_value = host_roles.get(key)
        if isinstance(legacy_value, dict) and isinstance(host_value, dict):
            merged[key] = {**legacy_value, **host_value}
        elif isinstance(host_value, dict):
            merged[key] = host_value
        elif isinstance(legacy_value, dict):
            merged[key] = legacy_value

    return {"roles": merged}


def _write_agent_model_report(roles: dict[str, Any], host_id: str | None = None) -> dict[str, Any]:
    path = _agent_model_report_path(host_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean_roles = roles if isinstance(roles, dict) else {}
    data = {
        "host_id": resolve_session_host_id(host_id),
        "roles": clean_roles,
        "updated_at": CatalogCard.now_iso(),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _split_model_candidates(*values: str | None) -> list[str]:
    candidates: list[str] = []
    for value in values:
        for item in re.split(r"[，,;；\n]", str(value or "")):
            clean = item.strip()
            if clean and clean not in candidates:
                candidates.append(clean)
    return candidates


def _merge_agent_model_report(roles: dict[str, Any], host_id: str | None = None) -> dict[str, Any]:
    report = _read_agent_model_report(host_id).get("roles", {})
    for key in ("witness_model", "admin_model", "embedding_model", "engine_embedding_model"):
        if key not in roles:
            continue
        raw = report.get(key)
        if not isinstance(raw, dict):
            continue
        current = str(raw.get("current") or "").strip()
        candidates_raw = raw.get("candidates")
        candidates: list[str] = []
        if isinstance(candidates_raw, list):
            candidates = [str(item).strip() for item in candidates_raw if str(item).strip()]
        elif isinstance(candidates_raw, str):
            candidates = _split_model_candidates(candidates_raw)
        if key == "embedding_model":
            filtered: list[str] = []
            for item in candidates:
                lower = item.lower()
                if "vcp" in lower or "openmemory" in lower or "mem0" in lower or "local catalog" in lower:
                    filtered.append(item)
            candidates = filtered
            if current:
                current_lower = current.lower()
                if not any(token in current_lower for token in ("vcp", "openmemory", "mem0", "local catalog")):
                    current = ""
        if current:
            roles[key]["current"] = current
        if candidates:
            merged = []
            for item in [roles[key].get("current", ""), *candidates]:
                if item and item not in merged:
                    merged.append(item)
            roles[key]["candidates"] = merged
    return roles


def _detect_vcp_version() -> str:
    root = settings.vcp_root_path
    if not root:
        return ""
    package_json = root / "package.json"
    if not package_json.exists():
        return ""
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("version") or "").strip()


def _read_vcp_config_map() -> dict[str, str]:
    candidate_paths: list[Path] = []
    if settings.vcp_root_path:
        candidate_paths.append(settings.vcp_root_path / "config.env")
    if settings.vcp_bridge_root_path:
        candidate_paths.append(settings.vcp_bridge_root_path.parent / "config.env")
    candidate_paths.append(Path(r"C:\Users\Administrator\Desktop\__inspect_vcp_toolbox\config.env"))

    config_path = next((path for path in candidate_paths if path and path.exists()), None)
    if not config_path:
        return {}
    values: dict[str, str] = {}
    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
    except OSError:
        return {}
    return values


def _detect_vcp_embedding_model() -> str:
    values = _read_vcp_config_map()
    return str(values.get("WhitelistEmbeddingModel") or "").strip()


def _normalize_session_mode(mode: str | None) -> str:
    clean = str(mode or "off").strip()
    clean = LEGACY_SESSION_MODE_ALIASES.get(clean, clean)
    return clean if clean in SESSION_MEMORY_MODES else "off"


def _role_entry(
    *,
    label: str,
    current: str,
    candidates: list[str],
    position: str,
    responsibility: str,
) -> dict[str, Any]:
    clean_candidates = [item for item in candidates if item]
    if current and current not in clean_candidates:
        clean_candidates.insert(0, current)
    return {
        "label": label,
        "current": current or (clean_candidates[0] if clean_candidates else "未配置"),
        "candidates": clean_candidates or ["未配置"],
        "position": position,
        "responsibility": responsibility,
    }


def _default_selected_models(model_roles: dict[str, Any]) -> dict[str, str]:
    selected: dict[str, str] = {}
    for key, role in model_roles.items():
        if isinstance(role, dict):
            selected[key] = str(role.get("current") or "未配置")
        else:
            selected[key] = str(role or "未配置")
    return selected


def _default_session_gate_state(host_id: str | None = None) -> dict[str, Any]:
    model_roles = _model_roles_state(host_id)
    return {
        "host_id": resolve_session_host_id(host_id),
        "mode": "passive",
        "label": SESSION_MEMORY_MODES["passive"],
        "confirm_before_write": True,
        "model_roles": model_roles,
        "selected_models": _default_selected_models(model_roles),
        "available_graphs": [],
        "updated_at": CatalogCard.now_iso(),
    }


def _model_roles_state(host_id: str | None = None) -> dict[str, Any]:
    witness_model = os.getenv("MEMLINK_SHRINE_WITNESS_MODEL", "").strip()
    witness_models = os.getenv("MEMLINK_SHRINE_WITNESS_MODELS", "").strip()
    admin_models = os.getenv("MEMLINK_SHRINE_ADMIN_MODELS", "").strip()
    engine_model = os.getenv("MEMLINK_SHRINE_MEMORY_ENGINE", "").strip()
    engine_models = os.getenv("MEMLINK_SHRINE_MEMORY_ENGINES", "").strip()
    engine_embedding_model = os.getenv("MEMLINK_SHRINE_ENGINE_EMBEDDING_MODEL", "").strip()
    engine_embedding_models = os.getenv("MEMLINK_SHRINE_ENGINE_EMBEDDING_MODELS", "").strip()
    default_witness = witness_model or "由现场协作模型声明，例如 Codex / Claude"
    default_admin = settings.gemini_model or "未配置"
    vcp_version = _detect_vcp_version()
    vcp_display_name = f"VCP {vcp_version}（当前主联想引擎）" if vcp_version else "VCP（当前主联想引擎）"
    default_engine = engine_model or (vcp_display_name if settings.vcp_base_url else "未配置底层引擎")
    vcp_embedding_current = _detect_vcp_embedding_model()
    default_engine_embedding = engine_embedding_model or (vcp_embedding_current if vcp_embedding_current else "未配置联想引擎 embedding 模型")
    roles = {
        "witness_model": _role_entry(
            label="知情者模型 / 协作模型",
            current=default_witness,
            candidates=_split_model_candidates(witness_models),
            position="对话现场与直写入口",
            responsibility="负责把当前讨论整理成残影草稿，判断这次该不该写、写哪几点；它是现场知情者，不负责底层联想召回。",
        ),
        "admin_model": _role_entry(
            label="管理员模型 / 治理馆员",
            current=default_admin,
            candidates=_split_model_candidates(admin_models),
            position="标准层与治理校验",
            responsibility="负责四摘要、标签、领域包、链路说明和质量校验；帮助整理记忆对象，但不替知情者决定写入意图，也不替 VCP 做联想。",
        ),
        "embedding_model": _role_entry(
            label="底层召回 / 联想引擎",
            current=default_engine,
            candidates=_split_model_candidates(engine_models, vcp_display_name),
            position="召回层与联想层",
            responsibility="负责底层召回、相近记忆激活与联想；Memlink 只做标准化写入与投递，真正召回使用这里选中的底层 memory 引擎。",
        ),
        "engine_embedding_model": _role_entry(
            label="联想引擎嵌入模型",
            current=default_engine_embedding,
            candidates=_split_model_candidates(engine_embedding_models, vcp_embedding_current),
            position="联想引擎内部向量化配置",
            responsibility="这是底层联想引擎自己用于向量化与相似检索的 embedding 模型，不属于 Memlink Core。本层只展示与记录当前底层引擎的 embedding 配置。",
        ),
    }
    return _merge_agent_model_report(roles, host_id)


def _normalize_selected_models(raw: Any, model_roles: dict[str, Any]) -> dict[str, str]:
    raw_map = raw if isinstance(raw, dict) else {}
    selected = _default_selected_models(model_roles)
    for key, role in model_roles.items():
        value = str(raw_map.get(key) or "").strip()
        if not value:
            continue
        candidates = role.get("candidates", []) if isinstance(role, dict) else []
        if value in candidates or value == "未配置":
            selected[key] = value
    return selected


def _normalize_available_graphs(raw: Any) -> list[str]:
    seen: list[str] = []
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, str):
        values = re.split(r"[，,;；\n]", raw)
    else:
        values = []
    for item in values:
        clean = str(item or "").strip()
        if clean and clean not in seen:
            seen.append(clean)
    return seen


def _read_session_gate_state(host_id: str | None = None) -> dict[str, Any]:
    path = _session_gate_path(host_id)
    data = _read_json_with_legacy(path, "session_memory_gate.json", {})
    if not data:
        return _default_session_gate_state(host_id)
    mode = _normalize_session_mode(data.get("mode"))
    model_roles = _model_roles_state(host_id)
    return {
        "host_id": resolve_session_host_id(host_id),
        "mode": mode,
        "label": SESSION_MEMORY_MODES[mode],
        "confirm_before_write": bool(data.get("confirm_before_write", True)),
        "model_roles": model_roles,
        "selected_models": _normalize_selected_models(data.get("selected_models"), model_roles),
        "available_graphs": _normalize_available_graphs(data.get("available_graphs")),
        "updated_at": data.get("updated_at") or CatalogCard.now_iso(),
    }


def _write_session_gate_state(
    mode: str,
    confirm_before_write: bool = True,
    selected_models: dict[str, str] | None = None,
    available_graphs: list[str] | None = None,
    host_id: str | None = None,
) -> dict[str, Any]:
    clean_mode = str(mode or "off").strip()
    clean_mode = LEGACY_SESSION_MODE_ALIASES.get(clean_mode, clean_mode)
    if clean_mode not in SESSION_MEMORY_MODES:
        raise HTTPException(status_code=400, detail="会话记忆模式只能是 off / passive / auto。")
    model_roles = _model_roles_state(host_id)
    state = {
        "host_id": resolve_session_host_id(host_id),
        "mode": clean_mode,
        "label": SESSION_MEMORY_MODES[clean_mode],
        "confirm_before_write": bool(confirm_before_write),
        "model_roles": model_roles,
        "selected_models": _normalize_selected_models(selected_models, model_roles),
        "available_graphs": _normalize_available_graphs(available_graphs),
        "updated_at": CatalogCard.now_iso(),
    }
    path = _session_gate_path(host_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def _has_meaningful_chain_content(payload: dict[str, Any]) -> bool:
    upstream = _as_list(payload.get("upstream_main_ids"))
    downstream = _as_list(payload.get("downstream_main_ids"))
    relation_type = str(payload.get("relation_type") or "unassigned").strip()
    topology_role = str(payload.get("topology_role") or "node").strip()
    path_status = str(payload.get("path_status") or "active").strip()
    focus_anchor = str(payload.get("focus_anchor_main_id") or "").strip()
    focus_reason = str(payload.get("focus_reason") or "").strip()
    return any(
        [
            bool(upstream),
            bool(downstream),
            relation_type not in {"", "unassigned"},
            topology_role not in {"", "node"},
            path_status not in {"", "active"},
            bool(focus_anchor),
            bool(focus_reason),
            bool(payload.get("is_landmark")),
        ]
    )


def _clean_update_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(payload)
    cleaned["upstream_main_ids"] = _as_list(cleaned.get("upstream_main_ids"))
    cleaned["downstream_main_ids"] = _as_list(cleaned.get("downstream_main_ids"))
    semantic_facets = cleaned.get("semantic_facets")
    if semantic_facets is not None and not isinstance(semantic_facets, dict):
        cleaned["semantic_facets"] = {}
    return cleaned


def _contains_any(values: list[str], needles: list[str]) -> bool:
    haystack = " ".join(values).lower()
    return any(needle.lower() in haystack for needle in needles if needle)


def _time_aliases(value: str) -> list[str]:
    value = value.strip()
    aliases = [value, value.replace(" ", "")]
    if "4月" in value and "2026" in value:
        aliases.extend(["2026-04", "2026年4月", "2026年04月", "2026 04"])
    return aliases


def _card_matches_filters(
    card: Any,
    memory_scope: str = "",
    time_basis: str = "",
    year: str = "",
    time_tag: str = "",
    client: str = "",
    style: str = "",
    theme: str = "",
) -> bool:
    base = card.base_facets or {}
    enterprise = _enterprise_facets(card)
    enterprise_values = [
        item
        for value in enterprise.values()
        for item in _as_list(value)
    ]
    has_enterprise_facets = bool(enterprise_values)

    if memory_scope == "enterprise" and not has_enterprise_facets:
        return False
    if memory_scope == "general" and has_enterprise_facets:
        return False
    if memory_scope == "personal":
        scope_values = _as_list(base.get("relevance_scope_core")) + _as_list(base.get("topic"))
        if base.get("memory_type") not in {"identity", "reflection"} and not _contains_any(scope_values, ["个人", "学习", "身份"]):
            return False
    if memory_scope == "system":
        scope_values = _as_list(base.get("relevance_scope_core")) + _as_list(base.get("topic")) + _as_list(base.get("entity"))
        if not _contains_any(scope_values, ["系统", "Memlink Shrine", "记忆图书馆", "Memlink", "方法规范"]):
            return False

    record_time_values = _as_list(card.raw_memory_created_at) + _as_list(card.projection_created_at) + _as_list(card.updated_at)
    content_time_values = _as_list(base.get("time")) + _as_list(enterprise.get("时间/季节/节庆"))
    if time_basis == "record":
        time_values = record_time_values
    elif time_basis == "content":
        time_values = content_time_values
    else:
        time_values = content_time_values + record_time_values

    if year and year != "全部年份" and not _contains_any(time_values, [year]):
        return False

    if time_tag:
        if not _contains_any(time_values, _time_aliases(time_tag)):
            return False

    if client:
        aliases = CLIENT_ALIASES.get(client, [client])
        if not _contains_any(_as_list(enterprise.get("客户")), aliases):
            return False

    if style and not _contains_any(_as_list(enterprise.get("风格")) + _as_list(enterprise.get("风格/主题")), [style]):
        return False

    if theme and not _contains_any(_as_list(enterprise.get("主题")) + _as_list(enterprise.get("风格/主题")), [theme]):
        return False

    return True


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/writing-spec")
def api_writing_spec() -> dict:
    return writing_spec_as_dict()


@app.get("/api/session-memory-gate")
def api_session_memory_gate(x_memory_host: str | None = Header(default=None)) -> dict:
    return _read_session_gate_state(x_memory_host)


@app.get("/api/session-auto-writer-status")
def api_session_auto_writer_status(x_memory_host: str | None = Header(default=None)) -> dict:
    host_id = resolve_session_host_id(x_memory_host)
    state = load_session_auto_writer_state(host_id)
    return {
        "host_id": host_id,
        "gate": read_session_gate(host_id),
        "watcher_state": state,
        "pending_drafts": list_pending_drafts(host_id),
    }


@app.get("/api/session-auto-writer-drafts")
def api_session_auto_writer_drafts(x_memory_host: str | None = Header(default=None)) -> dict:
    return {
        "host_id": resolve_session_host_id(x_memory_host),
        "items": list_pending_drafts(x_memory_host),
    }


@app.post("/api/session-auto-writer-drafts/{session_id}/confirm")
def api_confirm_session_auto_writer_draft(
    session_id: str,
    request: DraftConfirmRequest | None = None,
    x_memory_host: str | None = Header(default=None),
) -> dict:
    try:
        edits = request.model_dump() if request else None
        return confirm_pending_draft(session_id, edits=edits, host_id=x_memory_host)
    except KeyError:
        raise HTTPException(status_code=404, detail="待确认残影草稿不存在")


@app.post("/api/session-auto-writer-drafts/{session_id}/reject")
def api_reject_session_auto_writer_draft(session_id: str, x_memory_host: str | None = Header(default=None)) -> dict:
    try:
        return reject_pending_draft(session_id, host_id=x_memory_host)
    except KeyError:
        raise HTTPException(status_code=404, detail="待确认残影草稿不存在")


@app.get("/api/openmemory-status")
def api_openmemory_status() -> dict:
    url = f"{settings.openmemory_base_url}/docs"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return {
                "reachable": True,
                "base_url": settings.openmemory_base_url,
                "status_code": response.status,
            }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "reachable": False,
            "base_url": settings.openmemory_base_url,
            "error": str(exc),
        }


@app.put("/api/session-memory-gate")
def api_update_session_memory_gate(request: SessionMemoryGateRequest, x_memory_host: str | None = Header(default=None)) -> dict:
    return _write_session_gate_state(
        mode=request.mode,
        confirm_before_write=request.confirm_before_write,
        selected_models=request.selected_models,
        available_graphs=request.available_graphs,
        host_id=x_memory_host,
    )


@app.put("/api/session-memory-gate/model-roles")
def api_update_agent_model_roles(request: AgentModelReportRequest, x_memory_host: str | None = Header(default=None)) -> dict:
    _write_agent_model_report(request.roles, x_memory_host)
    return _read_session_gate_state(x_memory_host)


@app.get("/api/cards")
def api_cards(
    query: str = "",
    limit: int = 50,
    memory_scope: str = "",
    time_basis: str = "",
    year: str = "",
    time_tag: str = "",
    client: str = "",
    style: str = "",
    theme: str = "",
) -> list[dict]:
    has_filters = any([memory_scope, time_basis, year, time_tag, client, style, theme])
    resolver = _build_project_resolver()
    cards = search_cards(settings.db_path, query=query, limit=max(limit, 500) if has_filters else limit)
    if has_filters:
        cards = [
            card for card in cards
            if _card_matches_filters(card, memory_scope, time_basis, year, time_tag, client, style, theme)
        ][:limit]
    return [_serialize_card(card, resolver) for card in cards]


@app.get("/api/cards/{raw_memory_id}")
def api_card_detail(raw_memory_id: str) -> dict:
    card = get_card_by_id(settings.db_path, raw_memory_id)
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")
    return _serialize_card(card, _build_project_resolver())


@app.get("/api/cards/{raw_memory_id}/graph")
def api_card_graph(raw_memory_id: str, mode: str = "local", hops: int = 2) -> dict:
    service = build_service()
    return service.build_graph_payload(raw_memory_id=raw_memory_id, mode=mode, hops=hops)


@app.get("/api/cards/{raw_memory_id}/vcp-graph")
def api_card_vcp_graph(raw_memory_id: str) -> dict:
    card = get_card_by_id(settings.db_path, raw_memory_id)
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")
    resolver = _build_project_resolver()
    project_name = resolver.project_for_card(card).root_project
    if not settings.vcp_base_url:
        return _empty_graph_payload(card, "尚未配置 VCP_BASE_URL，当前还不能加载 VCP 联想图。", project_name)

    source_file_path = _extract_vcp_source_path(card)
    if not source_file_path:
        return _empty_graph_payload(card, "这张卡还没绑定 VCP 源文件路径，请先写入 vcp_source_path。", project_name)

    try:
        discovery = _call_vcp_associative_discovery(
            source_file_path=source_file_path,
            range_names=_extract_vcp_range(card),
        )
    except RuntimeError as exc:
        return _empty_graph_payload(card, f"VCP 联想图暂时不可用：{exc}", project_name)

    return _normalize_vcp_graph_payload(card, discovery, project_name)


@app.get("/api/cards/{raw_memory_id}/mechanisms")
def api_card_mechanisms(raw_memory_id: str) -> dict:
    service = build_service()
    return service.build_mechanism_payload(raw_memory_id=raw_memory_id)


@app.put("/api/cards/{raw_memory_id}")
def api_card_update(raw_memory_id: str, request: UpdateCardRequest) -> dict:
    payload = _clean_update_payload(request.model_dump(exclude_none=True))
    if _has_meaningful_chain_content(payload) and str(payload.get("chain_author_role") or "none").strip() == "none":
        raise HTTPException(status_code=400, detail="链路编辑必须声明作者角色，不能保持 none。")
    try:
        card = update_card(settings.db_path, raw_memory_id, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="卡片不存在")
    return _serialize_card(card, _build_project_resolver())


@app.post("/api/cards")
def api_card_create(
    request: CreateCardRequest,
    x_memory_author_role: str | None = Header(default=None),
    x_memory_author: str | None = Header(default=None),
) -> dict:
    try:
        card = create_direct_card(
            settings.db_path,
            request.model_dump(exclude_none=True),
            author_role=x_memory_author_role,
            author=x_memory_author,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return _serialize_card(card, _build_project_resolver())


@app.post("/api/query-brief")
def api_query_brief(request: BriefRequest, x_memory_host: str | None = Header(default=None)) -> dict:
    gate_state = _read_session_gate_state(x_memory_host)
    selected_engine = str((gate_state.get("selected_models") or {}).get("embedding_model") or "").strip()
    service = build_service_from_settings(
        settings,
        require_google=True,
        selected_memory_engine=selected_engine,
    )
    brief = service.build_memory_brief(
        question=request.question,
        routing_limit=request.routing_limit,
    )
    if isinstance(brief, dict):
        return brief
    return brief.as_dict()


@app.post("/api/sync")
def api_sync(request: SyncRequest) -> dict:
    service = build_service(require_google=True)
    count = service.sync_recent_memories(days=request.days)
    return {"synced": count}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    import base64, pathlib

    def _b64(path: str) -> str:
        return base64.b64encode(pathlib.Path(path).read_bytes()).decode()

    shrine_b64 = _b64(r"C:\Users\Administrator\Desktop\memory\图标\shrine_statue_crop.png")
    bg_b64     = _b64(r"C:\Users\Administrator\Desktop\memory\图标\g4.png")
    icon1_b64  = _b64(r"C:\Users\Administrator\Desktop\memory\图标\icon_1.png")
    icon2_b64  = _b64(r"C:\Users\Administrator\Desktop\memory\图标\icon_2.png")
    icon3_b64  = _b64(r"C:\Users\Administrator\Desktop\memory\图标\icon_3.png")
    icon4_b64  = _b64(r"C:\Users\Administrator\Desktop\memory\图标\icon_4.png")

    html = dedent(
        """
        <!doctype html>
        <html lang="zh-CN">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <title>Memlink Shrine</title>
          <style>
            :root {
              --bg: #0b1220;
              --panel: #131b2b;
              --panel-2: #0f1725;
              --line: #263247;
              --text: #eef4ff;
              --muted: #98a4b6;
              --accent: #4f8cff;
              --accent-2: #2fbf71;
              --danger: #ef5350;
              --shadow: 0 18px 40px rgba(0,0,0,.28);
            }
            * { box-sizing: border-box; }
            body {
              margin: 0;
              font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
              color: var(--text);
              background:
                radial-gradient(circle at top left, rgba(79,140,255,.16), transparent 30%),
                radial-gradient(circle at bottom right, rgba(47,191,113,.10), transparent 28%),
                linear-gradient(180deg, #09101b 0%, #0b1220 100%);
            }
            .shell {
              display: grid;
              grid-template-columns: 360px 1fr;
              min-height: 100vh;
            }
            .sidebar {
              padding: 18px;
              border-right: 1px solid var(--line);
              background: rgba(9, 16, 27, .85);
              backdrop-filter: blur(10px);
            }
            .main {
              padding: 18px;
            }
            .panel {
              background: linear-gradient(180deg, rgba(19,27,43,.96), rgba(15,23,37,.96));
              border: 1px solid var(--line);
              border-radius: 16px;
              padding: 16px;
              box-shadow: var(--shadow);
            }
            h1, h2, h3 {
              margin: 0 0 10px;
              font-weight: 650;
            }
            .sub {
              color: var(--muted);
              font-size: 13px;
              line-height: 1.6;
            }
            .row {
              display: flex;
              gap: 10px;
              margin-bottom: 12px;
            }
            .grid-2 {
              display: grid;
              grid-template-columns: 1fr 1fr;
              gap: 12px;
            }
            .grid-3 {
              display: grid;
              grid-template-columns: 1fr 1fr 1fr;
              gap: 12px;
            }
            label {
              display: block;
              font-size: 13px;
              color: var(--muted);
              margin-bottom: 6px;
            }
            input, textarea, select {
              width: 100%;
              background: #0a111d;
              color: var(--text);
              border: 1px solid var(--line);
              border-radius: 10px;
              padding: 10px 12px;
              font: inherit;
            }
            textarea {
              min-height: 96px;
              resize: vertical;
            }
            .smallarea textarea {
              min-height: 72px;
            }
            .tiny textarea {
              min-height: 56px;
            }
            button {
              border: none;
              border-radius: 10px;
              padding: 10px 14px;
              font: inherit;
              font-weight: 600;
              cursor: pointer;
              background: var(--accent);
              color: white;
            }
            button.secondary { background: #243042; }
            button.ghost {
              background: transparent;
              border: 1px solid var(--line);
            }
            .status {
              color: var(--muted);
              font-size: 13px;
              align-self: center;
            }
            .list {
              margin-top: 14px;
              display: flex;
              flex-direction: column;
              gap: 10px;
              max-height: calc(100vh - 220px);
              overflow: auto;
            }
            .card-item {
              background: rgba(10, 17, 29, .72);
              border: 1px solid var(--line);
              border-radius: 10px;
              padding: 10px 10px 8px;
              cursor: pointer;
              transition: .16s ease;
            }
            .card-item:hover {
              border-color: #3f5d8b;
              background: rgba(15, 23, 37, .9);
            }
            .card-item.active {
              border-color: var(--accent-2);
              box-shadow: inset 0 0 0 1px rgba(47,191,113,.18);
            }
            .project-group {
              border: 1px solid var(--line);
              border-radius: 12px;
              background: rgba(15, 23, 37, .48);
              overflow: hidden;
            }
            .project-group summary {
              cursor: pointer;
              padding: 10px 12px 9px;
              color: var(--text);
              font-weight: 700;
              display: flex;
              justify-content: space-between;
              gap: 10px;
              list-style: none;
              position: sticky;
              top: 0;
              z-index: 1;
              background: rgba(19, 27, 43, .96);
              border-bottom: 1px solid rgba(38, 50, 71, .65);
            }
            .project-group summary::-webkit-details-marker { display: none; }
            .project-count {
              color: var(--muted);
              font-size: 12px;
              font-weight: 500;
            }
            .project-cards {
              display: flex;
              flex-direction: column;
              gap: 8px;
              padding: 8px 8px 10px;
              max-height: 420px;
              overflow: auto;
            }
            .subproject-stack {
              display: flex;
              flex-direction: column;
              gap: 8px;
              padding: 0 8px 10px;
              max-height: min(540px, calc(100vh - 310px));
              overflow-y: auto;
              overflow-x: hidden;
              scrollbar-gutter: stable;
            }
            .subproject-stack::-webkit-scrollbar {
              width: 8px;
            }
            .subproject-stack::-webkit-scrollbar-thumb {
              background: rgba(92, 110, 140, .6);
              border-radius: 999px;
            }
            .subproject-stack::-webkit-scrollbar-track {
              background: rgba(15, 23, 37, .28);
              border-radius: 999px;
            }
            .folder-rail-wrap {
              display: grid;
              grid-template-columns: 28px 1fr 28px;
              gap: 6px;
              align-items: center;
              padding: 8px 8px 4px;
            }
            .folder-rail-nav {
              width: 28px;
              height: 28px;
              border-radius: 8px;
              border: 1px solid var(--line);
              background: rgba(12, 20, 35, .92);
              color: #dfe9ff;
              cursor: pointer;
              padding: 0;
              font-size: 13px;
            }
            .folder-rail {
              display: flex;
              gap: 8px;
              overflow-x: auto;
              overflow-y: hidden;
              scroll-behavior: smooth;
              padding: 2px 1px 4px;
            }
            .folder-rail::-webkit-scrollbar {
              height: 6px;
            }
            .folder-rail::-webkit-scrollbar-thumb {
              background: rgba(92, 110, 140, .55);
              border-radius: 999px;
            }
            .folder-chip {
              flex: 0 0 auto;
              border: 1px solid rgba(58, 74, 103, .95);
              background: rgba(16, 25, 40, .95);
              color: #dfe9ff;
              border-radius: 8px;
              padding: 7px 10px;
              font-size: 12px;
              line-height: 1.2;
              cursor: pointer;
              white-space: nowrap;
            }
            .folder-chip.active {
              border-color: #2ed573;
              box-shadow: inset 0 0 0 1px rgba(46, 213, 115, .22);
              background: rgba(19, 46, 34, .95);
            }
            .subproject-group {
              border: 1px solid rgba(38, 50, 71, .8);
              border-radius: 10px;
              background: rgba(11, 18, 32, .46);
              overflow: hidden;
            }
            .subproject-group summary {
              cursor: pointer;
              padding: 8px 10px;
              display: flex;
              justify-content: space-between;
              gap: 8px;
              color: #dfe9ff;
              font-size: 13px;
              font-weight: 650;
              list-style: none;
              background: rgba(12, 20, 35, .88);
              border-bottom: 1px solid rgba(38, 50, 71, .55);
            }
            .subproject-group summary::-webkit-details-marker { display: none; }
            .subproject-count {
              color: var(--muted);
              font-size: 11.5px;
              font-weight: 500;
            }
            .project-direct-note {
              padding: 8px 10px 0;
              color: #8ea0bc;
              font-size: 11.5px;
            }
            .card-title {
              font-weight: 650;
              margin-bottom: 6px;
              display: -webkit-box;
              -webkit-line-clamp: 2;
              -webkit-box-orient: vertical;
              overflow: hidden;
            }
            .card-sub {
              color: var(--muted);
              font-size: 12px;
              line-height: 1.45;
              display: -webkit-box;
              -webkit-line-clamp: 2;
              -webkit-box-orient: vertical;
              overflow: hidden;
            }
            .meta {
              display: flex;
              flex-wrap: wrap;
              gap: 6px;
              margin-top: 8px;
            }
            .pill {
              font-size: 11px;
              color: var(--muted);
              padding: 3px 7px;
              border: 1px solid var(--line);
              border-radius: 999px;
            }
            .layout {
              display: grid;
              grid-template-columns: 1.25fr 0.95fr;
              gap: 16px;
            }
            .stack {
              display: flex;
              flex-direction: column;
              gap: 16px;
            }
            .checkbox {
              display: flex;
              gap: 8px;
              align-items: center;
              color: var(--text);
              margin-top: 28px;
            }
            .checkbox input {
              width: auto;
            }
            .detail-box, .brief-box {
              white-space: pre-wrap;
              word-break: break-word;
              background: #0a111d;
              border: 1px solid var(--line);
              border-radius: 12px;
              padding: 12px;
              min-height: 180px;
            }
            .detail-box {
              min-height: 260px;
              max-height: 320px;
              overflow: auto;
            }
            .brief-box {
              min-height: 220px;
              max-height: 320px;
              overflow: auto;
            }
            .graph-toolbar {
              display: flex;
              justify-content: space-between;
              align-items: center;
              gap: 10px;
              margin-top: 14px;
              margin-bottom: 10px;
            }
            .graph-box {
              background: #0a111d;
              border: 1px solid var(--line);
              border-radius: 12px;
              padding: 12px;
              display: flex;
              flex-direction: column;
              gap: 12px;
            }
            .graph-scroll {
              overflow: hidden;
              max-height: 620px;
              min-height: 520px;
              border-radius: 10px;
              cursor: grab;
              user-select: none;
              border: 1px solid rgba(38, 50, 71, .55);
              background: linear-gradient(180deg, rgba(10,17,29,.94), rgba(8,13,23,.98));
              position: relative;
            }
            .graph-scroll.dragging { cursor: grabbing; }
            .graph-scroll svg {
              display: block;
              width: 100%;
              min-height: 260px;
            }
            .graph-status {
              color: var(--muted);
              font-size: 12px;
            }
            .graph-legend {
              display: flex;
              flex-wrap: wrap;
              gap: 8px;
              margin-top: 10px;
            }
            .legend-pill {
              font-size: 11px;
              padding: 4px 8px;
              border-radius: 999px;
              border: 1px solid var(--line);
              color: var(--muted);
            }
            .legend-current { border-color: #2ed573; color: #baf6cb; }
            .legend-origin { border-color: #57b5ff; color: #b9dcff; }
            .legend-normal { border-color: #6c86ff; color: #c9d3ff; }
            .legend-assoc { border-color: #ff8f57; color: #ffd0ba; }
            .legend-special { border-color: #ffb454; color: #ffd9a3; }
            .legend-reconnect { border-color: #ffb454; color: #ffd9a3; border-style: dashed; }
            details {
              border: 1px solid var(--line);
              border-radius: 12px;
              padding: 10px 12px;
              background: rgba(10,17,29,.75);
            }
            summary {
              cursor: pointer;
              color: var(--muted);
            }
            .filter-mini {
              margin-top: 12px;
              display: flex;
              flex-direction: column;
              gap: 10px;
            }
            .divider-title {
              display: flex;
              align-items: center;
              justify-content: space-between;
              gap: 10px;
              margin-bottom: 12px;
            }
            .tag {
              color: var(--muted);
              font-size: 12px;
              border: 1px solid var(--line);
              border-radius: 999px;
              padding: 4px 8px;
            }
            .hint-box {
              border: 1px dashed rgba(255,184,107,.5);
              border-radius: 12px;
              background: rgba(255,184,107,.08);
              color: #ffd7a6;
              padding: 10px 12px;
              font-size: 13px;
              line-height: 1.6;
              margin-bottom: 12px;
            }
            .muted-block {
              border: 1px solid var(--line);
              border-radius: 12px;
              padding: 10px 12px;
              background: rgba(10,17,29,.55);
              color: var(--muted);
              font-size: 13px;
              line-height: 1.6;
            }
            #mechanismOutput {
              min-height: 180px;
              max-height: 240px;
              overflow: auto;
            }
            .memory-gate {
              position: fixed;
              right: 30px;
              bottom: 30px;
              z-index: 9999;
              color: #d4b090;
              font-family: "Georgia", "STSong", "SimSun", serif;
            }
            .memory-gate-controls {
              display: flex;
              align-items: center;
              justify-content: flex-end;
            }
            .memory-gate-arrow {
              width: 40px;
              height: 40px;
              border-radius: 8px;
              padding: 0;
              display: grid;
              place-items: center;
              background: #1a1208;
              border: 1px solid #6b4820;
              color: #c8902a;
              font-size: 18px;
              box-shadow: 0 0 12px rgba(0,0,0,.6), inset 0 1px 0 rgba(255,200,100,.1);
              cursor: pointer;
              transition: border-color .2s, color .2s;
            }
            .memory-gate.open .memory-gate-arrow {
              color: #e8b840;
              border-color: #c8902a;
            }
            .memory-gate-panel {
              position: absolute;
              right: 0;
              bottom: 56px;
              width: 420px;
              max-width: min(420px, calc(100vw - 32px));
              display: none;
              background-image: url('data:image/png;base64,__BG__');
              background-size: cover;
              background-position: center;
              border: 1px solid #5a3c18;
              border-radius: 4px;
              box-shadow: 0 24px 60px rgba(0,0,0,.7), inset 0 0 40px rgba(0,0,0,.3), 0 0 0 1px rgba(180,130,50,.12);
              overflow: hidden;
            }
            .memory-gate.open .memory-gate-panel { display: block; }
            .memory-gate-head {
              display: flex;
              justify-content: space-between;
              align-items: flex-start;
              padding: 14px 16px 10px;
              border-bottom: 1px solid #4a3010;
              cursor: grab;
              background: linear-gradient(180deg, rgba(30,20,8,.9) 0%, rgba(20,14,6,.7) 100%);
              position: relative;
              min-height: 90px;
            }
            .memory-gate-title {
              font-size: 22px;
              font-weight: 700;
              color: #d8c090;
              letter-spacing: 0.04em;
              line-height: 1.2;
              text-shadow: 0 1px 4px rgba(0,0,0,.8);
              margin-bottom: 4px;
            }
            .memory-gate-state-label {
              font-size: 13px;
              color: #a08050;
              letter-spacing: 0.06em;
            }
            .memory-gate-statue {
              position: absolute;
              right: 8px;
              top: 4px;
              width: 100px;
              height: 110px;
              object-fit: contain;
              filter: drop-shadow(0 0 8px rgba(100,160,255,.35));
            }
            .ghost-btn {
              font-size: 11px;
              color: #6a5030;
              background: none;
              border: none;
              cursor: pointer;
              padding: 2px 6px;
              position: absolute;
              bottom: 8px;
              left: 16px;
            }
            .ghost-btn:hover { color: #c8902a; }
            .memory-gate-body {
              padding: 12px 16px 0;
              display: flex;
              flex-direction: column;
              gap: 10px;
            }
            .memory-gate-actions {
              display: grid;
              grid-template-columns: 1fr 1fr 1fr;
              gap: 6px;
            }
            .memory-gate-actions button {
              padding: 9px 6px;
              font-size: 13px;
              font-family: inherit;
              font-weight: 600;
              color: #a08858;
              background:
                linear-gradient(180deg, #2e2010 0%, #201408 60%, #2a1c0c 100%);
              border: 1px solid #5a3c18;
              border-radius: 3px;
              cursor: pointer;
              letter-spacing: 0.05em;
              box-shadow: inset 0 1px 0 rgba(255,200,100,.08), 0 2px 4px rgba(0,0,0,.5);
              transition: all .15s;
              position: relative;
              overflow: hidden;
            }
            .memory-gate-actions button::after {
              content: '';
              position: absolute;
              inset: 0;
              background: linear-gradient(180deg, rgba(255,200,80,.05) 0%, transparent 50%);
              pointer-events: none;
            }
            .memory-gate-actions button:hover {
              border-color: #8a6030;
              color: #c8a868;
            }
            .memory-gate-actions button.active {
              background: linear-gradient(180deg, #5a3a10 0%, #3e2608 60%, #4a3010 100%);
              border-color: #c8902a;
              color: #e8c060;
              box-shadow: inset 0 1px 0 rgba(255,200,80,.2), 0 0 12px rgba(200,144,42,.25);
              text-shadow: 0 0 8px rgba(255,200,80,.4);
            }
            .memory-gate-check {
              display: flex;
              align-items: center;
              gap: 8px;
              color: #887050;
              font-size: 12px;
              cursor: pointer;
            }
            .memory-gate-check input { display: none; }
            .rune-mark {
              font-size: 15px;
              color: #c8902a;
              line-height: 1;
              opacity: 0.8;
            }
            .rune-mark.checked { opacity: 1; color: #e8b840; }
            .gate-draft-row {
              display: flex;
              align-items: stretch;
              gap: 6px;
              height: 38px;
            }
            .gate-draft-btn {
              padding: 0 14px;
              font-size: 12px;
              font-family: inherit;
              color: #c8a060;
              background: linear-gradient(180deg, #2e2010 0%, #1e1408 100%);
              border: 1px solid #6a4820;
              border-radius: 3px;
              cursor: pointer;
              white-space: nowrap;
              box-shadow: inset 0 1px 0 rgba(255,200,80,.06);
              transition: border-color .15s;
              flex-shrink: 0;
            }
            .gate-draft-btn:hover { border-color: #c8902a; }
            .gate-parchment {
              flex: 1;
              display: flex;
              align-items: center;
              padding: 0 12px;
              font-size: 12px;
              color: #6a5030;
              background: linear-gradient(180deg, #2a2010 0%, #1e1808 100%);
              border: 1px solid #4a3010;
              border-radius: 3px;
              box-shadow: inset 0 2px 6px rgba(0,0,0,.4);
              background-image:
                repeating-linear-gradient(
                  0deg,
                  transparent,
                  transparent 18px,
                  rgba(80,50,10,.08) 18px,
                  rgba(80,50,10,.08) 19px
                );
              overflow: hidden;
            }
            .gate-parchment span { color: #a08858; }
            .memory-role-grid {
              display: flex;
              flex-direction: column;
              gap: 0;
            }
            .memory-role-row {
              padding: 10px 0 8px;
              border-bottom: 1px solid #3a2810;
            }
            .memory-role-row:last-child { border-bottom: none; }
            .memory-role-row > label {
              display: block;
              margin: 0 0 6px;
              color: #c8a060;
              font-size: 13px;
              font-weight: 600;
              letter-spacing: 0.04em;
              padding-bottom: 5px;
              border-bottom: 1px solid #6a4820;
            }
            .memory-role-row select {
              width: 100%;
              margin: 0 0 6px;
              padding: 7px 32px 7px 10px;
              font-size: 12px;
              font-family: inherit;
              color: #a89060;
              background: linear-gradient(180deg, #261a08 0%, #1a1206 100%);
              border: 1px solid #4a3010;
              border-radius: 3px;
              appearance: none;
              -webkit-appearance: none;
              background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%23a08040' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");
              background-repeat: no-repeat;
              background-position: right 10px center;
              cursor: pointer;
              box-shadow: inset 0 1px 3px rgba(0,0,0,.4);
            }
            .memory-role-row select:focus {
              outline: none;
              border-color: #8a6030;
            }
            .memory-role-meta {
              display: grid;
              grid-template-columns: 46px 1fr;
              gap: 3px 8px;
            }
            .memory-role-meta span {
              color: #6a5030;
              font-size: 11px;
            }
            .memory-role-meta div {
              color: #887050;
              font-size: 12px;
              line-height: 1.5;
            }
            .gate-bottom-bar {
              display: flex;
              align-items: center;
              justify-content: space-between;
              padding: 10px 16px 12px;
              border-top: 1px solid #3a2810;
              margin-top: 2px;
              background: linear-gradient(180deg, rgba(15,10,4,.6) 0%, rgba(10,7,2,.8) 100%);
            }
            .gate-icon-row {
              display: flex;
              gap: 6px;
            }
            .gate-icon-btn {
              width: 40px;
              height: 40px;
              padding: 2px;
              background: #1e1408;
              border: 1px solid #4a3010;
              border-radius: 3px;
              cursor: pointer;
              overflow: hidden;
              transition: border-color .15s;
            }
            .gate-icon-btn:hover { border-color: #8a6030; }
            .gate-icon-btn img {
              width: 100%;
              height: 100%;
              object-fit: cover;
              display: block;
            }
            .gate-refresh-btn {
              padding: 8px 16px;
              font-size: 13px;
              font-family: inherit;
              font-weight: 600;
              color: #c8a060;
              background: linear-gradient(180deg, #302010 0%, #201408 100%);
              border: 1px solid #6a4820;
              border-radius: 3px;
              cursor: pointer;
              letter-spacing: 0.04em;
              box-shadow: inset 0 1px 0 rgba(255,200,80,.08);
              transition: all .15s;
            }
            .gate-refresh-btn:hover {
              border-color: #c8902a;
              color: #e8c060;
            }
          </style>
        </head>
        <body>
          <div class="shell">
            <aside class="sidebar">
              <div class="panel">
                <h1>Memlink Shrine</h1>
                <div class="sub">保留残影、汇合旧线、让后来者在回望时重新获得意义。</div>
                <div class="row" style="margin-top: 14px;">
                  <input id="searchInput" placeholder="搜索标题、摘要、对象、主题、客户、项目……" />
                </div>
                <div class="row">
                  <button onclick="loadCards()">搜索</button>
                  <button class="secondary" onclick="syncCards()">同步近30天</button>
                  <span class="status" id="syncStatus"></span>
                </div>
                <details style="margin-top: 12px;" open>
                  <summary>增强筛选，可选展开，不影响通用记忆</summary>
                  <div class="filter-mini">
                    <div>
                      <label>记忆范围</label>
                      <select id="filter_scope" onchange="loadCards()">
                        <option value="">全部记忆</option>
                        <option value="general">通用记忆</option>
                        <option value="enterprise">企业/客户相关</option>
                        <option value="personal">个人/学习相关</option>
                        <option value="system">系统设计相关</option>
                      </select>
                    </div>
                    <div class="grid-3">
                      <div>
                        <label>时间依据</label>
                        <select id="filter_time_basis" onchange="loadCards()">
                          <option value="">不限时间</option>
                          <option value="record">记录时间，北京时间</option>
                          <option value="content">内容时间线索，业务时间</option>
                        </select>
                      </div>
                      <div>
                        <label>年份</label>
                        <select id="filter_year" onchange="loadCards()">
                          <option value="">全部年份</option>
                          <option value="2026">2026</option>
                          <option value="2025">2025</option>
                          <option value="2024">2024</option>
                          <option value="2023">2023</option>
                        </select>
                      </div>
                      <div>
                        <label>总览时间标签</label>
                        <select id="filter_time_tag" onchange="syncTimeSelect('filter_time_tag')">
                          <option value="">不限制时间标签</option>
                          <option value="2026 4月">2026 4月</option>
                          <option value="2025 春季">2025 春季</option>
                          <option value="2024 圣诞">2024 圣诞</option>
                          <option value="2023 夏季">2023 夏季</option>
                          <option value="测试时间，占位">测试时间，占位</option>
                        </select>
                      </div>
                    </div>
                    <details>
                      <summary>企业字段筛选，只有查客户/公司内容时展开</summary>
                      <div class="filter-mini">
                        <div>
                          <label>客户</label>
                          <select id="filter_client" onchange="loadCards()">
                            <option value="">全部客户</option>
                            <option value="沃尔玛">沃尔玛 / Walmart</option>
                            <option value="ALDI">ALDI / 阿尔迪</option>
                            <option value="PB">PB</option>
                            <option value="山姆">山姆</option>
                          </select>
                        </div>
                        <div class="grid-2">
                          <div>
                            <label>风格</label>
                            <select id="filter_style" onchange="loadCards()">
                              <option value="">全部风格</option>
                              <option value="farmhouse">farmhouse</option>
                              <option value="modern">modern</option>
                              <option value="rustic">rustic</option>
                            </select>
                          </div>
                          <div>
                            <label>主题</label>
                            <select id="filter_theme" onchange="loadCards()">
                              <option value="">全部主题</option>
                              <option value="patriotic">patriotic</option>
                              <option value="lemon bee">lemon bee</option>
                              <option value="Christmas nutcracker">Christmas nutcracker</option>
                            </select>
                          </div>
                        </div>
                      </div>
                    </details>
                  </div>
                </details>
              </div>
              <div class="list" id="cardList"></div>
            </aside>

            <main class="main">
              <div class="layout">
                <section class="stack">
                  <div class="panel">
                    <h2>记忆卡编辑</h2>
                    <div class="sub">这里改的是“编目卡”，不是底层原始记忆。常用字段都做成中文表单了，只有高级治理结构保留 JSON。</div>

                    <div class="grid-2" style="margin-top: 14px;">
                      <div>
                        <label>标题</label>
                        <input id="title" placeholder="例如：Memlink Shrine 项目融合机制" />
                      </div>
                      <div>
                        <label>记忆子类型</label>
                        <input id="memory_subtype" placeholder="例如：系统架构规范" />
                      </div>
                    </div>

                    <div class="row">
                      <div style="width:100%;">
                        <label>事实摘要</label>
                        <textarea id="fact_summary" placeholder="这条记忆客观说了什么"></textarea>
                      </div>
                    </div>

                    <div class="row">
                      <div style="width:100%;">
                        <label>意义摘要</label>
                        <textarea id="meaning_summary" placeholder="这条记忆为什么重要、什么时候该用"></textarea>
                      </div>
                    </div>

                    <div class="grid-2 smallarea">
                      <div>
                        <label>姿态摘要</label>
                        <textarea id="posture_summary" placeholder="知情者第三者视角：这段路是怎么被走出来的"></textarea>
                      </div>
                      <div>
                        <label>情绪轨迹</label>
                        <textarea id="emotion_trajectory" placeholder="知情者第三者视角：信心、张力、犹豫或释然是怎么变化的"></textarea>
                      </div>
                    </div>

                    <div class="grid-3 smallarea">
                      <div>
                        <label>对象标签</label>
                        <textarea id="entity_tags" placeholder="多个值用中文逗号或英文逗号分隔"></textarea>
                      </div>
                      <div>
                        <label>主题标签</label>
                        <textarea id="topic_tags" placeholder="多个值用逗号分隔"></textarea>
                      </div>
                      <div>
                        <label>通用时间标签</label>
                        <select id="time_tags" onchange="syncTimeSelect('time_tags')">
                          <option value="">不限制时间标签</option>
                          <option value="2026 4月">2026 4月</option>
                          <option value="2025 春季">2025 春季</option>
                          <option value="2024 圣诞">2024 圣诞</option>
                          <option value="2023 夏季">2023 夏季</option>
                          <option value="测试时间，占位">测试时间，占位</option>
                        </select>
                      </div>
                    </div>

                    <div class="grid-3 smallarea">
                      <div>
                        <label>状态标签</label>
                        <textarea id="status_tags" placeholder="例如 已确认、探索中"></textarea>
                      </div>
                      <div>
                        <label>记忆主类型</label>
                        <select id="memory_type">
                          <option value="identity">身份背景</option>
                          <option value="project">项目推进</option>
                          <option value="client">客户历史</option>
                          <option value="decision">决策结论</option>
                          <option value="method">方法规范</option>
                          <option value="reflection">反思判断</option>
                        </select>
                      </div>
                      <div>
                        <label>核心适用范围</label>
                        <textarea id="scope_core" placeholder="例如 系统架构、当前项目"></textarea>
                      </div>
                    </div>

                    <div class="row tiny">
                      <div style="width:100%;">
                        <label>扩展适用范围</label>
                        <textarea id="scope_extra" placeholder="例如 记忆检索优化、跨聊天框召回"></textarea>
                      </div>
                    </div>
                  </div>

                  <div class="panel">
                    <h2>记忆脉络编码</h2>
                    <div class="sub">这一块是 v2 新主轴：标签负责定位，摘要负责确认，下面的主ID和上下游关系负责让 AI 看懂“从哪来、到哪去”。</div>
                    <div class="grid-3 smallarea" style="margin-top: 14px;">
                      <div>
                        <label>上游主ID</label>
                        <textarea id="upstream_main_ids" placeholder="多个上游用逗号或换行分隔"></textarea>
                      </div>
                      <div>
                        <label>主ID</label>
                        <input id="main_id" placeholder="例如 ML-RET-M00-MN-20260414-0007" />
                      </div>
                      <div>
                        <label>下游主ID</label>
                        <textarea id="downstream_main_ids" placeholder="多个下游用逗号或换行分隔"></textarea>
                      </div>
                    </div>
                    <div class="grid-3 smallarea">
                      <div>
                        <label>拓扑角色</label>
                        <select id="topology_role">
                          <option value="origin">原点</option>
                          <option value="junction">岔路</option>
                          <option value="node">节点</option>
                          <option value="merge">汇合点</option>
                          <option value="exit">出口</option>
                        </select>
                      </div>
                      <div>
                        <label>路径状态</label>
                        <select id="path_status">
                          <option value="active">仍有效</option>
                          <option value="dead_end">死路</option>
                          <option value="superseded">已被替代</option>
                          <option value="open_head">开放头 / 待续</option>
                          <option value="paused">暂停 / 断档待重连</option>
                        </select>
                      </div>
                      <div>
                        <label>关系类型</label>
                        <select id="relation_type">
                          <option value="unassigned">未编链</option>
                          <option value="originates">起点 / 首次提出</option>
                          <option value="continues">同链延续</option>
                          <option value="derived_from">由上游衍生</option>
                          <option value="parallel_same">同议题同观点并行</option>
                          <option value="deepens">继续深入 / 下钻</option>
                          <option value="branches_to">形成分叉</option>
                          <option value="refines">修正/细化</option>
                          <option value="blocks">阻断/否定</option>
                          <option value="merges_to">汇合</option>
                          <option value="resumes_from">断档重连</option>
                        </select>
                      </div>
                    </div>
                    <div class="grid-3 smallarea">
                      <div>
                        <label>思考光标锚点</label>
                        <input id="focus_anchor_main_id" placeholder="当前新残影默认接在哪个节点之后" />
                      </div>
                      <div>
                        <label>光标置信度</label>
                        <input id="focus_confidence" type="number" min="0" max="1" step="0.01" />
                      </div>
                      <div>
                        <label>光标说明</label>
                        <input id="focus_reason" placeholder="为什么接这条线，而不是并行的另一条线" />
                      </div>
                    </div>
                    <div class="checkbox">
                      <input id="is_landmark" type="checkbox" />
                      <span>这是地标记忆，默认脉络召回时可以优先展示</span>
                    </div>
                    <div class="grid-3 smallarea">
                      <div>
                        <label>链路作者</label>
                        <input id="chain_author" placeholder="例如 codex / claude-code / human" />
                      </div>
                      <div>
                        <label>作者角色</label>
                        <select id="chain_author_role">
                          <option value="none">未指定</option>
                          <option value="witness_model">知情者模型</option>
                          <option value="human">人工修理</option>
                          <option value="assistant_suggestion">外部模型建议</option>
                        </select>
                      </div>
                      <div>
                        <label>链路状态</label>
                        <select id="chain_status">
                          <option value="unassigned">未编链</option>
                          <option value="suggested">仅建议</option>
                          <option value="witness_confirmed">知情者确认</option>
                          <option value="human_confirmed">人工确认</option>
                        </select>
                      </div>
                    </div>
                    <div class="row tiny">
                      <div style="width:100%;">
                        <label>链路置信度</label>
                        <input id="chain_confidence" type="number" min="0" max="1" step="0.01" />
                      </div>
                    </div>
                    <details style="margin-top: 12px;">
                      <summary>正文层 / 原文层（渐进展开用）</summary>
                      <div class="row" style="margin-top: 12px;">
                        <div style="width:100%;">
                          <label>正文层</label>
                          <textarea id="body_text" placeholder="第一次显式深挖时展示的浓缩正文，不是原文复制"></textarea>
                        </div>
                      </div>
                      <div class="row">
                        <div style="width:100%;">
                          <label>原文层</label>
                          <textarea id="raw_text" placeholder="最后一级才读取的底层原文。OpenMemory 同步来的原文会保存在这里，谨慎修改。"></textarea>
                        </div>
                      </div>
                    </details>
                  </div>

                  <div class="panel">
                    <h2>来源与并行写入规则</h2>
                    <div class="sub">中间层只记录来源事实，不自动覆盖，也不替知情者模型做语义裁决。多前端并行时默认 append-only，关系类型由知情者模型判断。</div>
                    <div class="grid-2 smallarea" style="margin-top: 14px;">
                      <div>
                        <label>记忆来源前端</label>
                        <input id="src_frontend" placeholder="例如 codex / claude_code / hermes / openclaw" />
                      </div>
                      <div>
                        <label>记忆来源主机</label>
                        <input id="src_host" placeholder="例如 codex-desktop / cc-laptop" />
                      </div>
                    </div>
                    <div class="grid-2 smallarea">
                      <div>
                        <label>记忆来源线程</label>
                        <input id="src_thread" placeholder="例如 同一个项目线程名" />
                      </div>
                      <div>
                        <label>记忆来源会话</label>
                        <input id="src_session" placeholder="例如 session / thread id" />
                      </div>
                    </div>
                    <div class="grid-3 smallarea">
                      <div>
                        <label>写入方式</label>
                        <select id="src_write_mode">
                          <option value="">未指定</option>
                          <option value="manual">manual</option>
                          <option value="passive">passive</option>
                          <option value="auto">auto</option>
                        </select>
                      </div>
                      <div>
                        <label>来源角色</label>
                        <select id="src_source_role">
                          <option value="">未指定</option>
                          <option value="witness_model">witness_model</option>
                          <option value="human">human</option>
                          <option value="assistant_suggestion">assistant_suggestion</option>
                        </select>
                      </div>
                      <div>
                        <label>并行写入规则</label>
                        <select id="src_parallel_rule">
                          <option value="append_only_branching">append_only_branching</option>
                        </select>
                      </div>
                    </div>
                    <div class="row tiny">
                      <div style="width:100%;">
                        <label>协作关系备注</label>
                        <textarea id="src_relation_note" placeholder="例如：CC 不同意 Codex 的 A 方案，改走 B；或：这是对 Codex 观点的继续深入。"></textarea>
                      </div>
                    </div>
                  </div>

                  <div class="panel">
                    <div class="divider-title">
                      <div>
                        <h2>领域维度包，可选增强</h2>
                        <div class="sub">非公司记忆可以不挂企业包。只有客户/项目/产品等业务记忆才展开填写。</div>
                      </div>
                      <span class="tag">不会替代通用记忆</span>
                    </div>

                    <div class="grid-2" style="margin-top: 14px;">
                      <div>
                        <label>当前领域包</label>
                        <select id="facet_pack_id_ui">
                          <option value="">无，通用/系统设计记忆</option>
                          <option value="enterprise">enterprise_v1，企业/客户记忆</option>
                        </select>
                      </div>
                      <div>
                        <label>领域包说明</label>
                        <input id="facet_pack_summary" value="当前卡片默认按通用记忆展示，只有需要时再挂企业维度。" />
                      </div>
                    </div>

                    <details style="margin-top: 12px;" open>
                      <summary>enterprise_v1 企业字段，只有企业记忆需要展开</summary>
                      <div class="hint-box" style="margin-top: 12px;">
                        这里先做 demo 形态：客户和时间先用下拉框表达“可选维度”。具体客户名单、时间颗粒度和标签内容后面可以反复调整。
                      </div>
                      <div class="grid-3 smallarea">
                        <div>
                          <label>客户</label>
                          <select id="ent_clients">
                            <option value="">未选择客户</option>
                            <option value="沃尔玛">沃尔玛 / Walmart</option>
                            <option value="ALDI">ALDI / 阿尔迪</option>
                            <option value="PB">PB</option>
                            <option value="山姆">山姆</option>
                            <option value="测试客户，占位">测试客户，占位</option>
                          </select>
                        </div>
                        <div><label>项目</label><textarea id="ent_projects" placeholder="例如 客户研究、图片标注"></textarea></div>
                        <div><label>产品/品类</label><textarea id="ent_products" placeholder="例如 家居软装、节庆摆件"></textarea></div>
                      </div>
                      <div class="grid-3 smallarea">
                        <div><label>风格</label><textarea id="ent_style" placeholder="例如 farmhouse、modern、rustic"></textarea></div>
                        <div><label>主题</label><textarea id="ent_theme" placeholder="例如 patriotic、lemon bee、nutcracker"></textarea></div>
                        <div>
                          <label>业务时间/季节/节庆</label>
                          <select id="ent_season" onchange="syncTimeSelect('ent_season')">
                            <option value="">未选择业务时间</option>
                            <option value="2026 4月">2026 4月</option>
                            <option value="2025 春季">2025 春季</option>
                            <option value="2024 圣诞">2024 圣诞</option>
                            <option value="2023 夏季">2023 夏季</option>
                            <option value="测试时间，占位">测试时间，占位</option>
                          </select>
                        </div>
                      </div>
                      <div class="grid-3 smallarea">
                        <div><label>流程节点</label><textarea id="ent_stage" placeholder="例如 分析、标注、复盘"></textarea></div>
                        <div><label>部门/角色</label><textarea id="ent_role" placeholder="例如 AI产品经理、设计部、客户"></textarea></div>
                        <div><label>文档/资产类型</label><textarea id="ent_asset" placeholder="例如 趋势文件、图片、报告"></textarea></div>
                      </div>
                      <div class="grid-3 smallarea">
                        <div><label>目标/约束</label><textarea id="ent_goal" placeholder="例如 小批量测试、先验证结果价值"></textarea></div>
                      </div>
                    </details>

                    <details style="margin-top: 12px;">
                      <summary>添加/调整维度，v3 重投影预留，当前只做入口</summary>
                      <div class="muted-block" style="margin-top: 12px;">
                        已存在子维度的值可以在当前卡片里立刻增删改；新增“字段定义”或删除整个子维度本身，才进入 v3 的重投影流程。
                      </div>
                    </details>
                  </div>

                  <div class="panel">
                    <h2>治理维度</h2>
                    <div class="grid-3" style="margin-top: 14px;">
                      <div>
                        <label>开合状态</label>
                        <select id="shelf_state">
                          <option value="open">打开</option>
                          <option value="half_open">半打开</option>
                          <option value="closed">封存</option>
                        </select>
                      </div>
                      <div>
                        <label>重要性</label>
                        <select id="importance">
                          <option value="pinned">钉住</option>
                          <option value="high">高</option>
                          <option value="normal">普通</option>
                          <option value="low">低</option>
                        </select>
                      </div>
                      <div>
                        <label>置信度</label>
                        <input id="confidence" type="number" min="0" max="1" step="0.01" />
                      </div>
                    </div>

                    <div class="checkbox">
                      <input id="pinned" type="checkbox" />
                      <span>钉住这条记忆，不让它轻易降级</span>
                    </div>

                    <div class="row">
                      <div style="width:100%;">
                        <label>升级规则说明</label>
                        <textarea id="promotion_rule_text"></textarea>
                      </div>
                    </div>

                    <div class="row">
                      <div style="width:100%;">
                        <label>降级规则说明</label>
                        <textarea id="degradation_rule_text"></textarea>
                      </div>
                    </div>

                    <div class="row">
                      <div style="width:100%;">
                        <label>判定理由</label>
                        <textarea id="rationale"></textarea>
                      </div>
                    </div>

                    <details>
                      <summary>高级治理结构（一般不用改，留给以后进 v3）</summary>
                      <div class="row" style="margin-top: 12px;">
                        <div style="width:100%;">
                          <label>高级治理结构（JSON）</label>
                          <textarea id="advanced_governance" placeholder="promotion_signals / degradation_signals / reactivation_rule"></textarea>
                        </div>
                      </div>
                    </details>

                    <div class="row" style="margin-top: 14px;">
                      <button onclick="saveCard()">保存卡片</button>
                      <span class="status" id="saveStatus"></span>
                    </div>
                  </div>
                </section>

                <section class="stack">
                  <div class="panel">
                    <h2>记忆理解简报测试</h2>
                    <div class="sub">这里是 Memlink 的召回简报入口。AI 可以把自然语言拆成结构化条件，再按当前的记忆层去回望与取证。</div>
                    <div class="row" style="margin-top: 14px;">
                      <textarea id="question" placeholder="例如：回忆一下我们是如何把旧项目汇合成 Memlink Shrine 的"></textarea>
                    </div>
                    <div class="row">
                      <button onclick="runBrief()">生成简报</button>
                      <span class="status" id="briefStatus"></span>
                    </div>
                    <div class="brief-box" id="briefOutput">等待运行...</div>
                  </div>

                  <div class="panel">
                    <h2>当前选中卡片</h2>
                    <div class="detail-box" id="detailOutput">请选择左侧的一张记忆卡。</div>
                    <div class="graph-toolbar">
                      <strong>当前图谱视图</strong>
                      <div class="row" style="margin-bottom: 0;">
                        <button class="ghost" onclick="loadGraph('local')">残影导航图</button>
                        <button class="ghost" onclick="loadGraph('full')">项目导航图</button>
                        <button class="ghost" onclick="loadGraph('vcp')">VCP 联想图</button>
                      </div>
                    </div>
                    <div class="graph-box">
                      <div class="graph-status" id="graphStatus">默认展示当前记忆上下游 2 步的残影导航图。</div>
                      <div class="graph-scroll">
                        <svg id="graphCanvas" width="100%" height="520" viewBox="0 0 760 520" preserveAspectRatio="xMinYMin meet"></svg>
                      </div>
                      <div class="graph-legend">
                        <span class="legend-pill legend-current">当前记忆</span>
                        <span class="legend-pill legend-origin">原点 / 种子</span>
                        <span class="legend-pill legend-normal">残影延申记忆</span>
                        <span class="legend-pill legend-assoc">VCP 联想结果</span>
                        <span class="legend-pill legend-special">特殊记忆（死路 / 待续 / 地标 / 关键）</span>
                        <span class="legend-pill legend-reconnect">虚线边 = 断档重连（已接上）</span>
                      </div>
                      <div class="muted-block" id="mechanismOutput" style="margin-top: 12px;">这里会显示当前卡片的思考光标与断档重连信息。</div>
                    </div>
                  </div>
                </section>
              </div>
            </main>
          </div>

          <script>
            let currentId = null;
            let currentCard = null;
            const graphView = {
              scale: 1,
              panX: 0,
              panY: 0,
              dragging: false,
              dragStartX: 0,
              dragStartY: 0,
              statusBase: '',
              signature: ''
            };
            let currentGraphMeta = null;
            let sessionMemoryGateState = { mode: 'passive', confirm_before_write: true };
            let suppressGateClick = false;

            const gateHints = {
              off: '熄火：只暂停写入；读取层仍在线，可随时调取记忆。',
              passive: '被动写入：读取层已接入；只有你明确说“记住、写入、存起来”等口令时才触发。',
              auto: '自动写入：按阶段、轮数或 token 阈值自动整理残影草稿，并按写入机制进入记忆层。'
            };

            function gateModeLabel(mode) {
              return { off: '熄火', passive: '被动写入', ask: '被动写入', auto: '自动写入' }[mode] || '熄火';
            }

            const memoryGateRoleDom = {
              witness_model: {
                select: 'gateWitnessSelect',
                position: 'gateWitnessPosition',
                responsibility: 'gateWitnessResponsibility',
                fallback: {
                  current: '由现场协作模型声明，例如 Codex / Claude',
                  candidates: ['由现场协作模型声明，例如 Codex / Claude'],
                  position: '对话现场与直写入口',
                  responsibility: '负责把当前讨论整理成残影草稿，判断这次该不该写、写哪几点；它是现场知情者，不负责底层联想召回。'
                }
              },
              admin_model: {
                select: 'gateAdminSelect',
                position: 'gateAdminPosition',
                responsibility: 'gateAdminResponsibility',
                fallback: {
                  current: '未配置',
                  candidates: ['未配置'],
                  position: '标准层与治理校验',
                  responsibility: '负责四摘要、标签、领域包、链路说明和质量校验；帮助整理记忆对象，但不替知情者决定写入意图，也不替 VCP 做联想。'
                }
              },
              embedding_model: {
                select: 'gateEmbeddingSelect',
                position: 'gateEmbeddingPosition',
                responsibility: 'gateEmbeddingResponsibility',
                fallback: {
                  current: '当前底层召回引擎',
                  candidates: ['当前底层召回引擎'],
                  position: '召回层与联想层',
                  responsibility: '负责底层召回、相近记忆激活与联想；Memlink 只做标准化写入与投递，真正召回使用这里选中的底层 memory 引擎。'
                }
              },
              engine_embedding_model: {
                select: 'gateEngineEmbeddingSelect',
                position: 'gateEngineEmbeddingPosition',
                responsibility: 'gateEngineEmbeddingResponsibility',
                fallback: {
                  current: '未配置联想引擎 embedding 模型',
                  candidates: ['未配置联想引擎 embedding 模型'],
                  position: '联想引擎内部向量化配置',
                  responsibility: '这是底层联想引擎自己用于向量化与相似检索的 embedding 模型，不属于 Memlink Core。本层只展示与记录当前底层引擎的 embedding 配置。'
                }
              }
            };

            function normalizeRoleEntry(entry, fallback) {
              if (entry && typeof entry === 'object' && !Array.isArray(entry)) {
                const candidates = Array.isArray(entry.candidates) && entry.candidates.length
                  ? entry.candidates.map(v => String(v || '').trim()).filter(Boolean)
                  : [String(entry.current || fallback.current || '未配置')];
                return {
                  current: String(entry.current || candidates[0] || fallback.current || '未配置'),
                  candidates,
                  position: String(entry.position || fallback.position || ''),
                  responsibility: String(entry.responsibility || fallback.responsibility || '')
                };
              }
              const value = String(entry || fallback.current || '未配置');
              return {
                current: value,
                candidates: [value],
                position: fallback.position || '',
                responsibility: fallback.responsibility || ''
              };
            }

            function currentSelectedModels() {
              const selected = { ...(sessionMemoryGateState.selected_models || {}) };
              Object.entries(memoryGateRoleDom).forEach(([key, dom]) => {
                const value = document.getElementById(dom.select)?.value;
                if (value) selected[key] = value;
              });
              return selected;
            }

            function fillModelRole(key, rawEntry) {
              const dom = memoryGateRoleDom[key];
              if (!dom) return;
              const entry = normalizeRoleEntry(rawEntry, dom.fallback);
              const selected = sessionMemoryGateState.selected_models?.[key] || entry.current;
              const select = document.getElementById(dom.select);
              if (select) {
                select.innerHTML = '';
                const options = entry.candidates.includes(selected) ? entry.candidates : [selected, ...entry.candidates];
                options.forEach(value => {
                  const option = document.createElement('option');
                  option.value = value;
                  option.textContent = value;
                  select.appendChild(option);
                });
                select.value = selected;
              }
              document.getElementById(dom.position).textContent = entry.position || '未定义';
              document.getElementById(dom.responsibility).textContent = entry.responsibility || '未定义';
            }

            function applySessionMemoryGate(state) {
              sessionMemoryGateState = state || { mode: 'off', confirm_before_write: true };
              const mode = sessionMemoryGateState.mode || 'off';
              const gate = document.getElementById('memoryGate');
              if (gate) {
                gate.classList.remove('gate-off', 'gate-ask', 'gate-passive', 'gate-auto');
                gate.classList.add(`gate-${mode}`);
              }
              document.getElementById('memoryGateLabel').textContent = gateModeLabel(mode);
              document.getElementById('memoryGateHint').textContent = gateHints[mode] || gateHints.off;
              document.getElementById('memoryGateConfirm').checked = !!sessionMemoryGateState.confirm_before_write;
              ['Off', 'Passive', 'Auto'].forEach(name => {
                const button = document.getElementById(`gateMode${name}`);
                if (button) button.classList.remove('active');
              });
              const activeButton = document.getElementById(`gateMode${mode === 'off' ? 'Off' : mode === 'auto' ? 'Auto' : 'Passive'}`);
              if (activeButton) activeButton.classList.add('active');
              const roles = sessionMemoryGateState.model_roles || {};
              fillModelRole('witness_model', roles.witness_model);
              fillModelRole('admin_model', roles.admin_model);
              fillModelRole('embedding_model', roles.embedding_model);
              fillModelRole('engine_embedding_model', roles.engine_embedding_model);
              document.getElementById('memoryGateUpdated').textContent = `状态更新时间：${北京时间(sessionMemoryGateState.updated_at) || '未记录'}`;
            }

            async function loadSessionMemoryGate() {
              const res = await fetch('/api/session-memory-gate');
              const state = await res.json();
              applySessionMemoryGate(state);
            }

            async function setSessionMemoryGateMode(mode) {
              const confirm = document.getElementById('memoryGateConfirm')?.checked ?? true;
              const res = await fetch('/api/session-memory-gate', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode, confirm_before_write: confirm, selected_models: currentSelectedModels() })
              });
              const state = await res.json();
              applySessionMemoryGate(state);
            }

            function saveCurrentGateMode() {
              setSessionMemoryGateMode(sessionMemoryGateState.mode || 'off');
            }

            function toggleSessionMemoryFire() {
              const mode = sessionMemoryGateState.mode || 'off';
              setSessionMemoryGateMode(mode === 'off' ? 'passive' : 'off');
            }

            function toggleMemoryGatePanel(force) {
              const gate = document.getElementById('memoryGate');
              if (!gate) return;
              const open = typeof force === 'boolean' ? force : !gate.classList.contains('open');
              gate.classList.toggle('open', open);
            }

            function restoreMemoryGatePosition() {
              const gate = document.getElementById('memoryGate');
              if (!gate) return;
              try {
                const saved = JSON.parse(localStorage.getItem('memoryGatePosition') || '{}');
                if (Number.isFinite(saved.left) && Number.isFinite(saved.top)) {
                  const rect = gate.getBoundingClientRect();
                  const safeLeft = Math.max(8, Math.min(window.innerWidth - rect.width - 8, saved.left));
                  const safeTop = Math.max(8, Math.min(window.innerHeight - rect.height - 8, saved.top));
                  gate.style.left = `${safeLeft}px`;
                  gate.style.top = `${safeTop}px`;
                  gate.style.right = 'auto';
                  gate.style.bottom = 'auto';
                  localStorage.setItem('memoryGatePosition', JSON.stringify({ left: safeLeft, top: safeTop }));
                }
              } catch {}
            }

            function attachMemoryGateInteractions() {
              const gate = document.getElementById('memoryGate');
              const arrow = document.getElementById('memoryGateArrow');
              const dragHead = document.getElementById('memoryGateDrag');
              if (!gate || !dragHead) return;
              restoreMemoryGatePosition();
              let dragging = false;
              let moved = false;
              let startX = 0;
              let startY = 0;
              let startLeft = 0;
              let startTop = 0;

              function start(event) {
                if (event.button !== 0) return;
                if (event.currentTarget === dragHead && event.target.closest('button, select, input, textarea')) return;
                dragging = true;
                moved = false;
                const rect = gate.getBoundingClientRect();
                startX = event.clientX;
                startY = event.clientY;
                startLeft = rect.left;
                startTop = rect.top;
                gate.classList.add('dragging');
                document.addEventListener('pointermove', move);
                document.addEventListener('pointerup', stop, { once: true });
              }

              function move(event) {
                if (!dragging) return;
                const dx = event.clientX - startX;
                const dy = event.clientY - startY;
                if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
                const rect = gate.getBoundingClientRect();
                const nextLeft = Math.max(8, Math.min(window.innerWidth - rect.width - 8, startLeft + dx));
                const nextTop = Math.max(8, Math.min(window.innerHeight - 60, startTop + dy));
                gate.style.left = `${nextLeft}px`;
                gate.style.top = `${nextTop}px`;
                gate.style.right = 'auto';
                gate.style.bottom = 'auto';
              }

              function stop() {
                dragging = false;
                gate.classList.remove('dragging');
                document.removeEventListener('pointermove', move);
                const rect = gate.getBoundingClientRect();
                localStorage.setItem('memoryGatePosition', JSON.stringify({ left: rect.left, top: rect.top }));
                if (moved) {
                  suppressGateClick = true;
                  setTimeout(() => { suppressGateClick = false; }, 50);
                }
              }

              dragHead.addEventListener('pointerdown', start);
              if (arrow) {
                arrow.addEventListener('click', () => toggleMemoryGatePanel());
              }
              window.addEventListener('resize', restoreMemoryGatePosition);
            }

            function splitList(text) {
              return String(text || '')
                .split(/[，,\\n]/)
                .map(v => v.trim())
                .filter(Boolean);
            }

            function joinList(values) {
              return Array.isArray(values) ? values.join('，') : '';
            }

            function firstValue(value) {
              if (Array.isArray(value)) {
                return String(value[0] || '').trim();
              }
              return String(value || '').trim();
            }

            function 图谱状态文本(base) {
              return `${base} | 缩放：${graphScaleText()} | 拖拽：按住鼠标移动`;
            }

            function 更新图谱状态(base) {
              const graphStatus = document.getElementById('graphStatus');
              if (!graphStatus) return;
              if (base) graphView.statusBase = base;
              graphStatus.textContent = 图谱状态文本(graphView.statusBase || '残影导航图');
            }

            function 图谱标签行(text, maxChars = 14) {
              const normalized = String(text || '').trim();
              if (!normalized) return ['未命名记忆'];
              const lines = [];
              for (let index = 0; index < normalized.length; index += maxChars) {
                lines.push(normalized.slice(index, index + maxChars));
              }
              return lines.length ? lines : ['未命名记忆'];
            }

            function singleValueList(value) {
              const text = String(value || '').trim();
              return text ? [text] : [];
            }

            function sameList(a, b) {
              const left = (Array.isArray(a) ? a : []).map(v => String(v || '').trim()).filter(Boolean);
              const right = (Array.isArray(b) ? b : []).map(v => String(v || '').trim()).filter(Boolean);
              if (left.length !== right.length) return false;
              return left.every((value, index) => value === right[index]);
            }

            function chainFieldsChanged(payload, card) {
              if (!card) return false;
              if ((payload.main_id || '') !== (card.main_id || '')) return true;
              if (!sameList(payload.upstream_main_ids, card.upstream_main_ids || [])) return true;
              if (!sameList(payload.downstream_main_ids, card.downstream_main_ids || [])) return true;
              if ((payload.relation_type || 'unassigned') !== (card.relation_type || 'unassigned')) return true;
              if ((payload.topology_role || 'node') !== (card.topology_role || 'node')) return true;
              if ((payload.path_status || 'active') !== (card.path_status || 'active')) return true;
              if ((payload.focus_anchor_main_id || '') !== (card.focus_anchor_main_id || '')) return true;
              if (Number(payload.focus_confidence || 0) !== Number(card.focus_confidence || 0)) return true;
              if ((payload.focus_reason || '') !== (card.focus_reason || '')) return true;
              if (!!payload.is_landmark !== !!card.is_landmark) return true;
              return false;
            }

            function setSelectValue(id, rawValue, fallbackPrefix = '历史值：') {
              const select = document.getElementById(id);
              if (!select) return;
              const value = firstValue(rawValue);
              if (!value) {
                select.value = '';
                return;
              }
              const exists = Array.from(select.options).some(option => option.value === value);
              if (!exists) {
                const option = document.createElement('option');
                option.value = value;
                option.textContent = `${fallbackPrefix}${value}`;
                select.appendChild(option);
              }
              select.value = value;
            }

            function currentFilters() {
              return {
                memory_scope: document.getElementById('filter_scope')?.value || '',
                time_basis: document.getElementById('filter_time_basis')?.value || '',
                year: document.getElementById('filter_year')?.value || '',
                time_tag: document.getElementById('filter_time_tag')?.value || '',
                client: document.getElementById('filter_client')?.value || '',
                style: document.getElementById('filter_style')?.value || '',
                theme: document.getElementById('filter_theme')?.value || ''
              };
            }

            function buildCardsUrl() {
              const params = new URLSearchParams();
              params.set('limit', '80');
              const query = document.getElementById('searchInput').value.trim();
              if (query) params.set('query', query);
              Object.entries(currentFilters()).forEach(([key, value]) => {
                if (value) params.set(key, value);
              });
              return `/api/cards?${params.toString()}`;
            }

            function syncTimeSelect(sourceId) {
              const source = document.getElementById(sourceId);
              if (!source) return;
              const value = source.value || '';
              ['filter_time_tag', 'time_tags', 'ent_season'].forEach(id => {
                if (id === sourceId) return;
                setSelectValue(id, value, '同步值：');
              });
              loadCards();
            }

            function 状态中文(value) {
              return { open: '打开', half_open: '半打开', closed: '封存' }[value] || value || '';
            }

            function 重要性中文(value) {
              return { pinned: '钉住', high: '高', normal: '普通', low: '低' }[value] || value || '';
            }

            function 路径状态中文(value) {
              return {
                active: '仍有效',
                dead_end: '死路',
                superseded: '已被替代',
                open_head: '开放头 / 待续',
                paused: '暂停 / 断档待重连'
              }[value] || value || '';
            }

            function 北京时间(value) {
              if (!value) return '';
              const date = new Date(value);
              if (Number.isNaN(date.getTime())) return value;
              const parts = new Intl.DateTimeFormat('zh-CN', {
                timeZone: 'Asia/Shanghai',
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false
              }).formatToParts(date).reduce((acc, part) => {
                acc[part.type] = part.value;
                return acc;
              }, {});
              return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second} 北京时间`;
            }

            function escapeHtml(str) {
              return String(str || '')
                .replaceAll('&', '&amp;')
                .replaceAll('<', '&lt;')
                .replaceAll('>', '&gt;')
                .replaceAll('"', '&quot;');
            }

            function 卡片详情文本(card) {
              const enterprise = card.domain_facets?.enterprise || {};
              const sourceMeta = card.domain_facets?.memory_source || {};
              const gov = card.governance || {};
              const styleValues = enterprise['风格'] || enterprise['风格/主题'] || [];
              const themeValues = enterprise['主题'] || [];
              const facetPack = card.facet_pack_id ? `${card.facet_pack_id}:${card.facet_pack_version || ''}` : '无，通用/系统设计记忆';
              return [
                `标题：${card.title || ''}`,
                `事实摘要：${card.fact_summary || ''}`,
                `意义摘要：${card.meaning_summary || ''}`,
                `姿态摘要：${card.posture_summary || ''}`,
                `情绪轨迹：${card.emotion_trajectory || ''}`,
                '',
                `领域包：${facetPack}`,
                `原始记忆创建时间：${北京时间(card.raw_memory_created_at)}`,
                `编目生成时间：${北京时间(card.projection_created_at)}`,
                `卡片更新时间：${北京时间(card.updated_at)}`,
                `最近访问时间：${北京时间(gov.last_accessed_at)}`,
                `最近强化时间：${北京时间(gov.last_reinforced_at)}`,
                '',
                `对象标签：${joinList(card.base_facets?.entity)}`,
                `主题标签：${joinList(card.base_facets?.topic)}`,
                `内容时间线索：${joinList(card.base_facets?.time)}`,
                `状态标签：${joinList(card.base_facets?.status)}`,
                `记忆主类型：${card.base_facets?.memory_type || ''}`,
                `记忆子类型：${card.base_facets?.memory_subtype || ''}`,
                `核心适用范围：${joinList(card.base_facets?.relevance_scope_core)}`,
                `扩展适用范围：${joinList(card.base_facets?.relevance_scope_extra)}`,
                '',
                `客户：${joinList(enterprise['客户'])}`,
                `项目：${joinList(enterprise['项目'])}`,
                `产品/品类：${joinList(enterprise['产品/品类'])}`,
                `风格：${joinList(styleValues)}`,
                `主题：${joinList(themeValues)}`,
                `时间/季节/节庆：${joinList(enterprise['时间/季节/节庆'])}`,
                `流程节点：${joinList(enterprise['流程节点'])}`,
                `部门/角色：${joinList(enterprise['部门/角色'])}`,
                `目标/约束：${joinList(enterprise['目标/约束'])}`,
                `文档/资产类型：${joinList(enterprise['文档/资产类型'])}`,
                '',
                `记忆来源前端：${sourceMeta.frontend || ''}`,
                `记忆来源主机：${sourceMeta.host || ''}`,
                `记忆来源线程：${sourceMeta.thread || ''}`,
                `记忆来源会话：${sourceMeta.session || ''}`,
                `写入方式：${sourceMeta.write_mode || ''}`,
                `来源角色：${sourceMeta.source_role || ''}`,
                `并行写入规则：${sourceMeta.parallel_rule || ''}`,
                `协作关系备注：${sourceMeta.relation_note || ''}`,
                '',
                `开合状态：${状态中文(gov.shelf_state)}`,
                `重要性：${重要性中文(gov.importance)}`,
                `是否钉住：${gov.pinned ? '是' : '否'}`,
                `置信度：${gov.confidence ?? ''}`,
                `升级规则：${gov.promotion_rule_text || ''}`,
                `降级规则：${gov.degradation_rule_text || ''}`,
                `判定理由：${gov.rationale || ''}`,
                '',
                `主ID：${card.main_id || ''}`,
                `上游主ID：${joinList(card.upstream_main_ids)}`,
                `下游主ID：${joinList(card.downstream_main_ids)}`,
                `关系类型：${card.relation_type || ''}`,
                `拓扑角色：${card.topology_role || ''}`,
                `路径状态：${路径状态中文(card.path_status)}`,
                `思考光标锚点：${card.focus_anchor_main_id || ''}`,
                `光标置信度：${card.focus_confidence ?? ''}`,
                `光标说明：${card.focus_reason || ''}`,
              ].join('\\n');
            }

            function 项目名(card) {
              return card.project_root || firstValue(card.project_path) || card.project_source_name || '未归属项目';
            }

            function 子项目名(card) {
              return card.project_subproject || '';
            }

            function 链路排序值(card) {
              const prefixOrder = {
                R: 10,
                M: 20,
                B: 30,
                C: 40,
                D: 50,
                J: 60,
                A: 80,
                S: 90
              };
              const roleOrder = {
                origin: 5,
                junction: 15,
                node: 25,
                merge: 35,
                exit: 95
              };
              let value = roleOrder[card.topology_role || 'node'] || 25;
              const prefixMatch = String(card.main_id || '').match(/-([RMSABCDJ])(\\d+)/);
              if (prefixMatch) {
                value = (prefixOrder[prefixMatch[1]] || value) + Number(prefixMatch[2]) / 100;
              }
              if (card.is_landmark) value += 5;
              if (card.path_status === 'open_head') value -= 3;
              if (card.path_status === 'paused') value -= 1;
              if (card.path_status === 'dead_end') value += 50;
              if (card.path_status === 'superseded') value += 60;
              return value;
            }

            function 按链路排序(a, b) {
              return 链路排序值(a) - 链路排序值(b)
                || String(a.main_id || '').localeCompare(String(b.main_id || ''))
                || String(a.created_at || '').localeCompare(String(b.created_at || ''));
            }

            function 渲染卡片(card) {
              const enterprise = card.domain_facets?.enterprise || {};
              const client = firstValue(enterprise['客户']);
              const timeValue = firstValue(card.base_facets?.time) || firstValue(enterprise['时间/季节/节庆']);
              const packLabel = card.facet_pack_id ? `${card.facet_pack_id}:${card.facet_pack_version || ''}` : '通用';
              const div = document.createElement('div');
              div.className = 'card-item' + (card.raw_memory_id === currentId ? ' active' : '');
              div.onclick = () => loadCard(card.raw_memory_id);
              div.innerHTML = `
                <div class="card-title">${escapeHtml(card.title)}</div>
                <div class="card-sub">${escapeHtml(card.meaning_summary || card.fact_summary || '')}</div>
                <div class="meta">
                  <span class="pill">${escapeHtml(card.chain_status === 'unassigned' ? '未编链' : card.chain_status || '未编链')}</span>
                  <span class="pill">${escapeHtml(card.main_id || '无主ID')}</span>
                  ${card.path_status && card.path_status !== 'active' ? `<span class="pill">${escapeHtml(路径状态中文(card.path_status))}</span>` : ''}
                  ${client ? `<span class="pill">${escapeHtml(client)}</span>` : ''}
                  ${timeValue ? `<span class="pill">${escapeHtml(timeValue)}</span>` : ''}
                  <span class="pill">${escapeHtml(packLabel)}</span>
                </div>
              `;
              return div;
            }

            function 节点边框色(node) {
              if (node.current) return '#2ed573';
              if (node.topology_role === 'origin') return '#57b5ff';
              if (node.graph_kind === 'vcp') return '#ff8f57';
              if (node.is_landmark || ['dead_end', 'superseded', 'open_head', 'paused'].includes(node.path_status) || ['merge', 'exit'].includes(node.role)) return '#ffb454';
              return '#7f8cff';
            }

            function 节点填充色(node) {
              if (node.current) return '#173d29';
              if (node.topology_role === 'origin') return '#112f4a';
              if (node.graph_kind === 'vcp') return '#382016';
              if (node.is_landmark || ['dead_end', 'superseded', 'open_head', 'paused'].includes(node.path_status) || ['merge', 'exit'].includes(node.role)) return '#3b2813';
              return '#1b2345';
            }

            function edgeColor(edge) {
              if (edge.reconnect) return '#ffb454';
              if (edge.relation_type === 'associative') return '#ff8f57';
              if (edge.relation_type === 'project_fusion') return '#5ce1e6';
              if (edge.path_status === 'dead_end' || edge.path_status === 'superseded') return '#ffb454';
              return '#6c86ff';
            }

            function graphScaleText() {
              return `${Math.round(graphView.scale * 100)}%`;
            }

            function applyGraphTransform() {
              const viewport = document.getElementById('graphViewport');
              if (!viewport) return;
              viewport.setAttribute('transform', `translate(${graphView.panX} ${graphView.panY}) scale(${graphView.scale})`);
            }

            function resetGraphView(payload, width, height, frames = {}) {
              const graphScroll = document.querySelector('.graph-scroll');
              const currentNode = (payload.nodes || []).find(node => node.current) || payload.nodes?.[0];
              const mode = payload.mode || 'local';
              graphView.scale = mode === 'full' ? 0.9 : (mode === 'vcp' ? 0.92 : 1.12);
              if (graphScroll && currentNode) {
                const rect = graphScroll.getBoundingClientRect();
                const viewWidth = rect.width || 760;
                const viewHeight = rect.height || 520;
                const frame = frames[currentNode.id];
                const nodeX = frame ? frame.x + (frame.width / 2) : (48 + Number(currentNode.lane || 0) * 188 + 78);
                const nodeY = frame ? frame.y + (frame.height / 2) : (42 + Number(currentNode.level || 0) * 142 + 40);
                graphView.panX = (viewWidth / 2) - (nodeX * graphView.scale);
                graphView.panY = (viewHeight / 2) - (nodeY * graphView.scale);
              } else {
                graphView.panX = 24;
                graphView.panY = 20;
              }
              currentGraphMeta = { width, height, mode, frames };
              applyGraphTransform();
            }

            function attachGraphInteractions() {
              const graphScroll = document.querySelector('.graph-scroll');
              const svg = document.getElementById('graphCanvas');
              if (!graphScroll || !svg || graphScroll.dataset.bound === '1') return;

              graphScroll.addEventListener('wheel', event => {
                if (!currentGraphMeta) return;
                event.preventDefault();
                const rect = svg.getBoundingClientRect();
                if (!rect.width || !rect.height) return;
                const cursorX = ((event.clientX - rect.left) / rect.width) * currentGraphMeta.width;
                const cursorY = ((event.clientY - rect.top) / rect.height) * currentGraphMeta.height;
                const oldScale = graphView.scale;
                const factor = event.deltaY < 0 ? 1.12 : 0.9;
                const newScale = Math.max(0.6, Math.min(6.0, oldScale * factor));
                const worldX = (cursorX - graphView.panX) / oldScale;
                const worldY = (cursorY - graphView.panY) / oldScale;
                graphView.scale = newScale;
                graphView.panX = cursorX - worldX * newScale;
                graphView.panY = cursorY - worldY * newScale;
                applyGraphTransform();
                更新图谱状态();
              }, { passive: false });

              graphScroll.addEventListener('mousedown', event => {
                if (event.button !== 0) return;
                if (!currentGraphMeta) return;
                event.preventDefault();
                graphView.dragging = true;
                graphView.dragStartX = event.clientX;
                graphView.dragStartY = event.clientY;
                graphScroll.classList.add('dragging');
              });

              window.addEventListener('mousemove', event => {
                if (!graphView.dragging || !currentGraphMeta) return;
                const rect = svg.getBoundingClientRect();
                if (!rect.width || !rect.height) return;
                const deltaX = ((event.clientX - graphView.dragStartX) / rect.width) * currentGraphMeta.width;
                const deltaY = ((event.clientY - graphView.dragStartY) / rect.height) * currentGraphMeta.height;
                graphView.dragStartX = event.clientX;
                graphView.dragStartY = event.clientY;
                graphView.panX += deltaX;
                graphView.panY += deltaY;
                applyGraphTransform();
              });

              window.addEventListener('mouseup', () => {
                graphView.dragging = false;
                graphScroll.classList.remove('dragging');
              });

              graphScroll.addEventListener('mouseleave', () => {
                graphView.dragging = false;
                graphScroll.classList.remove('dragging');
              });

              graphScroll.addEventListener('dblclick', () => {
                if (!currentGraphMeta) return;
                graphView.signature = '';
                loadGraph(currentGraphMeta.mode || 'local');
              });

              graphScroll.dataset.bound = '1';
            }

            async function loadGraph(mode = 'local') {
              if (!currentId) {
                graphView.statusBase = '请选择卡片后再看图谱。';
                更新图谱状态();
                document.getElementById('graphCanvas').innerHTML = '';
                return;
              }
              const graphLabels = {
                local: '残影导航图',
                full: '项目导航图',
                vcp: 'VCP 联想图',
              };
              const graphLoadingStates = {
                local: '正在加载当前节点上下游 2 步的残影导航图...',
                full: '正在加载项目导航图...',
                vcp: '正在加载 VCP 联想图...',
              };
              graphView.statusBase = graphLoadingStates[mode] || graphLoadingStates.local;
              更新图谱状态();
              const endpoint = mode === 'vcp'
                ? `/api/cards/${encodeURIComponent(currentId)}/vcp-graph`
                : `/api/cards/${encodeURIComponent(currentId)}/graph?mode=${encodeURIComponent(mode)}&hops=2`;
              const res = await fetch(endpoint);
              const payload = await res.json();
              renderGraph(payload);
              const nodeCount = Array.isArray(payload.nodes) ? payload.nodes.length : 0;
              const edgeCount = Array.isArray(payload.edges) ? payload.edges.length : 0;
              currentGraphMeta = { ...(currentGraphMeta || {}), mode };
              const messageSuffix = payload.message ? ` | ${payload.message}` : '';
              const modeHint = mode === 'vcp' ? ' | 离中心越近 = 联想越强 / 更先被想起' : '';
              更新图谱状态(`${graphLabels[mode] || graphLabels.local}：项目 ${payload.project || '未归属项目'}，显示 ${nodeCount} 个节点 / ${edgeCount} 条边${modeHint}${messageSuffix}`);
            }

            async function loadMechanisms() {
              if (!currentId) {
                document.getElementById('mechanismOutput').textContent = '请选择卡片后再看机制信息。';
                return;
              }
              const res = await fetch(`/api/cards/${encodeURIComponent(currentId)}/mechanisms`);
              const payload = await res.json();
              const focus = payload.focus || {};
              const current = payload.current || {};
              const parallel = Array.isArray(payload.parallel_candidates) ? payload.parallel_candidates : [];
              const reconnect = Array.isArray(payload.reconnect_targets) ? payload.reconnect_targets : [];
              document.getElementById('mechanismOutput').textContent = [
                `项目：${payload.project || '未归属项目'}`,
                `当前节点：${current.main_id || '未指定'} ${current.title ? `| ${current.title}` : ''}`,
                `当前状态：${路径状态中文(current.path_status) || '仍有效'} | 关系类型：${current.relation_type || 'unassigned'}`,
                '',
                `思考光标：${focus.main_id || '未指定'} ${focus.title ? `| ${focus.title}` : ''}`,
                `光标置信度：${focus.confidence ?? 0}`,
                `光标说明：${focus.reason || '当前还没有明确指定'}`,
                '',
                `并行候选：${parallel.length ? parallel.map(item => `${item.main_id}（${item.title}）`).join('；') : '无并行候选'}`,
                `断档重连候选：${reconnect.length ? reconnect.map(item => `${item.main_id}（${item.title} / ${路径状态中文(item.path_status)}）`).join('；') : '当前无开放头/暂停节点'}`
              ].join('\\n');
            }

            function renderGraph(payload) {
              const svg = document.getElementById('graphCanvas');
              const nodes = Array.isArray(payload.nodes) ? payload.nodes : [];
              const edges = Array.isArray(payload.edges) ? payload.edges : [];
              if (!nodes.length) {
                svg.setAttribute('viewBox', '0 0 760 520');
                svg.innerHTML = `<text x="24" y="36" fill="#98a4b6" font-size="14">${escapeHtml(payload.message || '当前还没有可展示的链路图。')}</text>`;
                return;
              }

              const isVcpGraph = (payload.mode || 'local') === 'vcp';
              const minNodeWidth = isVcpGraph ? 156 : 176;
              const minNodeHeight = isVcpGraph ? 80 : 88;
              const xGap = 36;
              const yGap = 54;
              const maxCharsPerLine = 14;
              const marginX = 48;
              const marginY = 42;
              const nodeLayouts = new Map();

              nodes.forEach(node => {
                const titleLines = 图谱标签行(node.title || node.short_title || node.id, maxCharsPerLine);
                const longestLine = Math.max(...titleLines.map(line => line.length), 8);
                const nodeWidth = Math.max(minNodeWidth, 34 + (longestLine * (isVcpGraph ? 13 : 15)));
                const nodeHeight = Math.max(minNodeHeight, 54 + (titleLines.length * (isVcpGraph ? 17 : 18)));
                nodeLayouts.set(node.id, { titleLines, nodeWidth, nodeHeight });
              });

              const pos = new Map();
              const frames = {};
              const parts = [];
              let width = 760;
              let height = 520;

              if (isVcpGraph) {
                const currentNode = nodes.find(node => node.current) || nodes[0];
                const currentLayout = nodeLayouts.get(currentNode.id);
                const outerNodes = nodes.filter(node => node.id !== currentNode.id);
                const scoreValues = outerNodes
                  .map(node => Number(node.match_score || 0))
                  .filter(value => Number.isFinite(value));
                const maxScore = scoreValues.length ? Math.max(...scoreValues) : 1;
                const minScore = scoreValues.length ? Math.min(...scoreValues) : 0;
                const currentDiag = Math.hypot(currentLayout.nodeWidth, currentLayout.nodeHeight);

                const ringGroups = [[], [], []];
                outerNodes.forEach((node, index) => {
                  const score = Number(node.match_score || 0);
                  let closeness = 0.5;
                  if (scoreValues.length && Number.isFinite(score) && maxScore > minScore + 0.0001) {
                    closeness = (score - minScore) / (maxScore - minScore);
                  } else if (outerNodes.length <= 1) {
                    closeness = 1;
                  } else {
                    closeness = 1 - (index / Math.max(outerNodes.length - 1, 1));
                  }
                  const ringIndex = closeness >= 0.67 ? 0 : (closeness >= 0.34 ? 1 : 2);
                  node.radial_ring = ringIndex + 1;
                  ringGroups[ringIndex].push(node);
                });
                ringGroups.forEach(group => group.sort((a, b) =>
                  Number(a.recall_rank || 0) - Number(b.recall_rank || 0)
                  || Number(b.match_score || 0) - Number(a.match_score || 0)
                ));

                const arcGap = 56;
                const radialGap = 104;
                const ringRadii = [];
                let previousRadius = 0;
                let previousDiag = currentDiag;

                ringGroups.forEach((group, ringIndex) => {
                  if (!group.length) {
                    ringRadii[ringIndex] = ringIndex === 0
                      ? Math.max(228, (currentDiag / 2) + 116)
                      : (previousRadius + radialGap);
                    previousRadius = ringRadii[ringIndex];
                    return;
                  }
                  const maxDiag = Math.max(...group.map(node => {
                    const layout = nodeLayouts.get(node.id);
                    return Math.hypot(layout.nodeWidth, layout.nodeHeight);
                  }));
                  const requiredCircumference = group.reduce((sum, node) => {
                    const layout = nodeLayouts.get(node.id);
                    return sum + layout.nodeWidth + arcGap;
                  }, 0);
                  const requiredRadius = requiredCircumference / (Math.PI * 2);
                  const baseRadius = ringIndex === 0
                    ? Math.max(228, (currentDiag / 2) + (maxDiag / 2) + 116)
                    : (previousRadius + (previousDiag / 2) + (maxDiag / 2) + radialGap);
                  const radius = Math.max(baseRadius, requiredRadius);
                  ringRadii[ringIndex] = radius;
                  previousRadius = radius;
                  previousDiag = maxDiag;
                });

                const maxNodeWidth = Math.max(currentLayout.nodeWidth, ...outerNodes.map(node => nodeLayouts.get(node.id).nodeWidth), 0);
                const maxNodeHeight = Math.max(currentLayout.nodeHeight, ...outerNodes.map(node => nodeLayouts.get(node.id).nodeHeight), 0);
                const maxRadius = outerNodes.length
                  ? Math.max(...ringRadii.filter(radius => Number.isFinite(radius)))
                  : Math.max(228, (currentDiag / 2) + 116);

                width = Math.max(980, Math.ceil((maxRadius + (maxNodeWidth / 2) + 180) * 2));
                height = Math.max(820, Math.ceil((maxRadius + (maxNodeHeight / 2) + 180) * 2));
                svg.setAttribute('viewBox', `0 0 ${width} ${height}`);

                const centerX = width / 2;
                const centerY = height / 2;
                const centerFrame = {
                  x: centerX - (currentLayout.nodeWidth / 2),
                  y: centerY - (currentLayout.nodeHeight / 2),
                  width: currentLayout.nodeWidth,
                  height: currentLayout.nodeHeight,
                };
                pos.set(currentNode.id, { x: centerFrame.x, y: centerFrame.y });
                frames[currentNode.id] = centerFrame;

                ringRadii.forEach((radius, index) => {
                  parts.push(`<circle cx="${centerX}" cy="${centerY}" r="${radius}" fill="none" stroke="#293445" stroke-width="1.2" stroke-dasharray="6 7" opacity="${index === 0 ? '0.34' : '0.22'}" />`);
                });
                parts.push(`<text x="${centerX - 120}" y="${height - 26}" fill="#7f8da5" font-size="12.6">离中心越近 = 联想越强 / 更先被想起</text>`);

                ringGroups.forEach((group, ringIndex) => {
                  if (!group.length) return;
                  const radius = ringRadii[ringIndex];
                  const angleOffset = ringIndex === 0 ? 0 : (ringIndex === 1 ? Math.PI / Math.max(group.length, 2) : Math.PI / Math.max(group.length * 2, 2));
                  const totalArc = group.reduce((sum, node) => {
                    const layout = nodeLayouts.get(node.id);
                    return sum + layout.nodeWidth + arcGap;
                  }, 0) || 1;
                  let cursor = (-Math.PI / 2) + angleOffset;
                  group.forEach((node) => {
                    const layout = nodeLayouts.get(node.id);
                    const arcSpan = ((layout.nodeWidth + arcGap) / totalArc) * (Math.PI * 2);
                    const angle = cursor + (arcSpan / 2);
                    cursor += arcSpan;
                    node.radial_ring = ringIndex + 1;
                    const x = centerX + (Math.cos(angle) * radius) - (layout.nodeWidth / 2);
                    const y = centerY + (Math.sin(angle) * radius) - (layout.nodeHeight / 2);
                    pos.set(node.id, { x, y });
                    frames[node.id] = { x, y, width: layout.nodeWidth, height: layout.nodeHeight };
                  });
                });
              } else {
                const levelMax = Math.max(...nodes.map(node => Number(node.level || 0)));
                const laneMax = Math.max(...nodes.map(node => Number(node.lane || 0)));
                const laneWidths = Array.from({ length: laneMax + 1 }, () => minNodeWidth);
                const levelHeights = Array.from({ length: levelMax + 1 }, () => minNodeHeight);

                nodes.forEach(node => {
                  const layout = nodeLayouts.get(node.id);
                  laneWidths[Number(node.lane || 0)] = Math.max(laneWidths[Number(node.lane || 0)], layout.nodeWidth);
                  levelHeights[Number(node.level || 0)] = Math.max(levelHeights[Number(node.level || 0)], layout.nodeHeight);
                });

                const laneOffsets = [];
                let laneCursor = 0;
                for (let lane = 0; lane <= laneMax; lane += 1) {
                  laneOffsets[lane] = laneCursor;
                  laneCursor += laneWidths[lane] + xGap;
                }

                const levelOffsets = [];
                let levelCursor = 0;
                for (let level = 0; level <= levelMax; level += 1) {
                  levelOffsets[level] = levelCursor;
                  levelCursor += levelHeights[level] + yGap;
                }

                width = Math.max(760, marginX * 2 + Math.max(0, laneCursor - xGap));
                height = Math.max(520, marginY * 2 + Math.max(0, levelCursor - yGap));
                svg.setAttribute('viewBox', `0 0 ${width} ${height}`);

                nodes.forEach(node => {
                  const layout = nodeLayouts.get(node.id);
                  const lane = Number(node.lane || 0);
                  const level = Number(node.level || 0);
                  pos.set(node.id, {
                    x: marginX + laneOffsets[lane],
                    y: marginY + levelOffsets[level],
                  });
                  frames[node.id] = {
                    x: marginX + laneOffsets[lane],
                    y: marginY + levelOffsets[level],
                    width: layout.nodeWidth,
                    height: layout.nodeHeight,
                  };
                });
              }

              edges.forEach(edge => {
                const sourceFrame = frames[edge.source];
                const targetFrame = frames[edge.target];
                if (!sourceFrame || !targetFrame) return;
                const color = edgeColor(edge);
                const dash = edge.reconnect ? '8 6' : (edge.relation_type === 'project_fusion' ? '10 7' : '');
                const startX = sourceFrame.x + (sourceFrame.width / 2);
                const startY = isVcpGraph ? (sourceFrame.y + (sourceFrame.height / 2)) : (sourceFrame.y + sourceFrame.height);
                const endX = targetFrame.x + (targetFrame.width / 2);
                const endY = isVcpGraph ? (targetFrame.y + (targetFrame.height / 2)) : targetFrame.y;
                const midX = (startX + endX) / 2;
                const midY = (startY + endY) / 2;
                const markerId = edge.relation_type === 'associative' ? 'arrowAssociative' : 'arrow';
                parts.push(
                  `<line x1="${startX}" y1="${startY}" x2="${endX}" y2="${endY}" stroke="${color}" stroke-width="${edge.reconnect ? 3.4 : 2.7}" ${dash ? `stroke-dasharray="${dash}"` : ''} marker-end="url(#${markerId})" opacity="0.92" />`
                );
                if (edge.reconnect) {
                  parts.push(
                    `<g>
                      <rect x="${midX - 24}" y="${midY - 13}" rx="9" ry="9" width="48" height="18" fill="#ffb454" opacity="0.95" />
                      <text x="${midX - 13}" y="${midY}" fill="#09111b" font-size="10.5" font-weight="800">重连</text>
                    </g>`
                  );
                } else if (edge.relation_type === 'project_fusion') {
                  parts.push(
                    `<g>
                      <rect x="${midX - 26}" y="${midY - 13}" rx="9" ry="9" width="52" height="18" fill="#5ce1e6" opacity="0.92" />
                      <text x="${midX - 16}" y="${midY}" fill="#081018" font-size="10.2" font-weight="800">汇合</text>
                    </g>`
                  );
                }
              });

              nodes.forEach(node => {
                const point = pos.get(node.id);
                if (!point) return;
                const layout = nodeLayouts.get(node.id);
                const border = 节点边框色(node);
                const fill = 节点填充色(node);
                const statusText = isVcpGraph
                  ? (node.current
                    ? '当前种子 / 触发点'
                    : `${node.role || ''}${node.radial_ring ? ` · 第${node.radial_ring}圈` : ''}`)
                  : (路径状态中文(node.path_status) || node.role || '');
                const titleLines = layout.titleLines;
                const badgeText = node.current
                  ? '当前'
                  : (node.graph_kind === 'vcp'
                    ? (node.topology_role === 'origin' ? '种子' : '联想')
                    : (node.topology_role === 'origin'
                      ? '原点'
                      : (node.is_landmark || ['dead_end', 'superseded', 'open_head', 'paused'].includes(node.path_status) || ['merge', 'exit'].includes(node.role) ? '特殊' : '延申')));
                const badgeFill = node.current
                  ? '#2ed573'
                  : (node.graph_kind === 'vcp'
                    ? (node.topology_role === 'origin' ? '#57b5ff' : '#ff8f57')
                    : (node.topology_role === 'origin'
                      ? '#57b5ff'
                      : (node.is_landmark || ['dead_end', 'superseded', 'open_head', 'paused'].includes(node.path_status) || ['merge', 'exit'].includes(node.role) ? '#ffb454' : '#6c86ff')));
                const glow = node.current
                  ? (isVcpGraph
                    ? `<circle cx="${point.x + (layout.nodeWidth / 2)}" cy="${point.y + (layout.nodeHeight / 2)}" r="${Math.max(layout.nodeWidth, layout.nodeHeight) / 2 + 16}" fill="none" stroke="#6cffad" stroke-width="3.2" opacity="0.95" />`
                    : `<rect x="${point.x - 8}" y="${point.y - 8}" rx="20" ry="20" width="${layout.nodeWidth + 16}" height="${layout.nodeHeight + 16}" fill="none" stroke="#6cffad" stroke-width="3.2" opacity="0.95" />`)
                  : '';
                const titleSvg = titleLines.map((line, index) =>
                  `<text x="${point.x + 14}" y="${point.y + 30 + (index * (isVcpGraph ? 17 : 18))}" fill="#eef4ff" font-size="${isVcpGraph ? '14.2' : '15.6'}" font-weight="700">${escapeHtml(line)}</text>`
                ).join('');
                const statusY = point.y + layout.nodeHeight - 14;
                parts.push(
                  `<g>
                    ${glow}
                    <rect x="${point.x}" y="${point.y}" rx="14" ry="14" width="${layout.nodeWidth}" height="${layout.nodeHeight}" fill="${fill}" stroke="${border}" stroke-width="${node.current ? 3.8 : 2}" />
                    <rect x="${point.x + 10}" y="${point.y - 14}" rx="10" ry="10" width="42" height="20" fill="${badgeFill}" />
                    <text x="${point.x + 19}" y="${point.y + 1}" fill="#07111c" font-size="11" font-weight="800">${badgeText}</text>
                    ${titleSvg}
                    <text x="${point.x + 14}" y="${statusY}" fill="#b9c3d6" font-size="12.4">${escapeHtml(statusText || node.role || '')}</text>
                  </g>`
                );
              });

              const signature = `${payload.mode || 'local'}|${payload.focus_main_id || ''}|${nodes.length}|${edges.length}`;
              svg.innerHTML = `
                <defs>
                  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path d="M 0 0 L 10 5 L 0 10 z" fill="#6c86ff"></path>
                  </marker>
                  <marker id="arrowAssociative" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path d="M 0 0 L 10 5 L 0 10 z" fill="#ff8f57"></path>
                  </marker>
                </defs>
                <g id="graphViewport">
                  ${parts.join('')}
                </g>
              `;
              attachGraphInteractions();
              if (graphView.signature !== signature) {
                graphView.signature = signature;
                resetGraphView(payload, width, height, frames);
              } else {
                currentGraphMeta = { ...(currentGraphMeta || {}), width, height, mode: payload.mode || 'local', frames };
                applyGraphTransform();
              }
            }

            async function loadCards() {
              const res = await fetch(buildCardsUrl());
              const cards = await res.json();
              const list = document.getElementById('cardList');
              list.innerHTML = '';
              const groups = new Map();
              cards.forEach(card => {
                const project = 项目名(card);
                const subproject = 子项目名(card);
                if (!groups.has(project)) {
                  groups.set(project, { direct: [], children: new Map() });
                }
                const entry = groups.get(project);
                if (subproject) {
                  if (!entry.children.has(subproject)) entry.children.set(subproject, []);
                  entry.children.get(subproject).push(card);
                } else {
                  entry.direct.push(card);
                }
              });
              Array.from(groups.entries()).forEach(([project, entry]) => {
                const projectCards = [
                  ...entry.direct,
                  ...Array.from(entry.children.values()).flat(),
                ];
                const details = document.createElement('details');
                details.className = 'project-group';
                details.open = projectCards.some(card => card.raw_memory_id === currentId);
                details.innerHTML = `
                  <summary>
                    <span>📁 ${escapeHtml(project)}</span>
                    <span class="project-count">${projectCards.length} 条记忆</span>
                  </summary>
                `;
                if (entry.direct.length || entry.children.size) {
                  const folderEntries = [];
                  const childStack = document.createElement('div');
                  childStack.className = 'subproject-stack';
                  if (entry.direct.length) {
                    const directDetails = document.createElement('details');
                    directDetails.className = 'subproject-group';
                    const directActive = entry.direct.some(card => card.raw_memory_id === currentId);
                    directDetails.open = directActive;
                    directDetails.innerHTML = `
                      <summary>
                        <span>总项目直系记忆</span>
                        <span class="subproject-count">${entry.direct.length} 条</span>
                      </summary>
                    `;
                    const directBody = document.createElement('div');
                    directBody.className = 'project-cards';
                    entry.direct.sort(按链路排序).forEach(card => directBody.appendChild(渲染卡片(card)));
                    directDetails.appendChild(directBody);
                    childStack.appendChild(directDetails);
                    folderEntries.push({ label: '总项目直系记忆', element: directDetails, active: directActive });
                  }
                  Array.from(entry.children.entries()).forEach(([subproject, subCards]) => {
                    const subDetails = document.createElement('details');
                    subDetails.className = 'subproject-group';
                    const subActive = subCards.some(card => card.raw_memory_id === currentId);
                    subDetails.open = subActive;
                    subDetails.innerHTML = `
                      <summary>
                        <span>${escapeHtml(subproject)}</span>
                        <span class="subproject-count">${subCards.length} 条</span>
                      </summary>
                    `;
                    const subBody = document.createElement('div');
                    subBody.className = 'project-cards';
                    subCards.sort(按链路排序).forEach(card => subBody.appendChild(渲染卡片(card)));
                    subDetails.appendChild(subBody);
                    childStack.appendChild(subDetails);
                    folderEntries.push({ label: subproject, element: subDetails, active: subActive });
                  });
                  if (!folderEntries.some(entryItem => entryItem.active) && folderEntries[0]) {
                    folderEntries[0].active = true;
                    folderEntries[0].element.open = true;
                  }
                  if (folderEntries.length) {
                    const railWrap = document.createElement('div');
                    railWrap.className = 'folder-rail-wrap';
                    const prev = document.createElement('button');
                    prev.className = 'folder-rail-nav';
                    prev.type = 'button';
                    prev.textContent = '‹';
                    const rail = document.createElement('div');
                    rail.className = 'folder-rail';
                    const next = document.createElement('button');
                    next.className = 'folder-rail-nav';
                    next.type = 'button';
                    next.textContent = '›';

                    const focusFolder = (targetEntry) => {
                      folderEntries.forEach(entryItem => {
                        const active = entryItem === targetEntry;
                        entryItem.element.open = active;
                        if (entryItem.chip) {
                          entryItem.chip.classList.toggle('active', active);
                        }
                      });
                      targetEntry.element.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                    };

                    folderEntries.forEach((folderEntry) => {
                      const chip = document.createElement('button');
                      chip.className = 'folder-chip' + (folderEntry.active ? ' active' : '');
                      chip.type = 'button';
                      chip.textContent = folderEntry.label;
                      chip.onclick = () => focusFolder(folderEntry);
                      folderEntry.chip = chip;
                      rail.appendChild(chip);
                    });

                    prev.onclick = () => rail.scrollBy({ left: -Math.max(180, rail.clientWidth * 0.72), behavior: 'smooth' });
                    next.onclick = () => rail.scrollBy({ left: Math.max(180, rail.clientWidth * 0.72), behavior: 'smooth' });

                    railWrap.appendChild(prev);
                    railWrap.appendChild(rail);
                    railWrap.appendChild(next);
                    details.appendChild(railWrap);
                  }
                  details.appendChild(childStack);
                }
                list.appendChild(details);
              });
            }

            async function loadCard(id) {
              currentId = id;
              const res = await fetch(`/api/cards/${encodeURIComponent(id)}`);
              const card = await res.json();
              currentCard = card;
              const base = card.base_facets || {};
              const enterprise = card.domain_facets?.enterprise || {};
              const sourceMeta = card.domain_facets?.memory_source || {};
              const gov = card.governance || {};

              document.getElementById('title').value = card.title || '';
              document.getElementById('fact_summary').value = card.fact_summary || '';
              document.getElementById('meaning_summary').value = card.meaning_summary || '';
              document.getElementById('posture_summary').value = card.posture_summary || '';
              document.getElementById('emotion_trajectory').value = card.emotion_trajectory || '';
              document.getElementById('body_text').value = card.body_text || '';
              document.getElementById('raw_text').value = card.raw_text || '';
              document.getElementById('main_id').value = card.main_id || '';
              document.getElementById('upstream_main_ids').value = joinList(card.upstream_main_ids);
              document.getElementById('downstream_main_ids').value = joinList(card.downstream_main_ids);
              document.getElementById('relation_type').value = card.relation_type || 'unassigned';
              document.getElementById('topology_role').value = card.topology_role || 'node';
              document.getElementById('path_status').value = card.path_status || 'active';
              document.getElementById('focus_anchor_main_id').value = card.focus_anchor_main_id || '';
              document.getElementById('focus_confidence').value = card.focus_confidence ?? '';
              document.getElementById('focus_reason').value = card.focus_reason || '';
              document.getElementById('is_landmark').checked = !!card.is_landmark;
              document.getElementById('chain_author').value = card.chain_author || '';
              document.getElementById('chain_author_role').value = card.chain_author_role || 'none';
              document.getElementById('chain_status').value = card.chain_status || 'unassigned';
              document.getElementById('chain_confidence').value = card.chain_confidence ?? '';
              document.getElementById('entity_tags').value = joinList(base.entity);
              document.getElementById('topic_tags').value = joinList(base.topic);
              setSelectValue('time_tags', base.time);
              document.getElementById('status_tags').value = joinList(base.status);
              document.getElementById('memory_type').value = base.memory_type || 'method';
              document.getElementById('memory_subtype').value = base.memory_subtype || '';
              document.getElementById('scope_core').value = joinList(base.relevance_scope_core);
              document.getElementById('scope_extra').value = joinList(base.relevance_scope_extra);

              setSelectValue('ent_clients', enterprise['客户'], '历史客户：');
              document.getElementById('ent_projects').value = joinList(enterprise['项目']);
              document.getElementById('ent_products').value = joinList(enterprise['产品/品类']);
              document.getElementById('ent_style').value = joinList(enterprise['风格'] || enterprise['风格/主题']);
              document.getElementById('ent_theme').value = joinList(enterprise['主题']);
              setSelectValue('ent_season', enterprise['时间/季节/节庆'], '历史业务时间：');
              document.getElementById('ent_stage').value = joinList(enterprise['流程节点']);
              document.getElementById('ent_role').value = joinList(enterprise['部门/角色']);
              document.getElementById('ent_goal').value = joinList(enterprise['目标/约束']);
              document.getElementById('ent_asset').value = joinList(enterprise['文档/资产类型']);
              document.getElementById('src_frontend').value = sourceMeta.frontend || '';
              document.getElementById('src_host').value = sourceMeta.host || '';
              document.getElementById('src_thread').value = sourceMeta.thread || '';
              document.getElementById('src_session').value = sourceMeta.session || '';
              document.getElementById('src_write_mode').value = sourceMeta.write_mode || '';
              document.getElementById('src_source_role').value = sourceMeta.source_role || '';
              document.getElementById('src_parallel_rule').value = sourceMeta.parallel_rule || 'append_only_branching';
              document.getElementById('src_relation_note').value = sourceMeta.relation_note || '';
              setSelectValue('facet_pack_id_ui', card.facet_pack_id || '');
              document.getElementById('facet_pack_summary').value = card.facet_pack_id
                ? '当前卡片已挂企业维度包，适合客户/项目/产品类记忆。'
                : '当前卡片默认按通用记忆展示，只有需要时再挂企业维度。';

              document.getElementById('shelf_state').value = gov.shelf_state || 'half_open';
              document.getElementById('importance').value = gov.importance || 'normal';
              document.getElementById('pinned').checked = !!gov.pinned;
              document.getElementById('confidence').value = gov.confidence ?? '';
              document.getElementById('promotion_rule_text').value = gov.promotion_rule_text || '';
              document.getElementById('degradation_rule_text').value = gov.degradation_rule_text || '';
              document.getElementById('rationale').value = gov.rationale || '';
              document.getElementById('advanced_governance').value = JSON.stringify({
                promotion_signals: gov.promotion_signals || {},
                degradation_signals: gov.degradation_signals || {},
                reactivation_rule: gov.reactivation_rule || {}
              }, null, 2);

              document.getElementById('detailOutput').textContent = 卡片详情文本(card);
              loadGraph('local');
              loadMechanisms();
              loadCards();
            }

            async function saveCard() {
              if (!currentId) return;

              let advanced = {};
              try {
                advanced = JSON.parse(document.getElementById('advanced_governance').value || '{}');
              } catch (error) {
                document.getElementById('saveStatus').textContent = '高级治理 JSON 格式不正确';
                return;
              }

              const payload = {
                facet_pack_id: document.getElementById('facet_pack_id_ui').value || '',
                facet_pack_version: document.getElementById('facet_pack_id_ui').value ? 'v1' : '',
                title: document.getElementById('title').value,
                fact_summary: document.getElementById('fact_summary').value,
                meaning_summary: document.getElementById('meaning_summary').value,
                posture_summary: document.getElementById('posture_summary').value,
                emotion_trajectory: document.getElementById('emotion_trajectory').value,
                body_text: document.getElementById('body_text').value,
                raw_text: document.getElementById('raw_text').value,
                main_id: document.getElementById('main_id').value,
                upstream_main_ids: splitList(document.getElementById('upstream_main_ids').value),
                downstream_main_ids: splitList(document.getElementById('downstream_main_ids').value),
                relation_type: document.getElementById('relation_type').value,
                topology_role: document.getElementById('topology_role').value,
                path_status: document.getElementById('path_status').value,
                focus_anchor_main_id: document.getElementById('focus_anchor_main_id').value,
                focus_confidence: Number(document.getElementById('focus_confidence').value || 0),
                focus_reason: document.getElementById('focus_reason').value,
                is_landmark: document.getElementById('is_landmark').checked,
                chain_author: document.getElementById('chain_author').value,
                chain_author_role: document.getElementById('chain_author_role').value,
                chain_status: document.getElementById('chain_status').value,
                chain_confidence: Number(document.getElementById('chain_confidence').value || 0),
                base_facets: {
                  entity: splitList(document.getElementById('entity_tags').value),
                  topic: splitList(document.getElementById('topic_tags').value),
                  time: singleValueList(document.getElementById('time_tags').value),
                  status: splitList(document.getElementById('status_tags').value),
                  memory_type: document.getElementById('memory_type').value,
                  memory_subtype: document.getElementById('memory_subtype').value,
                  relevance_scope_core: splitList(document.getElementById('scope_core').value),
                  relevance_scope_extra: splitList(document.getElementById('scope_extra').value)
                },
                domain_facets: {
                  memory_source: {
                    frontend: document.getElementById('src_frontend').value,
                    host: document.getElementById('src_host').value,
                    thread: document.getElementById('src_thread').value,
                    session: document.getElementById('src_session').value,
                    write_mode: document.getElementById('src_write_mode').value,
                    source_role: document.getElementById('src_source_role').value,
                    parallel_rule: document.getElementById('src_parallel_rule').value || 'append_only_branching',
                    relation_note: document.getElementById('src_relation_note').value
                  },
                  enterprise: {
                    "客户": singleValueList(document.getElementById('ent_clients').value),
                    "项目": splitList(document.getElementById('ent_projects').value),
                    "产品/品类": splitList(document.getElementById('ent_products').value),
                    "风格": splitList(document.getElementById('ent_style').value),
                    "主题": splitList(document.getElementById('ent_theme').value),
                    "风格/主题": [
                      ...splitList(document.getElementById('ent_style').value),
                      ...splitList(document.getElementById('ent_theme').value)
                    ],
                    "时间/季节/节庆": singleValueList(document.getElementById('ent_season').value),
                    "流程节点": splitList(document.getElementById('ent_stage').value),
                    "部门/角色": splitList(document.getElementById('ent_role').value),
                    "目标/约束": splitList(document.getElementById('ent_goal').value),
                    "文档/资产类型": splitList(document.getElementById('ent_asset').value)
                  }
                },
                governance: {
                  shelf_state: document.getElementById('shelf_state').value,
                  importance: document.getElementById('importance').value,
                  pinned: document.getElementById('pinned').checked,
                  confidence: Number(document.getElementById('confidence').value || 0),
                  promotion_rule_text: document.getElementById('promotion_rule_text').value,
                  degradation_rule_text: document.getElementById('degradation_rule_text').value,
                  rationale: document.getElementById('rationale').value,
                  promotion_signals: advanced.promotion_signals || {},
                  degradation_signals: advanced.degradation_signals || {},
                  reactivation_rule: advanced.reactivation_rule || {}
                }
              };

              if (chainFieldsChanged(payload, currentCard)) {
                payload.chain_author = payload.chain_author || 'human';
                payload.chain_author_role = 'human';
                payload.chain_status = 'human_confirmed';
              }

              document.getElementById('saveStatus').textContent = '保存中...';
              const res = await fetch(`/api/cards/${encodeURIComponent(currentId)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
              });
              const result = await res.json();
              document.getElementById('saveStatus').textContent = res.ok ? '已保存' : (result.detail || '保存失败');
              if (res.ok) {
                document.getElementById('detailOutput').textContent = 卡片详情文本(result);
                loadGraph('local');
                loadMechanisms();
                loadCards();
              }
            }

            async function runBrief() {
              const question = document.getElementById('question').value.trim();
              if (!question) return;
              document.getElementById('briefStatus').textContent = '生成中...';
              const res = await fetch('/api/query-brief', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question, routing_limit: 40 })
              });
              const result = await res.json();
              document.getElementById('briefStatus').textContent = res.ok ? '完成' : '失败';
              if (res.ok) {
                if (result && result.vcp_native) {
                  document.getElementById('briefOutput').textContent = [
                    `模式：VCP 原生结果 + Memlink 原始补充`,
                    `问题：${result.question || question}`,
                    `路由理由：${result.routing_reason || ''}`,
                    '',
                    `【VCP 原生结果】`,
                    JSON.stringify(result.vcp_native || {}, null, 2),
                    '',
                    `【Memlink 原始补充】`,
                    JSON.stringify(result.memlink_context_raw || [], null, 2),
                    '',
                    `【未匹配到 Memlink 卡的 VCP 结果】`,
                    JSON.stringify(result.unmatched_vcp_results || [], null, 2),
                  ].join('\\n');
                } else if (Array.isArray(result.results)) {
                  document.getElementById('briefOutput').textContent = [
                    `底层引擎：VCP 原生透传`,
                    `问题：${question}`,
                    '',
                    JSON.stringify(result, null, 2)
                  ].join('\\n');
                } else {
                  document.getElementById('briefOutput').textContent = [
                    `问题：${result.question || ''}`,
                    '',
                    `简报：${result.brief || ''}`,
                    '',
                    `相关原因：${result.relevance_reason || ''}`,
                    '',
                    `命中标题：${(result.applied_titles || []).join('，')}`,
                    '',
                    `证据片段：`,
                    ...((result.evidence_snippets || []).map(item => `- ${item}`)),
                    '',
                    `路由理由：${result.routing_reason || ''}`,
                    `置信度：${result.confidence ?? ''}`
                  ].join('\\n');
                }
              } else {
                document.getElementById('briefOutput').textContent = JSON.stringify(result, null, 2);
              }
            }

            async function syncCards() {
              document.getElementById('syncStatus').textContent = '同步中...';
              const res = await fetch('/api/sync', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ days: 30 })
              });
              const result = await res.json();
              document.getElementById('syncStatus').textContent = res.ok ? `已同步 ${result.synced} 条` : '同步失败';
              loadCards();
            }

            attachGraphInteractions();
            loadCards();
          </script>
        </body>
        </html>
        """
    )
    html = (
        html
        .replace("__BG__", bg_b64)
        .replace("__SHRINE__", shrine_b64)
        .replace("__ICON1__", icon1_b64)
        .replace("__ICON2__", icon2_b64)
        .replace("__ICON3__", icon3_b64)
        .replace("__ICON4__", icon4_b64)
    )
    return html


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("memlink_shrine.web:app", host="127.0.0.1", port=7861, reload=False)




