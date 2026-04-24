from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


NETWORK_ERROR_PATTERNS = (
    "stream disconnected before completion: error sending request for url",
    "unable to read data from the transport connection",
    "connection timed out",
    "connection timeout",
    "context deadline exceeded",
    "connection refused",
    "network is unreachable",
    "socket",
    "transport connection",
)
OVERLOAD_PATTERNS = ("server_overloaded", "selected model is at capacity")
USAGE_PATTERNS = ("usage_limit_exceeded", "you've hit your usage limit")


@dataclass
class CodexStatusSignal:
    status: str
    signal_source: str
    last_issue_at: str = ""
    last_success_at: str = ""
    issue_type: str = ""
    issue_message: str = ""


def _parse_iso(value: str | None) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _codex_home() -> Path:
    return Path.home() / ".codex"


def _latest_session_paths(limit: int = 3) -> list[Path]:
    root = _codex_home() / "sessions"
    if not root.exists():
        return []
    files = sorted(root.rglob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    return files[:limit]


def _read_tail_lines(path: Path, limit: int = 500) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    return lines[-limit:]


def _classify_error(payload: dict[str, object]) -> tuple[str, str]:
    message = str(payload.get("message") or "").strip()
    info = str(payload.get("codex_error_info") or "").strip().lower()
    lowered = message.lower()
    if info in OVERLOAD_PATTERNS or any(pattern in lowered for pattern in OVERLOAD_PATTERNS):
        return "overloaded", message
    if info in USAGE_PATTERNS or any(pattern in lowered for pattern in USAGE_PATTERNS):
        return "usage_limit", message
    if any(pattern in lowered for pattern in NETWORK_ERROR_PATTERNS):
        return "network_error", message
    return "other_error", message


def probe_codex_signal() -> CodexStatusSignal:
    latest_success_at = 0.0
    latest_success_text = ""
    latest_issue_at = 0.0
    latest_issue_type = ""
    latest_issue_text = ""

    for path in _latest_session_paths():
        for line in _read_tail_lines(path):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = row.get("payload") if isinstance(row, dict) else None
            if not isinstance(payload, dict):
                continue
            timestamp = _parse_iso(str(row.get("timestamp") or ""))
            if row.get("type") == "event_msg" and payload.get("type") == "error":
                issue_type, issue_text = _classify_error(payload)
                if issue_type == "network_error" and timestamp >= latest_issue_at:
                    latest_issue_at = timestamp
                    latest_issue_type = issue_type
                    latest_issue_text = issue_text
                continue

            payload_type = str(payload.get("type") or "").strip()
            role = str(payload.get("role") or "").strip()
            if payload_type == "message" and role == "assistant" and timestamp >= latest_success_at:
                latest_success_at = timestamp
                latest_success_text = "assistant_message"
            elif payload_type == "agent_message" and timestamp >= latest_success_at:
                latest_success_at = timestamp
                latest_success_text = "agent_message"
            elif payload_type == "task_complete" and timestamp >= latest_success_at:
                latest_success_at = timestamp
                latest_success_text = "task_complete"

    if latest_issue_at and latest_issue_at > latest_success_at:
        return CodexStatusSignal(
            status="network_error",
            signal_source="codex_session_event",
            last_issue_at=datetime.fromtimestamp(latest_issue_at, timezone.utc).isoformat(),
            last_success_at=datetime.fromtimestamp(latest_success_at, timezone.utc).isoformat() if latest_success_at else "",
            issue_type=latest_issue_type,
            issue_message=latest_issue_text,
        )
    if latest_success_at:
        return CodexStatusSignal(
            status="healthy",
            signal_source="codex_session_event",
            last_issue_at=datetime.fromtimestamp(latest_issue_at, timezone.utc).isoformat() if latest_issue_at else "",
            last_success_at=datetime.fromtimestamp(latest_success_at, timezone.utc).isoformat(),
            issue_type=latest_issue_type,
            issue_message=latest_issue_text,
        )
    return CodexStatusSignal(status="neutral", signal_source="codex_session_event")


def main() -> None:
    print(json.dumps(asdict(probe_codex_signal()), ensure_ascii=False))


if __name__ == "__main__":
    main()
