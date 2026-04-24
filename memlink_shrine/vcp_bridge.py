from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import load_settings
from .contracts import WriteAdapterReceipt
from .models import CatalogCard


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^\w\-.]+", "-", text.strip(), flags=re.UNICODE).strip("-._")
    return cleaned or "memory-card"


def _flatten_text(value: Any) -> str:
    if isinstance(value, list):
        return "，".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _enterprise_project(card: CatalogCard) -> str:
    enterprise = (card.domain_facets or {}).get("enterprise", {})
    if not isinstance(enterprise, dict):
        return ""
    for key in ("项目", "project"):
        value = enterprise.get(key)
        if isinstance(value, list):
            for item in value:
                clean = str(item or "").strip()
                if clean:
                    return clean
        clean = str(value or "").strip()
        if clean:
            return clean
    return ""


def _bridge_filename(card: CatalogCard) -> str:
    seed = card.main_id or card.raw_memory_id or card.title
    return f"{_slug(seed)}.txt"


def _ensure_relative_path(card: CatalogCard, namespace: str) -> str:
    semantic = dict(card.semantic_facets or {})
    existing = str(semantic.get("vcp_source_path") or "").strip().replace("\\", "/").lstrip("/")
    if existing:
        return existing
    return f"{namespace}/{_bridge_filename(card)}"


def build_bridge_document(card: CatalogCard) -> str:
    enterprise = (card.domain_facets or {}).get("enterprise", {})
    semantic = card.semantic_facets or {}
    lines = [
        f"标题: {card.title}",
        f"主ID: {card.main_id}",
        f"原始ID: {card.raw_memory_id}",
    ]
    project = _enterprise_project(card)
    if project:
        lines.append(f"项目: {project}")
    topics = _flatten_text((card.base_facets or {}).get("topic"))
    if topics:
        lines.append(f"主题标签: {topics}")
    if card.fact_summary:
        lines.append(f"事实摘要: {card.fact_summary}")
    if card.meaning_summary:
        lines.append(f"意义摘要: {card.meaning_summary}")
    if card.posture_summary:
        lines.append(f"姿态摘要: {card.posture_summary}")
    if card.emotion_trajectory:
        lines.append(f"情绪轨迹: {card.emotion_trajectory}")
    semantic_project = _flatten_text(semantic.get("project") or semantic.get("项目"))
    if semantic_project:
        lines.append(f"语义项目: {semantic_project}")
    if isinstance(enterprise, dict):
        enterprise_lines = []
        for key, value in enterprise.items():
            text = _flatten_text(value)
            if text:
                enterprise_lines.append(f"{key}: {text}")
        if enterprise_lines:
            lines.append("企业维度: " + " | ".join(enterprise_lines))
    body = card.body_text or card.raw_text
    if body:
        lines.append("")
        lines.append("正文:")
        lines.append(body)
    elif card.raw_text:
        lines.append("")
        lines.append("原文:")
        lines.append(card.raw_text)
    return "\n".join(lines).strip() + "\n"


class VcpBridgeWriteAdapter:
    adapter_id = "vcp_bridge"

    def __init__(self, settings=None) -> None:
        self.settings = settings or load_settings()

    def is_enabled(self) -> bool:
        return self.settings.vcp_bridge_root_path is not None

    def write_card(self, card: CatalogCard) -> tuple[CatalogCard, WriteAdapterReceipt | None]:
        root = self.settings.vcp_bridge_root_path
        if root is None:
            return card, None

        relative_path = _ensure_relative_path(card, self.settings.vcp_bridge_namespace)
        full_path = (root / relative_path).resolve()
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(build_bridge_document(card), encoding="utf-8")

        semantic = dict(card.semantic_facets or {})
        semantic["vcp_source_path"] = relative_path.replace("\\", "/")
        semantic["vcp_range"] = [self.settings.vcp_bridge_namespace]

        updated_card = card
        if semantic != (card.semantic_facets or {}):
            updated = card.as_dict()
            updated["semantic_facets"] = semantic
            updated_card = CatalogCard(**updated)

        return updated_card, WriteAdapterReceipt(
            adapter_id=self.adapter_id,
            delivered=True,
            external_ref=relative_path.replace("\\", "/"),
            details={"namespace": self.settings.vcp_bridge_namespace},
        )


def bridge_card(card: CatalogCard) -> CatalogCard:
    adapter = VcpBridgeWriteAdapter(load_settings())
    updated, _receipt = adapter.write_card(card)
    return updated
