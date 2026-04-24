from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from .config import Settings
from .contracts import RecallSelectionResult
from .db import list_all_cards, list_cards_for_routing
from .gemini_librarian import GeminiLibrarian
from .models import CatalogCard


class LocalCatalogRecallDelegate:
    delegate_id = "local_catalog"

    def __init__(self, db_path, librarian: GeminiLibrarian | None) -> None:
        self.db_path = db_path
        self.librarian = librarian

    def is_enabled(self) -> bool:
        return self.librarian is not None

    def select_candidates(
        self,
        *,
        question: str,
        routing_limit: int,
    ) -> RecallSelectionResult:
        if not self.librarian:
            raise RuntimeError("缺少 GOOGLE_API_KEY，当前召回委托无法调用编目员模型。")

        cards = list_cards_for_routing(self.db_path, limit=routing_limit)
        if not cards:
            return RecallSelectionResult(
                delegate_id=self.delegate_id,
                reasoning="目录卡为空",
                selected_raw_memory_ids=[],
                candidate_scope="no_cards_available",
            )

        selection = self.librarian.select_candidate_cards(question, cards)
        return RecallSelectionResult(
            delegate_id=self.delegate_id,
            reasoning=selection.reasoning or "未命中候选记忆",
            selected_raw_memory_ids=selection.selected_raw_memory_ids,
            candidate_scope=selection.candidate_scope,
            details={
                "selected_titles": selection.selected_titles,
                "catalog_size": len(cards),
            },
        )


def _normalize_vcp_path(value: str | None) -> str:
    return str(value or "").strip().replace("\\", "/").lstrip("/")


def _slug(value: str) -> str:
    clean = re.sub(r"[^\w\-.]+", "-", value.strip(), flags=re.UNICODE).strip("-._")
    return clean or "query"


def _vcp_associative_endpoints(base_url: str) -> list[str]:
    clean = base_url.rstrip("/")
    if not clean:
        return []
    if clean.endswith("/associative-discovery"):
        return [clean]
    candidates: list[str] = []
    if clean.endswith("/admin_api/dailynotes") or clean.endswith("/dailynotes"):
        candidates.append(f"{clean}/associative-discovery")
    else:
        candidates.append(f"{clean}/associative-discovery")
        candidates.append(f"{clean}/admin_api/dailynotes/associative-discovery")
    return list(dict.fromkeys(candidates))


def _request_vcp_json(
    *,
    url: str,
    payload: dict[str, object],
    username: str,
    password: str,
    timeout_seconds: float,
) -> dict[str, object]:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }
    if username and password:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads((response.read().decode("utf-8") or "{}").strip())


def _call_vcp_associative_discovery(
    *,
    settings: Settings,
    source_file_path: str,
    k: int,
    range_names: list[str],
    tag_boost: float = 0.15,
) -> dict[str, object]:
    payload = {
        "sourceFilePath": source_file_path,
        "k": k,
        "range": range_names,
        "tagBoost": tag_boost,
    }
    errors: list[str] = []
    for url in _vcp_associative_endpoints(settings.vcp_base_url):
        try:
            return _request_vcp_json(
                url=url,
                payload=payload,
                username=settings.vcp_admin_username,
                password=settings.vcp_admin_password,
                timeout_seconds=settings.vcp_timeout_seconds,
            )
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


class VcpRecallDelegate:
    delegate_id = "vcp"

    def __init__(self, *, settings: Settings, db_path: Path) -> None:
        self.settings = settings
        self.db_path = db_path

    def is_enabled(self) -> bool:
        return bool(
            self.settings.vcp_base_url
            and self.settings.vcp_bridge_root_path
            and self.settings.vcp_bridge_namespace
        )

    def _write_query_bridge_file(self, question: str) -> tuple[Path, str]:
        root = self.settings.vcp_bridge_root_path
        if root is None:
            raise RuntimeError("未配置 VCP_BRIDGE_ROOT_PATH")
        digest = hashlib.sha1(question.encode("utf-8")).hexdigest()[:10]
        filename = f"__memlink_query__-{_slug(question)[:48]}-{digest}.txt"
        relative = f"{self.settings.vcp_bridge_namespace}/{filename}"
        full_path = (root / relative).resolve()
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(
            (
                "Memlink Shrine Recall Query\n"
                f"问题: {question}\n"
                "用途: 仅作为底层召回与联想种子，不写入正式记忆卡。\n"
            ),
            encoding="utf-8",
        )
        return full_path, relative.replace("\\", "/")

    def _path_to_card_map(self) -> dict[str, CatalogCard]:
        mapping: dict[str, CatalogCard] = {}
        for card in list_all_cards(self.db_path):
            semantic = card.semantic_facets or {}
            relative = _normalize_vcp_path(str(semantic.get("vcp_source_path") or ""))
            if not relative:
                continue
            mapping.setdefault(relative, card)
            mapping.setdefault(Path(relative).name.lower(), card)
        return mapping

    def select_candidates(
        self,
        *,
        question: str,
        routing_limit: int,
    ) -> RecallSelectionResult:
        if not self.is_enabled():
            raise RuntimeError("VCP recall delegate 当前不可用。")

        query_file, relative_path = self._write_query_bridge_file(question)
        try:
            payload = _call_vcp_associative_discovery(
                settings=self.settings,
                source_file_path=relative_path,
                k=max(8, min(max(routing_limit, 8), 48)),
                range_names=[self.settings.vcp_bridge_namespace],
                tag_boost=0.15,
            )
        finally:
            try:
                query_file.unlink(missing_ok=True)
            except OSError:
                pass

        results = payload.get("results")
        items = results if isinstance(results, list) else []
        path_map = self._path_to_card_map()
        selected_ids: list[str] = []
        score_pairs: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            path_value = _normalize_vcp_path(str(item.get("path") or item.get("sourceFilePath") or ""))
            lookup_key = path_value or str(item.get("name") or "").strip().lower()
            card = path_map.get(lookup_key) or path_map.get(Path(lookup_key).name.lower())
            if not card or card.raw_memory_id in selected_ids:
                continue
            selected_ids.append(card.raw_memory_id)
            try:
                score_text = f"{float(item.get('score') or 0):.3f}"
            except (TypeError, ValueError):
                score_text = "0.000"
            score_pairs.append(f"{card.title}={score_text}")

        warning = str(payload.get("warning") or "").strip()
        unique_files = payload.get("metadata", {}).get("uniqueFilesFound") if isinstance(payload.get("metadata"), dict) else None
        reasoning_parts = [
            f"VCP 基于当前问题做底层联想召回，候选文件 {unique_files if unique_files is not None else len(items)} 个。",
        ]
        if score_pairs:
            reasoning_parts.append("命中卡片：" + "；".join(score_pairs[:8]))
        if warning:
            reasoning_parts.append(f"提示：{warning}")

        return RecallSelectionResult(
            delegate_id=self.delegate_id,
            reasoning=" ".join(reasoning_parts).strip(),
            selected_raw_memory_ids=selected_ids,
            candidate_scope=f"vcp_associative_discovery:{self.settings.vcp_bridge_namespace}",
            details={
                "result_count": len(items),
                "selected_count": len(selected_ids),
                "warning": warning,
                "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            },
        )

    def _run_native_recall(
        self,
        *,
        question: str,
        routing_limit: int,
    ) -> tuple[dict[str, object], Path]:
        if not self.is_enabled():
            raise RuntimeError("VCP recall delegate 当前不可用。")

        query_file, relative_path = self._write_query_bridge_file(question)
        payload = _call_vcp_associative_discovery(
            settings=self.settings,
            source_file_path=relative_path,
            k=max(8, min(max(routing_limit, 8), 48)),
            range_names=[self.settings.vcp_bridge_namespace],
            tag_boost=0.15,
        )
        return payload, query_file

    def native_recall(
        self,
        *,
        question: str,
        routing_limit: int,
    ) -> dict[str, object]:
        payload, query_file = self._run_native_recall(
            question=question,
            routing_limit=routing_limit,
        )
        try:
            return payload
        finally:
            try:
                query_file.unlink(missing_ok=True)
            except OSError:
                pass

    def native_recall_with_context(
        self,
        *,
        question: str,
        routing_limit: int,
    ) -> dict[str, object]:
        payload, query_file = self._run_native_recall(
            question=question,
            routing_limit=routing_limit,
        )
        try:
            items = payload.get("results")
            results = items if isinstance(items, list) else []
            path_map = self._path_to_card_map()
            context_rows: list[dict[str, object]] = []
            unmatched_rows: list[dict[str, object]] = []

            for item in results:
                if not isinstance(item, dict):
                    continue
                path_value = _normalize_vcp_path(str(item.get("path") or item.get("sourceFilePath") or ""))
                lookup_key = path_value or str(item.get("name") or "").strip().lower()
                card = path_map.get(lookup_key) or path_map.get(Path(lookup_key).name.lower())
                if card:
                    context_rows.append(
                        {
                            "vcp_match": item,
                            "memlink_raw": card.as_dict(),
                        }
                    )
                else:
                    unmatched_rows.append(item)

            return {
                "mode": "vcp_native_plus_memlink_raw",
                "question": question,
                "engine": self.delegate_id,
                "routing_reason": (
                    "VCP 原生结果优先返回；Memlink 只附加自己已有的原始记录资料，不做二次筛选、"
                    "不重排、不改写。"
                ),
                "vcp_native": payload,
                "memlink_context_raw": context_rows,
                "unmatched_vcp_results": unmatched_rows,
            }
        finally:
            try:
                query_file.unlink(missing_ok=True)
            except OSError:
                pass
