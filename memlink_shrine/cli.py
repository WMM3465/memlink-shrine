from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .composition import build_service_from_settings
from .config import load_settings
from .db import init_db, list_cards, sanitize_untrusted_chains
from .demo_chain import apply_demo_witness_chain
from .direct_write import create_direct_card
from .session_auto_writer import preview_tail, tick as tick_session_auto_writer, watch as watch_session_auto_writer


def load_dotenv_file(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def build_service():
    settings = load_settings()
    if not settings.google_api_key:
        raise SystemExit("GOOGLE_API_KEY is required")
    return build_service_from_settings(settings, require_google=True)


def cmd_init_db() -> None:
    settings = load_settings()
    init_db(settings.db_path)
    print(f"Initialized catalog database at: {settings.db_path}")


def cmd_sync_openmemory(days: int) -> None:
    service = build_service()
    count = service.sync_recent_memories(days=days)
    print(f"Synchronized {count} memories into catalog cards.")


def cmd_list_cards(limit: int) -> None:
    settings = load_settings()
    cards = list_cards(settings.db_path, limit=limit)
    print(
        json.dumps(
            [card.as_dict() for card in cards],
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_sanitize_chains() -> None:
    settings = load_settings()
    init_db(settings.db_path)
    count = sanitize_untrusted_chains(settings.db_path)
    print(f"Sanitized {count} untrusted chain records.")


def cmd_seed_demo_chain() -> None:
    settings = load_settings()
    init_db(settings.db_path)
    result = apply_demo_witness_chain(settings.db_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_query_brief(question: str, routing_limit: int) -> None:
    service = build_service()
    brief = service.build_memory_brief(question=question, routing_limit=routing_limit)
    if isinstance(brief, dict):
        print(json.dumps(brief, ensure_ascii=False, indent=2))
        return
    print(json.dumps(brief.as_dict(), ensure_ascii=False, indent=2))


def cmd_write_card(input_path: str, author_role: str, author: str) -> None:
    settings = load_settings()
    init_db(settings.db_path)
    if input_path == "-":
        payload_text = sys.stdin.read()
    else:
        payload_text = Path(input_path).read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    card = create_direct_card(
        settings.db_path,
        payload,
        author_role=author_role,
        author=author,
    )
    print(json.dumps(card.as_dict(), ensure_ascii=False, indent=2))


def cmd_session_auto_tick(
    dry_run: bool,
    session_limit: int,
    process_existing: bool,
    turn_threshold: int | None,
    char_threshold: int | None,
    hours_threshold: float | None,
) -> None:
    result = tick_session_auto_writer(
        dry_run=dry_run,
        session_limit=session_limit,
        initialize_at_eof=not process_existing,
        turn_threshold=turn_threshold,
        char_threshold=char_threshold,
        hours_threshold=hours_threshold,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))


def cmd_session_tail_preview(tail_lines: int, write: bool) -> None:
    result = preview_tail(tail_lines=tail_lines, write=write)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="Memlink Shrine v1+v2 runtime")
    parser.add_argument("--env-file", default=".env", help="Optional env file path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db")

    sync_parser = subparsers.add_parser("sync-openmemory")
    sync_parser.add_argument("--days", type=int, default=7)

    list_parser = subparsers.add_parser("list-cards")
    list_parser.add_argument("--limit", type=int, default=20)

    subparsers.add_parser("sanitize-chains")
    subparsers.add_parser("seed-demo-chain")

    brief_parser = subparsers.add_parser("query-brief")
    brief_parser.add_argument("--question", required=True)
    brief_parser.add_argument("--routing-limit", type=int, default=120)

    write_parser = subparsers.add_parser(
        "write-card",
        help="从 Codex/Claude 等现场知情者直接写入一张残影卡；input 用 '-' 时从 stdin 读取 JSON。",
    )
    write_parser.add_argument("--input", default="-")
    write_parser.add_argument("--author-role", default="witness_model")
    write_parser.add_argument("--author", default="codex")

    auto_tick_parser = subparsers.add_parser(
        "session-auto-tick",
        help="读取 Codex 本地 session 增量，并按 Memlink Shrine 状态门执行一次自动/被动写入判断。",
    )
    auto_tick_parser.add_argument("--dry-run", action="store_true")
    auto_tick_parser.add_argument(
        "--process-existing",
        action="store_true",
        help="测试用：第一次看到 session 时也处理已有内容；后台 watcher 默认不要打开它。",
    )
    auto_tick_parser.add_argument("--session-limit", type=int, default=4)
    auto_tick_parser.add_argument("--turn-threshold", type=int, default=None)
    auto_tick_parser.add_argument("--char-threshold", type=int, default=None)
    auto_tick_parser.add_argument("--hours-threshold", type=float, default=None)

    auto_watch_parser = subparsers.add_parser(
        "session-auto-watch",
        help="后台监听 Codex 本地 session；Memlink Shrine 熄火时不写入，被动/自动时按规则写入。",
    )
    auto_watch_parser.add_argument("--interval", type=float, default=8.0)
    auto_watch_parser.add_argument("--session-limit", type=int, default=4)

    tail_parser = subparsers.add_parser(
        "session-tail-preview",
        help="预览最近一段 Codex session 会如何被压成残影卡；默认不写库。",
    )
    tail_parser.add_argument("--tail-lines", type=int, default=240)
    tail_parser.add_argument("--write", action="store_true")

    args = parser.parse_args()
    load_dotenv_file(Path(args.env_file))

    if args.command == "init-db":
        cmd_init_db()
    elif args.command == "sync-openmemory":
        cmd_sync_openmemory(days=args.days)
    elif args.command == "list-cards":
        cmd_list_cards(limit=args.limit)
    elif args.command == "sanitize-chains":
        cmd_sanitize_chains()
    elif args.command == "seed-demo-chain":
        cmd_seed_demo_chain()
    elif args.command == "query-brief":
        cmd_query_brief(question=args.question, routing_limit=args.routing_limit)
    elif args.command == "write-card":
        cmd_write_card(
            input_path=args.input,
            author_role=args.author_role,
            author=args.author,
        )
    elif args.command == "session-auto-tick":
        cmd_session_auto_tick(
            dry_run=args.dry_run,
            session_limit=args.session_limit,
            process_existing=args.process_existing,
            turn_threshold=args.turn_threshold,
            char_threshold=args.char_threshold,
            hours_threshold=args.hours_threshold,
        )
    elif args.command == "session-auto-watch":
        watch_session_auto_writer(
            interval_seconds=args.interval,
            session_limit=args.session_limit,
        )
    elif args.command == "session-tail-preview":
        cmd_session_tail_preview(tail_lines=args.tail_lines, write=args.write)


if __name__ == "__main__":
    main()



