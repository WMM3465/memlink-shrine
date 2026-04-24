from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .models import RawMemory


class OpenMemoryAdapter:
    def __init__(self, base_url: str, user_id: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_id = user_id

    def _parse_memory_item(self, item: dict[str, Any]) -> RawMemory:
        return RawMemory(
            id=str(item["id"]),
            user_id=self.user_id,
            app_name=item.get("app_name"),
            content=item.get("content") or item.get("text") or "",
            created_at=item.get("created_at"),
            metadata=item.get("metadata_"),
        )

    def list_recent_memories(
        self,
        days: int = 7,
        page_size: int = 100,
        max_pages: int = 10,
    ) -> list[RawMemory]:
        from_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
        memories: list[RawMemory] = []

        for page in range(1, max_pages + 1):
            response = requests.get(
                f"{self.base_url}/api/v1/memories/",
                params={
                    "user_id": self.user_id,
                    "page": page,
                    "page_size": page_size,
                    "from_date": from_ts,
                    "sort_column": "created_at",
                    "sort_direction": "desc",
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items", [])
            memories.extend(self._parse_memory_item(item) for item in items)
            if len(items) < page_size:
                break

        return memories

    def get_memory(self, memory_id: str) -> RawMemory:
        response = requests.get(
            f"{self.base_url}/api/v1/memories/{memory_id}",
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return self._parse_memory_item(payload)

    def get_memories_by_ids(self, memory_ids: list[str]) -> list[RawMemory]:
        return [self.get_memory(memory_id) for memory_id in memory_ids]
