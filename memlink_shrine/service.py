from __future__ import annotations

from pathlib import Path

from .contracts import MemlinkRecallDelegate
from .db import (
    get_card_by_main_id,
    get_cards_by_ids,
    get_cards_by_main_ids,
    list_all_cards,
    list_cards_by_project,
    touch_cards_access,
    upsert_card,
)
from .gemini_librarian import GeminiLibrarian
from .models import CatalogCard, MemoryBrief
from .openmemory_adapter import OpenMemoryAdapter
from .project_fusion import ProjectFusionResolver


class MemlinkShrineService:
    def __init__(
        self,
        openmemory: OpenMemoryAdapter,
        librarian: GeminiLibrarian | None,
        db_path: Path,
        recall_delegate: MemlinkRecallDelegate | None = None,
    ) -> None:
        self.openmemory = openmemory
        self.librarian = librarian
        self.db_path = db_path
        self.recall_delegate = recall_delegate

    def _require_librarian(self) -> GeminiLibrarian:
        if not self.librarian:
            raise RuntimeError("缺少 GOOGLE_API_KEY，当前路由无法调用编目员模型。")
        return self.librarian

    def _require_recall_delegate(self) -> MemlinkRecallDelegate:
        if not self.recall_delegate or not self.recall_delegate.is_enabled():
            raise RuntimeError("当前未配置可用的 recall delegate。")
        return self.recall_delegate

    def sync_recent_memories(self, days: int = 7) -> int:
        librarian = self._require_librarian()
        memories = self.openmemory.list_recent_memories(days=days)
        for memory in memories:
            card = librarian.create_card(memory)
            upsert_card(self.db_path, card)
        return len(memories)

    @staticmethod
    def _explicit_raw_request(question: str) -> bool:
        return any(
            keyword in question
            for keyword in ["原文", "全文", "完整内容", "逐字", "底层记忆", "raw"]
        )

    def _find_origin_anchor(self, card: CatalogCard, max_depth: int = 12) -> CatalogCard | None:
        current = card
        seen: set[str] = set()
        for _ in range(max_depth):
            if current.topology_role == "origin":
                return current
            if not current.upstream_main_ids:
                return current if current.main_id != card.main_id else None
            upstream_id = current.upstream_main_ids[0]
            if not upstream_id or upstream_id in seen:
                return None
            seen.add(upstream_id)
            upstream = get_card_by_main_id(self.db_path, upstream_id)
            if not upstream:
                return None
            current = upstream
        return None

    def _build_context_cards(
        self,
        selected_cards: list[CatalogCard],
        max_neighbors: int = 8,
    ) -> list[CatalogCard]:
        ordered: list[CatalogCard] = []
        seen_raw_ids: set[str] = set()

        def add(card: CatalogCard | None) -> None:
            if not card or card.raw_memory_id in seen_raw_ids:
                return
            seen_raw_ids.add(card.raw_memory_id)
            ordered.append(card)

        for card in selected_cards:
            add(card)
            add(self._find_origin_anchor(card))

        neighbor_ids: list[str] = []
        for card in selected_cards:
            neighbor_ids.extend(card.upstream_main_ids)
            neighbor_ids.extend(card.downstream_main_ids)
        for neighbor in get_cards_by_main_ids(self.db_path, neighbor_ids):
            if len(ordered) >= len(selected_cards) + max_neighbors:
                break
            add(neighbor)

        second_hop_ids: list[str] = []
        for card in ordered:
            second_hop_ids.extend(card.upstream_main_ids)
            second_hop_ids.extend(card.downstream_main_ids)
        for neighbor in get_cards_by_main_ids(self.db_path, second_hop_ids):
            if len(ordered) >= len(selected_cards) + max_neighbors:
                break
            add(neighbor)

        return ordered

    def build_memory_brief(
        self,
        question: str,
        routing_limit: int = 120,
    ) -> MemoryBrief | dict[str, object]:
        delegate = self._require_recall_delegate()
        native_recall_with_context = getattr(delegate, "native_recall_with_context", None)
        if callable(native_recall_with_context):
            return native_recall_with_context(question=question, routing_limit=routing_limit)

        librarian = self._require_librarian()
        selection = delegate.select_candidates(question=question, routing_limit=routing_limit)
        if not selection.selected_raw_memory_ids:
            return MemoryBrief(
                question=question,
                brief="当前没有找到足够相关的记忆候选集合。",
                relevance_reason=selection.reasoning or "未命中候选记忆",
                applied_raw_memory_ids=[],
                applied_titles=[],
                confidence=0.0,
                evidence_snippets=[],
                routing_reason=selection.candidate_scope or selection.reasoning,
            )

        selected_cards = get_cards_by_ids(self.db_path, selection.selected_raw_memory_ids)
        context_cards = self._build_context_cards(selected_cards)
        selected_memories = (
            self.openmemory.get_memories_by_ids(selection.selected_raw_memory_ids)
            if self._explicit_raw_request(question)
            else []
        )
        brief = librarian.create_memory_brief(
            question=question,
            cards=context_cards,
            raw_memories=selected_memories,
            routing_reason=(
                f"{selection.delegate_id}: {selection.reasoning} | 默认使用摘要、正文层与上下游脉络；"
                f"命中 {len(selected_cards)} 条，局部脉络展开到 {len(context_cards)} 张卡。"
            ),
        )
        touch_cards_access(self.db_path, [card.raw_memory_id for card in context_cards])
        return brief

    @staticmethod
    def _raw_project_name(card: CatalogCard) -> str:
        enterprise = card.domain_facets.get("enterprise", {})
        projects = enterprise.get("项目", [])
        if isinstance(projects, list) and projects:
            return str(projects[0])
        return "未归属项目"

    def _fusion_resolver(self, cards: list[CatalogCard] | None = None) -> ProjectFusionResolver:
        return ProjectFusionResolver(cards or list_all_cards(self.db_path))

    def _project_name(self, card: CatalogCard) -> str:
        resolver = self._fusion_resolver()
        return resolver.project_for_card(card).root_project

    def _project_cards(self, seed_card: CatalogCard) -> list[CatalogCard]:
        resolver = self._fusion_resolver()
        cards = resolver.cards_for_seed_root(seed_card)
        if cards:
            return cards
        project_name = self._raw_project_name(seed_card)
        cards = list_cards_by_project(self.db_path, project_name)
        return cards or [seed_card]

    @staticmethod
    def _short_title(card: CatalogCard) -> str:
        title = str(card.title or "").strip()
        if not title:
            return "未命名记忆"
        if "：" in title:
            tail = title.split("：")[-1].strip()
            if tail:
                return tail[:20]
        return title[:20]

    def build_graph_payload(
        self,
        raw_memory_id: str,
        mode: str = "local",
        hops: int = 2,
    ) -> dict:
        seed = get_cards_by_ids(self.db_path, [raw_memory_id])
        if not seed:
            return {"mode": mode, "nodes": [], "edges": [], "focus_main_id": "", "project": ""}
        seed_card = seed[0]
        project_cards = self._project_cards(seed_card)
        resolver = self._fusion_resolver(project_cards)
        by_main = {card.main_id: card for card in project_cards if card.main_id}
        focus_main_id = seed_card.main_id

        include: set[str]
        if mode == "full":
            include = set(by_main.keys())
        else:
            include = {focus_main_id}
            frontier = {focus_main_id}
            for _ in range(max(hops, 1)):
                next_frontier: set[str] = set()
                for main_id in frontier:
                    card = by_main.get(main_id)
                    if not card:
                        continue
                    for neighbor_id in card.upstream_main_ids + card.downstream_main_ids:
                        if neighbor_id and neighbor_id in by_main and neighbor_id not in include:
                            include.add(neighbor_id)
                            next_frontier.add(neighbor_id)
                frontier = next_frontier
                if not frontier:
                    break

        included_cards = [card for card in project_cards if card.main_id in include]
        card_map = {card.main_id: card for card in included_cards}
        incoming: dict[str, set[str]] = {card.main_id: set() for card in included_cards}
        outgoing: dict[str, list[str]] = {card.main_id: [] for card in included_cards}
        edges: list[dict] = []
        for card in included_cards:
            for downstream_id in card.downstream_main_ids:
                downstream_card = card_map.get(downstream_id)
                if downstream_card:
                    outgoing[card.main_id].append(downstream_id)
                    incoming[downstream_id].add(card.main_id)
                    edges.append(
                        {
                            "source": card.main_id,
                            "target": downstream_id,
                            "relation_type": downstream_card.relation_type,
                            "path_status": downstream_card.path_status,
                            "reconnect": downstream_card.relation_type == "resumes_from",
                        }
                    )

        if mode == "full":
            existing_pairs = {(edge["source"], edge["target"]) for edge in edges}
            for edge in resolver.build_fusion_edges(seed_card, included_cards):
                pair = (edge["source"], edge["target"])
                if pair in existing_pairs:
                    continue
                existing_pairs.add(pair)
                edges.append(edge)

        def role_rank(card: CatalogCard) -> tuple[int, str]:
            order = {"origin": 1, "junction": 2, "node": 3, "merge": 4, "exit": 5}
            return (order.get(card.topology_role, 9), card.main_id)

        roots = sorted(
            [card.main_id for card in included_cards if not incoming.get(card.main_id)],
            key=lambda main_id: role_rank(card_map[main_id]),
        )
        if not roots and focus_main_id:
            roots = [focus_main_id]

        levels: dict[str, int] = {}
        lanes: dict[str, int] = {}
        next_lane = 0

        def walk(main_id: str, depth: int, lane: int) -> int:
            nonlocal next_lane
            current_level = levels.get(main_id, -1)
            if depth > current_level:
                levels[main_id] = depth
            lanes.setdefault(main_id, lane)
            children = sorted(outgoing.get(main_id, []))
            cursor_lane = lanes[main_id]
            max_lane = cursor_lane
            for index, child_id in enumerate(children):
                if child_id in lanes:
                    child_lane = lanes[child_id]
                elif index == 0:
                    child_lane = cursor_lane
                else:
                    next_lane += 1
                    child_lane = next_lane
                max_lane = max(max_lane, walk(child_id, depth + 1, child_lane))
            return max_lane

        for root in roots:
            if root in lanes:
                continue
            walk(root, 0, next_lane)
            next_lane += 1

        for main_id in card_map:
            levels.setdefault(main_id, 0)
            lanes.setdefault(main_id, next_lane)
            next_lane += 1

        nodes = []
        for card in included_cards:
            nodes.append(
                {
                    "id": card.main_id,
                    "raw_memory_id": card.raw_memory_id,
                    "title": card.title,
                    "short_title": self._short_title(card),
                    "role": card.topology_role,
                    "path_status": card.path_status,
                    "is_landmark": card.is_landmark,
                    "chain_status": card.chain_status,
                    "posture_summary": card.posture_summary,
                    "emotion_trajectory": card.emotion_trajectory,
                    "focus_anchor_main_id": card.focus_anchor_main_id,
                    "focus_confidence": card.focus_confidence,
                    "focus_reason": card.focus_reason,
                    "reconnectable": card.path_status in {"open_head", "paused"},
                    "project_root": resolver.project_for_card(card).root_project,
                    "project_subproject": resolver.project_for_card(card).subproject,
                    "level": levels.get(card.main_id, 0),
                    "lane": lanes.get(card.main_id, 0),
                    "current": card.main_id == focus_main_id,
                }
            )

        return {
            "mode": mode,
            "project": self._project_name(seed_card),
            "focus_main_id": focus_main_id,
            "nodes": nodes,
            "edges": edges,
        }

    def build_mechanism_payload(self, raw_memory_id: str) -> dict:
        seed = get_cards_by_ids(self.db_path, [raw_memory_id])
        if not seed:
            return {
                "focus": None,
                "parallel_candidates": [],
                "reconnect_targets": [],
                "project": "",
            }
        seed_card = seed[0]
        project_cards = self._project_cards(seed_card)
        by_main = {card.main_id: card for card in project_cards if card.main_id}
        focus_id = seed_card.focus_anchor_main_id or seed_card.main_id
        focus_card = by_main.get(focus_id)

        parallel_candidates: list[dict] = []
        if seed_card.upstream_main_ids:
            parent_id = seed_card.upstream_main_ids[0]
            siblings = [
                card for card in project_cards
                if card.main_id != seed_card.main_id and parent_id in card.upstream_main_ids
            ]
            for sibling in siblings:
                parallel_candidates.append(
                    {
                        "main_id": sibling.main_id,
                        "title": sibling.title,
                        "path_status": sibling.path_status,
                        "topology_role": sibling.topology_role,
                    }
                )

        reconnect_targets = [
            {
                "main_id": card.main_id,
                "title": card.title,
                "path_status": card.path_status,
                "topology_role": card.topology_role,
            }
            for card in project_cards
            if card.path_status in {"open_head", "paused"} and card.main_id != seed_card.main_id
        ]

        return {
            "project": self._project_name(seed_card),
            "focus": {
                "main_id": focus_card.main_id if focus_card else focus_id,
                "title": focus_card.title if focus_card else seed_card.title,
                "confidence": seed_card.focus_confidence,
                "reason": seed_card.focus_reason,
            },
            "current": {
                "main_id": seed_card.main_id,
                "title": seed_card.title,
                "path_status": seed_card.path_status,
                "relation_type": seed_card.relation_type,
            },
            "parallel_candidates": parallel_candidates,
            "reconnect_targets": reconnect_targets,
        }


