from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import CatalogCard


def _clean_name(value: Any, default: str = "") -> str:
    text = " ".join(str(value or "").strip().split())
    return text or default


def _normalize_name(value: Any) -> str:
    return _clean_name(value).casefold()


def _enterprise(card: CatalogCard) -> dict[str, Any]:
    enterprise = (card.domain_facets or {}).get("enterprise", {})
    return enterprise if isinstance(enterprise, dict) else {}


def _codex_session(card: CatalogCard) -> dict[str, Any]:
    session = (card.domain_facets or {}).get("codex_session", {})
    return session if isinstance(session, dict) else {}


def _project_names(card: CatalogCard) -> list[str]:
    enterprise = _enterprise(card)
    values = enterprise.get("项目")
    names: list[str] = []
    if isinstance(values, list):
        names = [_clean_name(item) for item in values if _clean_name(item)]
    elif values:
        names = [_clean_name(values)]
    project = _clean_name(enterprise.get("project"))
    if project and project not in names:
        names.append(project)
    return names


def _thread_name(card: CatalogCard) -> str:
    return _clean_name(_codex_session(card).get("thread_name"))


def _is_project_naming(card: CatalogCard) -> bool:
    base = card.base_facets or {}
    return _clean_name(base.get("memory_subtype")) == "project_naming"


def _timestamp_key(card: CatalogCard) -> str:
    return _clean_name(
        card.updated_at
        or card.created_at
        or card.projection_created_at
        or card.raw_memory_created_at
    )


def _role_rank(card: CatalogCard) -> int:
    order = {"origin": 0, "junction": 1, "node": 2, "merge": 3, "exit": 4}
    return order.get(card.topology_role, 9)


@dataclass(frozen=True)
class ProjectProjection:
    raw_project: str
    root_project: str
    subproject: str
    project_path: list[str]
    aliases: list[str]
    source: str


class ProjectFusionResolver:
    def __init__(self, cards: list[CatalogCard]) -> None:
        self.cards = cards
        self.alias_to_root: dict[str, str] = {}
        self.root_aliases: dict[str, list[str]] = {}
        self._build_aliases(cards)

    def _build_aliases(self, cards: list[CatalogCard]) -> None:
        naming_cards = sorted(
            [card for card in cards if _is_project_naming(card)],
            key=_timestamp_key,
            reverse=True,
        )
        for card in naming_cards:
            aliases = _project_names(card)
            if not aliases:
                continue
            root = aliases[0]
            root_key = _normalize_name(root)
            seen: list[str] = []
            for alias in aliases:
                clean = _clean_name(alias)
                key = _normalize_name(clean)
                if not clean or not key:
                    continue
                if clean not in seen:
                    seen.append(clean)
                self.alias_to_root.setdefault(key, root)
            if root not in seen:
                seen.insert(0, root)
            self.root_aliases[root_key] = seen

    def resolve_root(self, raw_project: str) -> str:
        clean = _clean_name(raw_project, "未归属项目")
        key = _normalize_name(clean)
        return self.alias_to_root.get(key, clean)

    def aliases_for_root(self, root_project: str) -> list[str]:
        root_key = _normalize_name(root_project)
        aliases = list(self.root_aliases.get(root_key, []))
        if root_project and root_project not in aliases:
            aliases.insert(0, root_project)
        return aliases or [root_project]

    def project_for_card(self, card: CatalogCard) -> ProjectProjection:
        raw_project = _project_names(card)[0] if _project_names(card) else "未归属项目"
        root_project = self.resolve_root(raw_project)
        raw_key = _normalize_name(raw_project)
        root_key = _normalize_name(root_project)
        thread_name = _thread_name(card)
        if raw_key and raw_key != root_key:
            subproject = raw_project
            source = "project_alias"
        elif thread_name and _normalize_name(thread_name) != root_key:
            subproject = thread_name
            source = "thread_name"
        else:
            subproject = ""
            source = "root"
        path = [root_project]
        if subproject:
            path.append(subproject)
        return ProjectProjection(
            raw_project=raw_project,
            root_project=root_project,
            subproject=subproject,
            project_path=path,
            aliases=self.aliases_for_root(root_project),
            source=source,
        )

    def enrich_card_dict(self, card: CatalogCard) -> dict[str, Any]:
        payload = card.as_dict()
        projection = self.project_for_card(card)
        payload["project_root"] = projection.root_project
        payload["project_subproject"] = projection.subproject
        payload["project_path"] = projection.project_path
        payload["project_source_name"] = projection.raw_project
        payload["project_aliases"] = projection.aliases
        payload["project_path_source"] = projection.source
        return payload

    def cards_for_root(self, root_project: str) -> list[CatalogCard]:
        root_key = _normalize_name(root_project)
        return [card for card in self.cards if _normalize_name(self.project_for_card(card).root_project) == root_key]

    def cards_for_seed_root(self, seed_card: CatalogCard) -> list[CatalogCard]:
        return self.cards_for_root(self.project_for_card(seed_card).root_project)

    def choose_anchor(self, cards: list[CatalogCard]) -> CatalogCard | None:
        if not cards:
            return None
        ordered = sorted(
            cards,
            key=lambda card: (
                0 if _is_project_naming(card) else 1,
                0 if card.is_landmark else 1,
                _role_rank(card),
                _timestamp_key(card),
                _clean_name(card.title, "未命名记忆"),
            ),
        )
        return ordered[0]

    def build_fusion_edges(self, seed_card: CatalogCard, included_cards: list[CatalogCard]) -> list[dict[str, Any]]:
        root_project = self.project_for_card(seed_card).root_project
        root_key = _normalize_name(root_project)
        by_projection: dict[str, list[CatalogCard]] = {}
        root_cards: list[CatalogCard] = []
        for card in included_cards:
            projection = self.project_for_card(card)
            if _normalize_name(projection.root_project) != root_key:
                continue
            if projection.subproject:
                by_projection.setdefault(projection.subproject, []).append(card)
            else:
                root_cards.append(card)

        root_anchor = self.choose_anchor(root_cards) or self.choose_anchor(included_cards)
        if not root_anchor or not root_anchor.main_id:
            return []

        synthetic_edges: list[dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for subproject, cards in sorted(by_projection.items()):
            anchor = self.choose_anchor(cards)
            if not anchor or not anchor.main_id or anchor.main_id == root_anchor.main_id:
                continue
            pair = (root_anchor.main_id, anchor.main_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            synthetic_edges.append(
                {
                    "source": root_anchor.main_id,
                    "target": anchor.main_id,
                    "relation_type": "project_fusion",
                    "path_status": "",
                    "reconnect": False,
                    "synthetic": True,
                    "label": f"汇入 {root_project}",
                    "subproject": subproject,
                }
            )
        return synthetic_edges
