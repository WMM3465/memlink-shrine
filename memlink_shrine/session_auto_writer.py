from __future__ import annotations

import json
import os
import re
import time
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_settings
from .db import init_db
from .direct_write import create_direct_card
from .id_schema import build_default_main_id
from .models import CatalogCard
from .runtime_paths import runtime_root
from .source_rules import DEFAULT_PARALLEL_RULE, infer_frontend_name


SESSION_GATE_FILE = Path("data/session_memory_gate.json")
AUTO_WRITER_STATE_FILE = Path("data/session_auto_writer_state.json")
PASSIVE_TRIGGERS = (
    "记住",
    "记下来",
    "写进memory",
    "写入memory",
    "写进记忆",
    "写入记忆",
    "存起来",
    "存进memory",
)
SESSION_ID_PATTERN = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.IGNORECASE)


@dataclass
class SessionMessage:
    timestamp: str
    role: str
    text: str


@dataclass
class SessionSnapshot:
    session_id: str
    thread_name: str
    updated_at: str
    path: Path


@dataclass
class TriggerDecision:
    should_write: bool
    reason: str
    mode: str


@dataclass
class TickResult:
    checked_sessions: int = 0
    new_messages: int = 0
    written_cards: list[dict[str, Any]] = field(default_factory=list)
    pending_drafts: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def project_root() -> Path:
    return runtime_root()


def data_path(relative: Path) -> Path:
    path = project_root() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def resolve_host_id(host_id: str | None = None) -> str:
    candidate = str(host_id or os.getenv("MEMLINK_SHRINE_HOST_ID") or "default").strip().lower()
    normalized = re.sub(r"[^a-z0-9._-]+", "-", candidate).strip(".-_")
    return normalized or "default"


def _hosted_path(relative: Path, host_id: str | None = None) -> Path:
    host = resolve_host_id(host_id)
    name = relative.name
    dot = name.rfind(".")
    if dot > 0:
        host_name = f"{name[:dot]}.{host}{name[dot:]}"
    else:
        host_name = f"{name}.{host}"
    return data_path(relative.with_name(host_name))


def _read_json_with_legacy(path: Path, legacy_path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if path.exists():
        return read_json(path, default)
    if legacy_path.exists():
        return read_json(legacy_path, default)
    return default


def codex_home() -> Path:
    return Path(os.getenv("CODEX_HOME") or Path.home() / ".codex")


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_session_gate(host_id: str | None = None) -> dict[str, Any]:
    state = _read_json_with_legacy(
        _hosted_path(SESSION_GATE_FILE, host_id),
        data_path(SESSION_GATE_FILE),
        {
            "mode": "passive",
            "confirm_before_write": True,
            "selected_models": {},
            "available_graphs": [],
        },
    )
    mode = str(state.get("mode") or "off").strip()
    if mode not in {"off", "passive", "auto"}:
        mode = "off"
    state["mode"] = mode
    state.setdefault("confirm_before_write", True)
    state.setdefault("selected_models", {})
    if not isinstance(state.get("available_graphs"), list):
        state["available_graphs"] = []
    return state


def build_memory_points_from_text(text: str, *, limit: int = 6) -> list[str]:
    points: list[str] = []
    seen: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = re.sub(r"^\[[^\]]+\]\s*(用户|Codex):\s*", "", raw_line).strip()
        for fragment in split_memory_fragments(line):
            normalized = re.sub(r"\s+", "", fragment)
            if not normalized:
                continue
            duplicate = False
            for old in seen:
                if normalized in old or old in normalized:
                    duplicate = True
                    break
            if duplicate:
                continue
            seen.append(normalized)
            points.append(fragment)
            if len(points) >= limit:
                return points
    return points


def hydrate_pending_draft_preview(draft: dict[str, Any]) -> dict[str, Any]:
    preview = draft.get("preview") if isinstance(draft.get("preview"), dict) else {}
    payload = draft.get("payload") if isinstance(draft.get("payload"), dict) else {}
    points = preview.get("memory_points")
    if isinstance(points, list) and any(str(item).strip() for item in points):
        return draft
    source_text = str(payload.get("raw_text") or preview.get("raw_excerpt") or "")
    rebuilt = build_memory_points_from_text(source_text)
    if not rebuilt:
        rebuilt = [
            str(preview.get("title") or payload.get("title") or "").strip(),
            str(preview.get("fact_summary") or payload.get("fact_summary") or "").strip(),
            str(preview.get("meaning_summary") or payload.get("meaning_summary") or "").strip(),
        ]
        rebuilt = [item for item in rebuilt if item]
    preview = dict(preview)
    preview["memory_points"] = rebuilt
    graph_assignments = preview.get("graph_assignments")
    if not isinstance(graph_assignments, list) or not graph_assignments:
        default_graph = str(draft.get("thread_name") or payload.get("title") or "未归属项目").strip()
        preview["graph_assignments"] = [default_graph] * len(rebuilt)
    draft = dict(draft)
    draft["preview"] = preview
    return draft


def load_state(host_id: str | None = None) -> dict[str, Any]:
    path = _hosted_path(AUTO_WRITER_STATE_FILE, host_id)
    state = _read_json_with_legacy(path, data_path(AUTO_WRITER_STATE_FILE), {"sessions": {}, "pending_drafts": {}})
    state.setdefault("sessions", {})
    state.setdefault("pending_drafts", {})
    upgraded: dict[str, Any] = {}
    changed = False
    for key, value in state["pending_drafts"].items():
        if isinstance(value, dict):
            new_value = hydrate_pending_draft_preview(value)
            upgraded[key] = new_value
            if new_value != value:
                changed = True
        else:
            upgraded[key] = value
    state["pending_drafts"] = upgraded
    if changed:
        write_json(path, state)
    return state


def save_state(state: dict[str, Any], host_id: str | None = None) -> None:
    state["updated_at"] = CatalogCard.now_iso()
    write_json(_hosted_path(AUTO_WRITER_STATE_FILE, host_id), state)


def parse_iso_to_timestamp(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        normalized = re.sub(r"\.(\d{6})\d+(?=Z|[+-]\d\d:?\d\d|$)", r".\1", value.strip())
        return datetime.fromisoformat(normalized.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def latest_session_rows(limit: int = 6) -> list[dict[str, Any]]:
    index_path = codex_home() / "session_index.jsonl"
    if not index_path.exists():
        return []
    rows: dict[str, dict[str, Any]] = {}
    for line in index_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        session_id = str(row.get("id") or "").strip()
        if not session_id:
            continue
        rows[session_id] = row
    ordered = sorted(
        rows.values(),
        key=lambda row: parse_iso_to_timestamp(str(row.get("updated_at") or "")),
        reverse=True,
    )
    return ordered[:limit]


def find_session_file(session_id: str) -> Path | None:
    sessions_root = codex_home() / "sessions"
    if not sessions_root.exists():
        return None
    matches = list(sessions_root.rglob(f"*{session_id}*.jsonl"))
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def session_id_from_path(path: Path) -> str:
    match = SESSION_ID_PATTERN.search(path.name)
    return match.group(1) if match else path.stem


def discover_sessions(limit: int = 4) -> list[SessionSnapshot]:
    rows_by_id: dict[str, dict[str, Any]] = {}
    snapshots_by_id: dict[str, SessionSnapshot] = {}
    row_limit = max(limit * 3, limit)
    for row in latest_session_rows(limit=row_limit):
        session_id = str(row.get("id") or "").strip()
        if session_id:
            rows_by_id[session_id] = row
        path = find_session_file(session_id)
        if not path:
            continue
        snapshots_by_id[session_id] = SessionSnapshot(
            session_id=session_id,
            thread_name=str(row.get("thread_name") or "Codex 会话").strip() or "Codex 会话",
            updated_at=str(row.get("updated_at") or ""),
            path=path,
        )

    sessions_root = codex_home() / "sessions"
    if sessions_root.exists():
        recent_files = sorted(
            sessions_root.rglob("rollout-*.jsonl"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )[: max(row_limit, 12)]
        for path in recent_files:
            session_id = session_id_from_path(path)
            row = rows_by_id.get(session_id, {})
            updated_at = str(row.get("updated_at") or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat())
            thread_name = str(row.get("thread_name") or path.stem).strip() or "Codex 会话"
            snapshots_by_id[session_id] = SessionSnapshot(
                session_id=session_id,
                thread_name=thread_name,
                updated_at=updated_at,
                path=path,
            )

    return sorted(
        snapshots_by_id.values(),
        key=lambda snapshot: snapshot.path.stat().st_mtime,
        reverse=True,
    )[:limit]


def read_new_jsonl(path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], offset
    size = path.stat().st_size
    if offset < 0 or offset > size:
        offset = size
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read()
        new_offset = handle.tell()
    lines = data.decode("utf-8", errors="ignore").splitlines()
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events, new_offset


def read_tail_events(path: Path, tail_lines: int = 240) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    events: list[dict[str, Any]] = []
    for line in raw[-tail_lines:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def content_text_from_message(payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in payload.get("content") or []:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    return "\n".join(chunks).strip()


def clean_message_text(role: str, text: str) -> str:
    text = text.strip()
    if text.startswith("<turn_aborted>"):
        return ""
    text = re.sub(
        r"(?is)^# AGENTS\.md instructions.*?</environment_context>\s*",
        "",
        text,
    )
    if role == "user" and "## My request for Codex:" in text:
        text = text.split("## My request for Codex:", 1)[1].strip()
    text = re.sub(r"<image[^>]*>\s*</image>", "[图片]", text, flags=re.IGNORECASE | re.DOTALL)
    return text.strip()


def extract_messages(events: list[dict[str, Any]]) -> list[SessionMessage]:
    messages: list[SessionMessage] = []
    for event in events:
        if event.get("type") != "response_item":
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, dict) or payload.get("type") != "message":
            continue
        if payload.get("phase") == "commentary":
            continue
        role = str(payload.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        text = content_text_from_message(payload)
        text = clean_message_text(role, text)
        if not text:
            continue
        messages.append(
            SessionMessage(
                timestamp=str(event.get("timestamp") or CatalogCard.now_iso()),
                role=role,
                text=text,
            )
        )
    return messages


def trim_buffer(messages: list[dict[str, str]], max_messages: int = 80) -> list[dict[str, str]]:
    if len(messages) <= max_messages:
        return messages
    return messages[-max_messages:]


def buffer_fingerprint(buffer: list[dict[str, str]]) -> str:
    digest = hashlib.sha1()
    for msg in buffer:
        digest.update(str(msg.get("timestamp") or "").encode("utf-8"))
        digest.update(b"|")
        digest.update(str(msg.get("role") or "").encode("utf-8"))
        digest.update(b"|")
        digest.update(str(msg.get("text") or "").encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def message_dicts(messages: list[SessionMessage]) -> list[dict[str, str]]:
    return [{"timestamp": msg.timestamp, "role": msg.role, "text": msg.text} for msg in messages]


def message_timestamp(msg: dict[str, str] | SessionMessage) -> float:
    if isinstance(msg, SessionMessage):
        return parse_iso_to_timestamp(msg.timestamp)
    return parse_iso_to_timestamp(str(msg.get("timestamp") or ""))


def maybe_reset_segment(
    session_state: dict[str, Any],
    buffer: list[dict[str, str]],
    new_messages: list[SessionMessage],
    *,
    gap_hours: float,
) -> tuple[list[dict[str, str]], str | None]:
    if not buffer or not new_messages or gap_hours <= 0:
        return buffer, None
    previous_messages = buffer[: -len(new_messages)] if len(new_messages) <= len(buffer) else []
    if not previous_messages:
        return buffer, None
    previous_ts = message_timestamp(previous_messages[-1])
    first_new_ts = message_timestamp(new_messages[0])
    if not previous_ts or not first_new_ts:
        return buffer, None
    gap_seconds = first_new_ts - previous_ts
    if gap_seconds < gap_hours * 3600:
        return buffer, None

    anchor = str(session_state.get("last_card_main_id") or "").strip()
    reset_note = f"断档续写：距离上次线程推进约 {gap_seconds / 3600:.1f} 小时；触发计数从新片段重开"
    if anchor:
        reset_note += f"，链路接回 {anchor}"
    session_state["last_segment_reset_at"] = CatalogCard.now_iso()
    session_state["last_segment_gap_hours"] = round(gap_seconds / 3600, 2)
    session_state["last_segment_resume_anchor_main_id"] = anchor
    return message_dicts(new_messages), reset_note


def buffer_text(buffer: list[dict[str, str]], max_chars: int = 18000) -> str:
    lines: list[str] = []
    for msg in buffer:
        role = "用户" if msg.get("role") == "user" else "Codex"
        timestamp = CatalogCard.to_beijing_iso(msg.get("timestamp")) or msg.get("timestamp") or ""
        lines.append(f"[{timestamp}] {role}: {msg.get('text', '').strip()}")
    text = "\n\n".join(lines).strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def summarize_first_user(buffer: list[dict[str, str]]) -> str:
    for msg in buffer:
        if msg.get("role") == "user" and msg.get("text"):
            text = " ".join(msg["text"].split())
            return text[:100]
    return "本轮 Codex 会话"


def summarize_last_user(buffer: list[dict[str, str]]) -> str:
    for msg in reversed(buffer):
        if msg.get("role") == "user" and msg.get("text"):
            text = " ".join(msg["text"].split())
            return text[:120]
    return "本轮对话仍在推进中"


def split_memory_fragments(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    rough_parts: list[str] = []
    for line in normalized.split(" [图片] "):
        line = line.strip()
        if not line:
            continue
        rough_parts.extend(re.split(r"[。！？；;]\s*", line))
    fragments: list[str] = []
    for part in rough_parts:
        part = part.strip(" -•·\t\r\n")
        if not part:
            continue
        if len(part) < 10:
            continue
        if re.search(r"(AGENTS\.md|<INSTRUCTIONS>|</INSTRUCTIONS>|environment_context|OutputEncoding|jsonl|python\.exe)", part, re.IGNORECASE):
            continue
        fragments.append(part[:96])
    return fragments


def build_memory_points(buffer: list[dict[str, str]], *, limit: int = 6) -> list[str]:
    points: list[str] = []
    seen: list[str] = []
    assistant_keywords = (
        "机制",
        "规则",
        "方案",
        "链路",
        "图谱",
        "残影",
        "记忆",
        "召回",
        "写入",
        "分叉",
        "原点",
        "新主题",
        "重复",
        "项目",
        "自动",
        "被动",
        "光标",
        "断档",
    )

    def push(text: str) -> None:
        normalized = re.sub(r"\s+", "", text)
        if not normalized:
            return
        for old in seen:
            if normalized in old or old in normalized:
                return
        seen.append(normalized)
        points.append(text)

    for role in ("user", "assistant"):
        for msg in buffer:
            if msg.get("role") != role:
                continue
            for fragment in split_memory_fragments(str(msg.get("text") or "")):
                if role == "assistant" and not any(keyword in fragment for keyword in assistant_keywords):
                    continue
                push(fragment)
                if len(points) >= limit:
                    return points
    return points


def beijing_day_tag(timestamp: str | None) -> str:
    text = CatalogCard.to_beijing_iso(timestamp) or CatalogCard.now_iso()
    return text[:10]


def position_for(index: int) -> str:
    return f"M{max(index, 0):02d}"


def decide_trigger(
    *,
    mode: str,
    buffer: list[dict[str, str]],
    new_messages: list[SessionMessage],
    turn_threshold: int,
    char_threshold: int,
    hours_threshold: float,
) -> TriggerDecision:
    if mode == "off":
        return TriggerDecision(False, "Memlink Shrine 熄火，暂停写入；读取层仍在线。", mode)
    if not buffer:
        return TriggerDecision(False, "没有可写入的新对话。", mode)
    if not new_messages:
        return TriggerDecision(False, "没有新的线程推进消息。", mode)

    passive_hit = any(
        msg.role == "user" and any(trigger in msg.text for trigger in PASSIVE_TRIGGERS)
        for msg in new_messages
    )
    user_turns = sum(1 for msg in buffer if msg.get("role") == "user")
    chars = sum(len(msg.get("text", "")) for msg in buffer)
    first_ts = parse_iso_to_timestamp(buffer[0].get("timestamp"))
    last_ts = parse_iso_to_timestamp(buffer[-1].get("timestamp"))
    elapsed_hours = max(last_ts - first_ts, 0.0) / 3600 if first_ts and last_ts else 0.0

    mode_label = "被动写入" if mode == "passive" else "自动写入"
    if passive_hit:
        return TriggerDecision(True, f"{mode_label}：用户主动触发写入关键词。", mode)
    if user_turns >= turn_threshold:
        return TriggerDecision(True, f"{mode_label}：用户轮数达到 {user_turns}/{turn_threshold}。", mode)
    if chars >= char_threshold:
        return TriggerDecision(True, f"{mode_label}：缓存字符达到 {chars}/{char_threshold}。", mode)
    if elapsed_hours >= hours_threshold:
        return TriggerDecision(True, f"{mode_label}：持续时间达到 {elapsed_hours:.2f}/{hours_threshold:.2f} 小时。", mode)
    return TriggerDecision(False, f"{mode_label}阈值未达到。", mode)


def refresh_trigger_before_write(
    *,
    previous_decision: TriggerDecision,
    buffer: list[dict[str, str]],
    new_messages: list[SessionMessage],
    turn_threshold: int,
    char_threshold: int,
    hours_threshold: float,
) -> TriggerDecision:
    latest_gate = read_session_gate()
    latest_mode = str(latest_gate.get("mode") or previous_decision.mode or "passive").strip()
    latest_decision = decide_trigger(
        mode=latest_mode,
        buffer=buffer,
        new_messages=new_messages,
        turn_threshold=turn_threshold,
        char_threshold=char_threshold,
        hours_threshold=hours_threshold,
    )
    if latest_mode != previous_decision.mode:
        latest_decision.reason = f"写入前检测到模式已切换：{latest_decision.reason}"
    return latest_decision


def build_card_payload(
    *,
    snapshot: SessionSnapshot,
    buffer: list[dict[str, str]],
    session_state: dict[str, Any],
    trigger_reason: str,
    mode: str,
) -> dict[str, Any]:
    host_id = resolve_host_id()
    first_timestamp = buffer[0].get("timestamp") if buffer else CatalogCard.now_iso()
    last_timestamp = buffer[-1].get("timestamp") if buffer else CatalogCard.now_iso()
    index = int(session_state.get("next_position_index") or 0)
    upstream_main_id = str(session_state.get("last_card_main_id") or "").strip()
    topology_role = "origin" if not upstream_main_id else "node"
    position = position_for(index)
    thread_name = snapshot.thread_name or "Codex 会话"
    title_seed = summarize_first_user(buffer)
    title = f"{thread_name} 自动残影 {index + 1:02d}: {title_seed}"
    raw_text = buffer_text(buffer)
    latest_user = summarize_last_user(buffer)
    day_tag = beijing_day_tag(first_timestamp)
    raw_memory_id = f"codex-session-{snapshot.session_id}-{int(time.time() * 1000)}"

    domain_facets = {
        "enterprise": {
            "project": thread_name,
            "项目": [thread_name],
            "process_stage": "Codex 会话协作",
            "document_asset_type": "对话残影",
        },
        "memory_source": {
            "frontend": infer_frontend_name(source_type=f"codex_session_{host_id}_{mode}", author="codex-session-watcher"),
            "host": host_id,
            "thread": thread_name,
            "session": snapshot.session_id,
            "write_mode": mode,
            "source_role": "witness_model",
            "parallel_rule": DEFAULT_PARALLEL_RULE,
            "relation_note": "",
        },
        "codex_session": {
            "session_id": snapshot.session_id,
            "thread_name": thread_name,
            "mode": mode,
            "host_id": host_id,
        },
    }
    base_facets = {
        "entity": ["Codex", "Memlink Shrine", thread_name],
        "topic": ["自动残影", "现场协作", "Memlink Shrine"],
        "time": [day_tag],
        "status": [mode, "待复检"],
    }
    upstream = [upstream_main_id] if upstream_main_id else []
    payload = {
        "raw_memory_id": raw_memory_id,
        "title": title[:160],
        "fact_summary": (
            f"这是一段来自 Codex 本地 session 的自动残影，时间范围为 "
            f"{CatalogCard.to_beijing_iso(first_timestamp) or first_timestamp} 到 "
            f"{CatalogCard.to_beijing_iso(last_timestamp) or last_timestamp}。"
            f"本段从“{title_seed}”附近开始，最新用户关注点是“{latest_user}”。"
        ),
        "meaning_summary": (
            "这张卡不是把对话压成最终结论，而是保留现场协作的阶段痕迹，"
            "用于未来沿着残影链回到当时的判断入口。"
        ),
        "posture_summary": "知情者模型从现场对话中截取一段可回溯残影，保持过程优先，不预先包装成成功经验。",
        "emotion_trajectory": "本段对话处于推进与校正并存的工作状态，具体情绪需要后续人工或知情者复检。",
        "body_text": raw_text[:6000],
        "raw_text": raw_text,
        "base_facets": base_facets,
        "domain_facets": domain_facets,
        "governance": {
            "shelf_state": "half_open",
            "importance": "normal",
            "pinned": False,
            "confidence": 0.72,
        },
        "main_id": "",
        "upstream_main_ids": upstream,
        "downstream_main_ids": [],
        "relation_type": "continues" if upstream else "originates",
        "topology_role": topology_role,
        "path_status": "active",
        "focus_anchor_main_id": upstream_main_id,
        "focus_confidence": 0.78 if upstream_main_id else 0.0,
        "focus_reason": trigger_reason,
        "is_landmark": False,
        "chain_author": "codex-session-watcher",
        "chain_author_role": "witness_model",
        "chain_status": "witness_confirmed",
        "chain_confidence": 0.72,
        "id_schema_id": "memlink_shrine_default_v2",
        "source_id": snapshot.session_id,
        "source_type": f"codex_session_{host_id}_{mode}",
        "owner": "local-user",
        "visibility": "private",
        "confidence_source": "codex_session_watcher",
        "raw_memory_created_at": first_timestamp,
        "projection_created_at": CatalogCard.now_iso(),
        "projection_based_on": "Codex 本地 session JSONL",
        "facet_pack_id": "enterprise",
        "facet_pack_version": "v1",
        "subgraph": "RET",
        "position": position,
    }
    return payload


def build_pending_draft(
    *,
    snapshot: SessionSnapshot,
    session_state: dict[str, Any],
    buffer: list[dict[str, str]],
    trigger_reason: str,
    mode: str,
) -> dict[str, Any]:
    payload = build_card_payload(
        snapshot=snapshot,
        buffer=buffer,
        session_state=session_state,
        trigger_reason=trigger_reason,
        mode=mode,
    )
    created_at = CatalogCard.now_iso()
    draft_id = f"draft-{snapshot.session_id}-{int(time.time() * 1000)}"
    memory_points = build_memory_points(buffer)
    if not memory_points:
        memory_points = [
            str(payload.get("title") or "未命名残影"),
            str(payload.get("fact_summary") or "暂无事实摘要"),
            str(payload.get("meaning_summary") or "暂无意义摘要"),
        ]
    default_graph = snapshot.thread_name or "未归属项目"
    return {
        "draft_id": draft_id,
        "session_id": snapshot.session_id,
        "thread_name": snapshot.thread_name,
        "created_at": created_at,
        "mode": mode,
        "trigger_reason": trigger_reason,
        "fingerprint": buffer_fingerprint(buffer),
        "message_count": len(buffer),
        "first_message_at": buffer[0].get("timestamp") if buffer else "",
        "last_message_at": buffer[-1].get("timestamp") if buffer else "",
        "preview": {
            "memory_points": memory_points,
            "graph_assignments": [default_graph] * len(memory_points),
            "fact_summary": payload.get("fact_summary", ""),
            "meaning_summary": payload.get("meaning_summary", ""),
            "posture_summary": payload.get("posture_summary", ""),
            "emotion_trajectory": payload.get("emotion_trajectory", ""),
            "raw_excerpt": str(payload.get("raw_text") or "")[:1400],
        },
        "payload": payload,
    }


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _build_point_payloads_from_draft(
    draft: dict[str, Any],
    session_state: dict[str, Any],
) -> list[dict[str, Any]]:
    preview = draft.get("preview", {}) if isinstance(draft.get("preview"), dict) else {}
    base_payload = dict(draft.get("payload") or {})
    points = [str(item).strip() for item in preview.get("memory_points") or [] if str(item).strip()]
    if not points:
        fallback = str(base_payload.get("fact_summary") or base_payload.get("title") or "").strip()
        points = [fallback] if fallback else []
    if not points:
        return []

    graph_assignments = [str(item).strip() for item in preview.get("graph_assignments") or [] if str(item).strip()]
    if not graph_assignments:
        graph_assignments = [str(draft.get("thread_name") or "未归属项目").strip() or "未归属项目"] * len(points)
    if len(graph_assignments) < len(points):
        graph_assignments.extend([graph_assignments[-1]] * (len(points) - len(graph_assignments)))
    graph_assignments = graph_assignments[: len(points)]

    thread_name = str(draft.get("thread_name") or "Codex 会话").strip() or "Codex 会话"
    raw_excerpt = str(preview.get("raw_excerpt") or base_payload.get("raw_text") or "").strip()
    first_timestamp = str(base_payload.get("raw_memory_created_at") or draft.get("first_message_at") or CatalogCard.now_iso())
    base_raw_memory_id = str(base_payload.get("raw_memory_id") or f"codex-session-{draft.get('session_id') or 'unknown'}").strip()
    upstream_main_id = str(session_state.get("last_card_main_id") or "").strip()
    next_index = int(session_state.get("next_position_index") or 0)
    payloads: list[dict[str, Any]] = []

    for offset, point in enumerate(points):
        position_index = next_index + offset
        position = position_for(position_index)
        assigned_graph = graph_assignments[offset] if offset < len(graph_assignments) else (graph_assignments[-1] if graph_assignments else "未归属项目")
        assigned_graph = assigned_graph or "未归属项目"
        point_payload = dict(base_payload)
        point_payload["raw_memory_id"] = f"{base_raw_memory_id}-p{offset + 1:02d}"
        point_payload["title"] = f"{thread_name} 残影记忆 {position_index + 1:02d}: {point}"[:160]
        point_payload["fact_summary"] = point[:280]
        point_payload["meaning_summary"] = (
            f"这是自动残影切片中的第 {offset + 1}/{len(points)} 个记忆点，"
            "保留当时的判断落点，供后续沿链回忆。"
        )[:280]
        excerpt_block = f"\n\n原文核对节选：\n{raw_excerpt}" if raw_excerpt else ""
        point_payload["body_text"] = (
            f"过程稿：\n{point}\n\n"
            "这是一条从同一轮现场对话里切出来的残影记忆点，保留的是当时真正被确认下来的判断落点。"
            f"{excerpt_block}"
        )[:8000]
        point_payload["raw_text"] = raw_excerpt or str(base_payload.get("raw_text") or "")

        domain_facets = _json_clone(base_payload.get("domain_facets") or {})
        enterprise = dict(domain_facets.get("enterprise") or {})
        enterprise["项目"] = [assigned_graph]
        enterprise["project"] = assigned_graph
        domain_facets["enterprise"] = enterprise
        domain_facets["memory_graphs"] = {
            "selected": [assigned_graph],
            "unique": [assigned_graph],
        }
        codex_session = dict(domain_facets.get("codex_session") or {})
        codex_session["memory_point_index"] = offset + 1
        codex_session["memory_point_total"] = len(points)
        domain_facets["codex_session"] = codex_session
        point_payload["domain_facets"] = domain_facets

        topology_role = "origin" if not upstream_main_id else "node"
        relation_type = "originates" if not upstream_main_id else "continues"
        point_payload["upstream_main_ids"] = [upstream_main_id] if upstream_main_id else []
        point_payload["downstream_main_ids"] = []
        point_payload["topology_role"] = topology_role
        point_payload["relation_type"] = relation_type
        point_payload["focus_anchor_main_id"] = upstream_main_id
        point_payload["focus_confidence"] = 0.78 if upstream_main_id else 0.0
        point_payload["position"] = position
        point_payload["subgraph"] = str(base_payload.get("subgraph") or "RET")
        point_payload["main_id"] = build_default_main_id(
            point_payload["raw_memory_id"],
            first_timestamp,
            subgraph=point_payload["subgraph"],
            position=position,
            topology_role=topology_role,
            path_status=str(point_payload.get("path_status") or "active"),
            is_landmark=bool(point_payload.get("is_landmark")),
        )
        payloads.append(point_payload)
        upstream_main_id = point_payload["main_id"]

    return payloads


def queue_pending_draft(
    *,
    state: dict[str, Any],
    snapshot: SessionSnapshot,
    session_state: dict[str, Any],
    buffer: list[dict[str, str]],
    trigger_reason: str,
    mode: str,
) -> dict[str, Any]:
    pending = state.setdefault("pending_drafts", {})
    existing = pending.get(snapshot.session_id)
    if isinstance(existing, dict):
        incoming = build_pending_draft(
            snapshot=snapshot,
            session_state=session_state,
            buffer=buffer,
            trigger_reason=trigger_reason,
            mode=mode,
        )
        existing_preview = dict(existing.get("preview") or {})
        incoming_preview = dict(incoming.get("preview") or {})

        existing_points = [str(item).strip() for item in existing_preview.get("memory_points") or [] if str(item).strip()]
        incoming_points = [str(item).strip() for item in incoming_preview.get("memory_points") or [] if str(item).strip()]
        combined_points = existing_points + incoming_points
        if combined_points:
            existing_preview["memory_points"] = combined_points

        existing_graphs = [str(item).strip() for item in existing_preview.get("graph_assignments") or [] if str(item).strip()]
        incoming_graphs = [str(item).strip() for item in incoming_preview.get("graph_assignments") or [] if str(item).strip()]
        combined_graphs = existing_graphs + incoming_graphs
        if combined_points:
            fallback_graph = str(snapshot.thread_name or "未归属项目").strip() or "未归属项目"
            while len(combined_graphs) < len(combined_points):
                combined_graphs.append(fallback_graph)
            existing_preview["graph_assignments"] = combined_graphs[: len(combined_points)]

        existing_raw = str(existing_preview.get("raw_excerpt") or "").strip()
        incoming_raw = str(incoming_preview.get("raw_excerpt") or "").strip()
        if incoming_raw:
            if existing_raw and incoming_raw not in existing_raw:
                existing_preview["raw_excerpt"] = f"{existing_raw}\n\n{incoming_raw}".strip()
            elif not existing_raw:
                existing_preview["raw_excerpt"] = incoming_raw

        existing = dict(existing)
        existing["preview"] = existing_preview
        existing["message_count"] = int(existing.get("message_count") or 0) + len(buffer)
        existing["last_message_at"] = incoming.get("last_message_at") or existing.get("last_message_at")
        existing["updated_at"] = CatalogCard.now_iso()
        latest_reason = str(trigger_reason or "").strip()
        prior_reason = str(existing.get("trigger_reason") or "").strip()
        if latest_reason and latest_reason not in prior_reason:
            existing["trigger_reason"] = f"{prior_reason}；刷新：{latest_reason}".strip("；")
        pending[snapshot.session_id] = existing
        session_state["buffer"] = []
        session_state["pending_draft_id"] = existing.get("draft_id")
        session_state["pending_created_at"] = existing.get("created_at")
        return existing
    draft = build_pending_draft(
        snapshot=snapshot,
        session_state=session_state,
        buffer=buffer,
        trigger_reason=trigger_reason,
        mode=mode,
    )
    pending[snapshot.session_id] = draft
    session_state["buffer"] = []
    session_state["pending_draft_id"] = draft["draft_id"]
    session_state["pending_created_at"] = draft["created_at"]
    return draft


def write_session_card(
    *,
    snapshot: SessionSnapshot,
    session_state: dict[str, Any],
    buffer: list[dict[str, str]],
    trigger_reason: str,
    mode: str,
) -> dict[str, Any]:
    draft = build_pending_draft(
        snapshot=snapshot,
        session_state=session_state,
        buffer=buffer,
        trigger_reason=trigger_reason,
        mode=mode,
    )
    return _write_draft_cards(draft, session_state)


def _write_prebuilt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    init_db(settings.db_path)
    card = create_direct_card(
        settings.db_path,
        payload,
        author_role="witness_model",
        author="codex-session-watcher",
    )
    return {
        "raw_memory_id": card.raw_memory_id,
        "main_id": card.main_id,
        "title": card.title,
        "trigger_reason": str(payload.get("focus_reason") or ""),
    }


def _write_draft_cards(draft: dict[str, Any], session_state: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    init_db(settings.db_path)
    payloads = _build_point_payloads_from_draft(draft, session_state)
    items: list[dict[str, Any]] = []
    for payload in payloads:
        items.append(_write_prebuilt_payload(payload))
    if items:
        session_state["last_card_main_id"] = items[-1]["main_id"]
    session_state["next_position_index"] = int(session_state.get("next_position_index") or 0) + len(items)
    session_state["last_write_at"] = CatalogCard.now_iso()
    session_state["buffer"] = []
    return {
        "session_id": str(draft.get("session_id") or ""),
        "count": len(items),
        "items": items,
        "trigger_reason": str(draft.get("trigger_reason") or ""),
    }


def public_pending_draft(draft: dict[str, Any]) -> dict[str, Any]:
    preview = draft.get("preview", {}) if isinstance(draft.get("preview"), dict) else {}
    payload = draft.get("payload", {}) if isinstance(draft.get("payload"), dict) else {}
    return {
        "draft_id": draft.get("draft_id"),
        "session_id": draft.get("session_id"),
        "thread_name": draft.get("thread_name"),
        "created_at": draft.get("created_at"),
        "updated_at": draft.get("updated_at"),
        "mode": draft.get("mode"),
        "trigger_reason": draft.get("trigger_reason"),
        "fingerprint": draft.get("fingerprint"),
        "message_count": draft.get("message_count", 0),
        "first_message_at": draft.get("first_message_at"),
        "last_message_at": draft.get("last_message_at"),
        "preview": preview,
        "payload_meta": {
            "raw_memory_id": payload.get("raw_memory_id"),
            "main_id": payload.get("main_id"),
            "source_type": payload.get("source_type"),
            "focus_anchor_main_id": payload.get("focus_anchor_main_id"),
        },
    }


def apply_draft_edits(draft: dict[str, Any], edits: dict[str, Any] | None = None) -> dict[str, Any]:
    if not edits:
        return draft
    preview = dict(draft.get("preview") or {})
    payload = dict(draft.get("payload") or {})

    if "memory_points" in edits:
        points = [str(item).strip() for item in edits.get("memory_points") or [] if str(item).strip()]
        if points:
            preview["memory_points"] = points
            payload["body_text"] = "记忆点清单：\n" + "\n".join(f"{idx}. {point}" for idx, point in enumerate(points, start=1))
            payload["fact_summary"] = "本次残影准备记住这些要点：" + "；".join(points[:4])[:280]

    current_points = preview.get("memory_points")
    point_count = len(current_points) if isinstance(current_points, list) and current_points else 0
    if "graph_assignments" in edits:
        assignments = [str(item).strip() for item in edits.get("graph_assignments") or []]
        assignments = [item for item in assignments if item]
        if assignments:
            if point_count and len(assignments) < point_count:
                assignments.extend([assignments[-1]] * (point_count - len(assignments)))
            if point_count:
                assignments = assignments[:point_count]
            preview["graph_assignments"] = assignments
            unique_graphs: list[str] = []
            for item in assignments:
                if item not in unique_graphs:
                    unique_graphs.append(item)
            domain_facets = dict(payload.get("domain_facets") or {})
            enterprise = dict(domain_facets.get("enterprise") or {})
            if unique_graphs:
                enterprise["项目"] = unique_graphs
                enterprise["project"] = unique_graphs[0]
            domain_facets["enterprise"] = enterprise
            domain_facets["memory_graphs"] = {
                "selected": assignments,
                "unique": unique_graphs,
            }
            payload["domain_facets"] = domain_facets

    if "raw_excerpt" in edits:
        raw_excerpt = str(edits.get("raw_excerpt") or "").strip()
        if raw_excerpt:
            preview["raw_excerpt"] = raw_excerpt
            body_text = str(payload.get("body_text") or "").strip()
            prefix = body_text or "记忆点清单：\n（待补充）"
            payload["body_text"] = f"{prefix}\n\n原文核对节选：\n{raw_excerpt}"

    draft = dict(draft)
    draft["preview"] = preview
    draft["payload"] = payload
    return draft


def list_pending_drafts(host_id: str | None = None) -> list[dict[str, Any]]:
    state = load_state(host_id)
    drafts = []
    for draft in state.get("pending_drafts", {}).values():
        if isinstance(draft, dict):
            drafts.append(public_pending_draft(draft))
    drafts.sort(
        key=lambda item: max(
            parse_iso_to_timestamp(str(item.get("updated_at") or "")),
            parse_iso_to_timestamp(str(item.get("last_message_at") or "")),
            parse_iso_to_timestamp(str(item.get("created_at") or "")),
        ),
        reverse=True,
    )
    return drafts


def confirm_pending_draft(session_id: str, edits: dict[str, Any] | None = None, host_id: str | None = None) -> dict[str, Any]:
    state = load_state(host_id)
    pending = state.setdefault("pending_drafts", {})
    draft = pending.get(session_id)
    if not isinstance(draft, dict):
        raise KeyError(f"pending draft not found: {session_id}")
    draft = apply_draft_edits(draft, edits)
    sessions = state.setdefault("sessions", {})
    session_state = sessions.setdefault(session_id, {})
    result = _write_draft_cards(draft, session_state)
    session_state.pop("pending_draft_id", None)
    session_state.pop("pending_created_at", None)
    pending.pop(session_id, None)
    save_state(state, host_id)
    return result


def reject_pending_draft(session_id: str, host_id: str | None = None) -> dict[str, Any]:
    state = load_state(host_id)
    pending = state.setdefault("pending_drafts", {})
    draft = pending.get(session_id)
    if not isinstance(draft, dict):
        raise KeyError(f"pending draft not found: {session_id}")
    sessions = state.setdefault("sessions", {})
    session_state = sessions.setdefault(session_id, {})
    session_state["last_rejected_at"] = CatalogCard.now_iso()
    session_state.pop("pending_draft_id", None)
    session_state.pop("pending_created_at", None)
    pending.pop(session_id, None)
    save_state(state, host_id)
    return {
        "session_id": session_id,
        "rejected_draft_id": draft.get("draft_id"),
        "rejected_at": session_state["last_rejected_at"],
    }


def ensure_session_state(state: dict[str, Any], snapshot: SessionSnapshot, initialize_at_eof: bool) -> dict[str, Any]:
    sessions = state.setdefault("sessions", {})
    item = sessions.setdefault(snapshot.session_id, {})
    item["thread_name"] = snapshot.thread_name
    item["path"] = str(snapshot.path)
    item.setdefault("buffer", [])
    item.setdefault("last_card_main_id", "")
    item.setdefault("next_position_index", 0)
    if "offset" not in item:
        item["offset"] = snapshot.path.stat().st_size if initialize_at_eof else 0
        item["initialized_at"] = CatalogCard.now_iso()
    return item


def tick(
    *,
    initialize_at_eof: bool = True,
    session_limit: int = 4,
    turn_threshold: int | None = None,
    char_threshold: int | None = None,
    hours_threshold: float | None = None,
    dry_run: bool = False,
) -> TickResult:
    gate = read_session_gate()
    mode = gate["mode"]
    result = TickResult()
    state = load_state()
    turn_threshold = turn_threshold or int(os.getenv("MEMLINK_SHRINE_AUTO_TURN_THRESHOLD", "8"))
    char_threshold = char_threshold or int(os.getenv("MEMLINK_SHRINE_AUTO_CHAR_THRESHOLD", "12000"))
    hours_threshold = hours_threshold or float(os.getenv("MEMLINK_SHRINE_AUTO_HOURS_THRESHOLD", "0.5"))
    max_backlog_bytes = int(os.getenv("MEMLINK_SHRINE_MAX_SESSION_BACKLOG_BYTES", str(1024 * 1024)))

    for snapshot in discover_sessions(limit=session_limit):
        result.checked_sessions += 1
        session_state = ensure_session_state(state, snapshot, initialize_at_eof=initialize_at_eof)

        if mode == "off":
            session_state["offset"] = snapshot.path.stat().st_size
            session_state["buffer"] = []
            result.skipped.append(f"{snapshot.thread_name}: 熄火，暂停写入")
            continue

        file_size = snapshot.path.stat().st_size
        offset = int(session_state.get("offset") or 0)
        if max_backlog_bytes > 0 and file_size - offset > max_backlog_bytes:
            session_state["offset"] = file_size
            session_state["buffer"] = []
            result.skipped.append(f"{snapshot.thread_name}: 会话积压过大，已追平到当前末尾；等待下一次真实推进")
            continue

        events, new_offset = read_new_jsonl(snapshot.path, int(session_state.get("offset") or 0))
        new_messages = extract_messages(events)
        result.new_messages += len(new_messages)
        if new_messages:
            buffer = trim_buffer(list(session_state.get("buffer") or []) + message_dicts(new_messages))
            buffer, segment_reset_note = maybe_reset_segment(
                session_state,
                buffer,
                new_messages,
                gap_hours=float(os.getenv("MEMLINK_SHRINE_SEGMENT_GAP_HOURS", "24")),
            )
            session_state["buffer"] = buffer
        else:
            buffer = list(session_state.get("buffer") or [])
            segment_reset_note = None

        session_state["offset"] = new_offset
        decision = decide_trigger(
            mode=mode,
            buffer=buffer,
            new_messages=new_messages,
            turn_threshold=turn_threshold,
            char_threshold=char_threshold,
            hours_threshold=hours_threshold,
        )
        if not decision.should_write:
            result.skipped.append(f"{snapshot.thread_name}: {decision.reason}")
            continue
        final_decision = refresh_trigger_before_write(
            previous_decision=decision,
            buffer=buffer,
            new_messages=new_messages,
            turn_threshold=turn_threshold,
            char_threshold=char_threshold,
            hours_threshold=hours_threshold,
        )
        if not final_decision.should_write:
            result.skipped.append(f"{snapshot.thread_name}: {final_decision.reason}")
            continue
        if segment_reset_note:
            final_decision.reason = f"{final_decision.reason}；{segment_reset_note}"
        should_confirm = final_decision.mode == "passive"
        if should_confirm:
            draft = queue_pending_draft(
                state=state,
                snapshot=snapshot,
                session_state=session_state,
                buffer=buffer,
                trigger_reason=final_decision.reason,
                mode=final_decision.mode,
            )
            result.pending_drafts.append(public_pending_draft(draft))
            result.skipped.append(f"{snapshot.thread_name}: 已生成待确认残影草稿。")
            continue
        if dry_run:
            payload = build_card_payload(
                snapshot=snapshot,
                buffer=buffer,
                session_state=session_state,
                trigger_reason=final_decision.reason,
                mode=final_decision.mode,
            )
            result.written_cards.append({"dry_run": True, "payload": payload})
            continue
        result.written_cards.append(
            write_session_card(
                snapshot=snapshot,
                session_state=session_state,
                buffer=buffer,
                trigger_reason=final_decision.reason,
                mode=final_decision.mode,
            )
        )

    save_state(state)
    return result


def preview_tail(
    *,
    tail_lines: int = 240,
    session_limit: int = 1,
    write: bool = False,
) -> dict[str, Any]:
    snapshots = discover_sessions(limit=session_limit)
    if not snapshots:
        return {"error": "没有找到 Codex session。"}
    snapshot = snapshots[0]
    events = read_tail_events(snapshot.path, tail_lines=tail_lines)
    messages = extract_messages(events)
    if not messages:
        return {"error": "尾部没有可用的用户/助手消息。", "session": snapshot.session_id}
    state = load_state()
    session_state = ensure_session_state(state, snapshot, initialize_at_eof=True)
    buffer = trim_buffer(message_dicts(messages), max_messages=80)
    if write:
        card = write_session_card(
            snapshot=snapshot,
            session_state=session_state,
            buffer=buffer,
            trigger_reason=f"手动尾部预览写入：最近 {tail_lines} 行。",
            mode="manual",
        )
        save_state(state)
        return {"written": card, "messages": len(buffer)}
    payload = build_card_payload(
        snapshot=snapshot,
        buffer=buffer,
        session_state=session_state,
        trigger_reason=f"手动尾部预览：最近 {tail_lines} 行。",
        mode="manual",
    )
    return {"session": snapshot.__dict__ | {"path": str(snapshot.path)}, "messages": len(buffer), "payload": payload}


def watch(interval_seconds: float = 8.0, session_limit: int = 4) -> None:
    print("Memlink Shrine session auto writer started.")
    print("Memlink Shrine modes: off=熄火, passive=被动写入, auto=自动写入")
    while True:
        try:
            result = tick(session_limit=session_limit)
            if result.written_cards:
                print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - long-running watcher should survive transient errors.
            print(f"session auto writer error: {exc}")
        time.sleep(interval_seconds)


