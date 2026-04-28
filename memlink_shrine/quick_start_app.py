from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import END, BOTH, LEFT, RIGHT, X, Button, Frame, Label, StringVar, Text, Tk, messagebox

import uvicorn

from .models import CatalogCard
from .runtime_paths import runtime_data_root, runtime_root


APP_TITLE = "Memlink Shrine Quick Start"
QUICK_START_PORT = 7862
API_BASE = f"http://127.0.0.1:{QUICK_START_PORT}"
HEALTH_URL = f"{API_BASE}/health"
DATA_DIR = runtime_data_root()
DEMO_DB_PATH = DATA_DIR / "memlink_shrine_quick_start.db"
RUNTIME_STATE_PATH = DATA_DIR / "memlink_shrine_quick_start_runtime.json"
DEBUG_LOG_PATH = DATA_DIR / "quick_start_debug.log"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _debug_log(message: str) -> None:
    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except OSError:
        return


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return 200 <= response.status < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _terminate_pid(pid: int) -> None:
    if pid <= 0:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except Exception:
        return


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _request_json(method: str, path: str, payload: dict | None = None, headers: dict[str, str] | None = None) -> dict | list:
    data = None
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=request_headers, method=method)
    with urllib.request.urlopen(req, timeout=8) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def _quick_start_artifacts() -> list[Path]:
    return [
        DEMO_DB_PATH,
        DATA_DIR / "session_memory_gate.quick-start.json",
        DATA_DIR / "agent_model_report.quick-start.json",
        DATA_DIR / "session_auto_writer_state.quick-start.json",
        DATA_DIR / "memlink_shrine_overlay_position.quick-start.json",
        DATA_DIR / "memlink_shrine_codex_lifecycle_state.json",
    ]


def _split_memory_blocks(text: str) -> list[str]:
    clean = text.strip()
    if not clean:
        return []
    blocks = re.split(r"(?m)^\s*---+\s*$", clean)
    return [block.strip() for block in blocks if block.strip()]


def _title_from_text(text: str, index: int) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    seed = first_line[:36] if first_line else f"记忆 {index:02d}"
    return f"Quick Start 直写 {index:02d}: {seed}"


def _fact_summary(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized[:180]


def _meaning_summary(index: int, total: int) -> str:
    if total <= 1:
        return "这是一条通过 Quick Start 独立程序手动直写进 Memlink Shrine 的演示记忆，用来展示写入后如何在 Web UI 中立刻出现。"
    return f"这是 Quick Start 一次多段直写中的第 {index}/{total} 段，用来展示多段记忆如何顺次写入并在 Web UI 中形成链路。"


def _build_payload(text: str, index: int, total: int, upstream_main_id: str = "") -> dict:
    relation_type = "originates" if not upstream_main_id else "continues"
    topology_role = "origin" if not upstream_main_id else "node"
    now_iso = CatalogCard.now_iso()
    return {
        "title": _title_from_text(text, index),
        "fact_summary": _fact_summary(text),
        "meaning_summary": _meaning_summary(index, total),
        "posture_summary": "通过 Quick Start 独立程序手动写入，用于演示 Memlink Shrine 的直写入口与卡片展示逻辑。",
        "emotion_trajectory": "演示写入，情绪字段默认留空，由现场输入决定是否补充。",
        "body_text": text.strip(),
        "raw_text": text.strip(),
        "base_facets": {
            "entity": ["Memlink Shrine"],
            "topic": ["Quick Start", "直写演示"],
            "time": [now_iso[:10]],
            "status": ["demo"],
            "memory_type": "demo",
            "memory_subtype": "quick_start_direct",
            "relevance_scope_core": ["写入机制", "Web UI"],
            "relevance_scope_extra": ["演示层"],
        },
        "domain_facets": {
            "enterprise": {
                "项目": ["Quick Start 演示"],
                "project": "Quick Start 演示",
                "process_stage": "本地独立演示",
            }
        },
        "governance": {
            "shelf_state": "half_open",
            "importance": "normal",
            "pinned": False,
            "confidence": 0.86,
            "promotion_rule_text": "",
            "degradation_rule_text": "",
            "rationale": "Quick Start 独立演示写入",
        },
        "upstream_main_ids": [upstream_main_id] if upstream_main_id else [],
        "relation_type": relation_type,
        "topology_role": topology_role,
        "path_status": "active",
        "focus_anchor_main_id": upstream_main_id,
        "focus_confidence": 0.75 if upstream_main_id else 0.0,
        "focus_reason": "Quick Start 多段写入演示" if upstream_main_id else "Quick Start 首段直写演示",
        "source_type": "quick_start_direct",
        "confidence_source": "human",
        "projection_created_at": now_iso,
        "raw_memory_created_at": now_iso,
    }


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env["MEMLINK_SHRINE_RUNTIME_ROOT"] = str(runtime_root())
    env["MEMLINK_SHRINE_DB"] = str(DEMO_DB_PATH)
    env["MEMLINK_SHRINE_RECALL_DELEGATE"] = "local_catalog"
    env["MEMLINK_SHRINE_WRITE_ADAPTERS"] = ""
    env["MEMLINK_SHRINE_MEMORY_ENGINE"] = "Quick Start 本地直写演示层"
    env["MEMLINK_SHRINE_MEMORY_ENGINES"] = "Quick Start 本地直写演示层"
    env["MEMLINK_SHRINE_ENGINE_EMBEDDING_MODEL"] = "未接入"
    env["MEMLINK_SHRINE_ENGINE_EMBEDDING_MODELS"] = "未接入"
    env["MEMLINK_SHRINE_WITNESS_MODEL"] = "Quick Start 手动知情写入"
    env["MEMLINK_SHRINE_WITNESS_MODELS"] = "Quick Start 手动知情写入"
    env["MEMLINK_SHRINE_GEMINI_MODEL"] = "Quick Start 本地治理视图"
    env["MEMLINK_SHRINE_ADMIN_MODELS"] = "Quick Start 本地治理视图"
    env["MEMLINK_SHRINE_HOST_ID"] = "quick-start"
    env["MEMLINK_SHRINE_STANDALONE"] = "1"
    env["MEMLINK_SHRINE_DISABLE_AUTO_RECOVERY"] = "1"
    env["MEMLINK_SHRINE_API_BASE"] = API_BASE
    env["MEMLINK_SHRINE_QUICK_START_DEBUG_LOG"] = str(DEBUG_LOG_PATH)
    return env


def _self_command(role: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--quick-start-role", role]
    return [sys.executable, "-m", "memlink_shrine.quick_start_app", "--quick-start-role", role]


@dataclass
class QuickStartRuntime:
    web_process: subprocess.Popen | None = None
    overlay_process: subprocess.Popen | None = None

    def stop_previous_runtime(self) -> None:
        state = _read_json(RUNTIME_STATE_PATH)
        for key in ("web_pid", "overlay_pid"):
            try:
                pid = int(state.get(key) or 0)
            except (TypeError, ValueError):
                pid = 0
            _terminate_pid(pid)
        if RUNTIME_STATE_PATH.exists():
            try:
                RUNTIME_STATE_PATH.unlink()
            except OSError:
                pass

    def clear_demo_state(self) -> None:
        for path in _quick_start_artifacts():
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                continue

    def _start_role(self, role: str, *, windowless: bool) -> subprocess.Popen:
        command = _self_command(role)
        _debug_log(f"spawn role={role} command={command}")
        return subprocess.Popen(
            command,
            cwd=str(runtime_root()),
            env=_base_env(),
            creationflags=CREATE_NO_WINDOW if windowless else 0,
        )

    def wait_for_health(self, timeout_seconds: float = 15.0) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if _http_ok(HEALTH_URL):
                return True
            time.sleep(0.5)
        return False

    def start(self) -> None:
        _debug_log("runtime.start begin")
        self.stop_previous_runtime()
        self.clear_demo_state()
        self.web_process = self._start_role("web", windowless=True)
        if not self.wait_for_health():
            _debug_log("runtime.start web health timeout")
            self.stop()
            raise RuntimeError("Quick Start Web UI did not become healthy on port 7862.")
        self.overlay_process = self._start_role("overlay", windowless=True)
        _write_json(
            RUNTIME_STATE_PATH,
            {
                "web_pid": int(self.web_process.pid if self.web_process else 0),
                "overlay_pid": int(self.overlay_process.pid if self.overlay_process else 0),
                "port": QUICK_START_PORT,
                "db_path": str(DEMO_DB_PATH),
                "started_at": CatalogCard.now_iso(),
            },
        )
        _debug_log(
            f"runtime.start success web_pid={int(self.web_process.pid if self.web_process else 0)} overlay_pid={int(self.overlay_process.pid if self.overlay_process else 0)}"
        )

    def stop(self) -> None:
        for process in (self.overlay_process, self.web_process):
            if process and process.poll() is None:
                _terminate_pid(int(process.pid))
        self.overlay_process = None
        self.web_process = None
        if RUNTIME_STATE_PATH.exists():
            try:
                RUNTIME_STATE_PATH.unlink()
            except OSError:
                pass

    def open_browser(self) -> None:
        webbrowser.open(API_BASE)

    def write_memory_blocks(self, text: str) -> list[dict]:
        blocks = _split_memory_blocks(text)
        if not blocks:
            return []
        results: list[dict] = []
        upstream_main_id = ""
        total = len(blocks)
        for index, block in enumerate(blocks, start=1):
            payload = _build_payload(block, index=index, total=total, upstream_main_id=upstream_main_id)
            result = _request_json(
                "POST",
                "/api/cards",
                payload=payload,
                headers={
                    "X-Memory-Author-Role": "human",
                    "X-Memory-Author": "quick-start",
                },
            )
            if not isinstance(result, dict):
                raise RuntimeError("Quick Start write did not return a card payload.")
            results.append(result)
            upstream_main_id = str(result.get("main_id") or "")
        return results

    def card_count(self) -> int:
        cards = _request_json("GET", "/api/cards?limit=200")
        if isinstance(cards, list):
            return len(cards)
        return 0


class QuickStartWindow:
    def __init__(self) -> None:
        self.runtime = QuickStartRuntime()
        self.root = Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("640x560")
        self.root.configure(bg="#14100d")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.status_var = StringVar(value="启动中…")
        self.count_var = StringVar(value="当前卡片数：0")
        self._build_ui()

        self.runtime.start()
        self.runtime.open_browser()
        self.refresh_count()
        self.status_var.set("Quick Start 已启动：控火台与 Web UI 已拉起，当前是空库。")

    def _build_ui(self) -> None:
        shell = Frame(self.root, bg="#14100d")
        shell.pack(fill=BOTH, expand=True, padx=16, pady=16)

        Label(shell, text="Memlink Shrine Quick Start", fg="#e6c690", bg="#14100d", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
        Label(
            shell,
            text="独立演示层：默认空库，不依赖 Codex / CC / VCP。输入一段记忆直接写入；多段请用单独一行 --- 分隔。",
            fg="#b89a73",
            bg="#14100d",
            justify="left",
            wraplength=590,
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(8, 12))

        status_row = Frame(shell, bg="#14100d")
        status_row.pack(fill=X)
        Label(status_row, textvariable=self.status_var, fg="#f0dfc4", bg="#14100d", font=("Microsoft YaHei UI", 10)).pack(side=LEFT)
        Label(status_row, textvariable=self.count_var, fg="#c2a47d", bg="#14100d", font=("Microsoft YaHei UI", 10, "bold")).pack(side=RIGHT)

        self.editor = Text(
            shell,
            bg="#201915",
            fg="#f0dfc4",
            insertbackground="#f0dfc4",
            relief="flat",
            bd=0,
            font=("Microsoft YaHei UI", 11),
            wrap="word",
            padx=12,
            pady=12,
            height=18,
        )
        self.editor.pack(fill=BOTH, expand=True, pady=(14, 12))

        button_row = Frame(shell, bg="#14100d")
        button_row.pack(fill=X)
        Button(button_row, text="写入当前内容", command=self.write_current, bg="#8a5c2c", fg="white", relief="flat", padx=14, pady=8).pack(side=LEFT)
        Button(button_row, text="打开 Web UI", command=self.runtime.open_browser, bg="#3a3027", fg="#f0dfc4", relief="flat", padx=14, pady=8).pack(side=LEFT, padx=(10, 0))
        Button(button_row, text="刷新卡片数", command=self.refresh_count, bg="#3a3027", fg="#f0dfc4", relief="flat", padx=14, pady=8).pack(side=LEFT, padx=(10, 0))

        self.log = Text(
            shell,
            bg="#18120f",
            fg="#cbb18a",
            relief="flat",
            bd=0,
            font=("Consolas", 10),
            wrap="word",
            padx=10,
            pady=10,
            height=8,
        )
        self.log.pack(fill=BOTH, expand=False, pady=(12, 0))
        self.log.insert("1.0", "写入记录会显示在这里。\n")
        self.log.configure(state="disabled")

    def append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert(END, text.rstrip() + "\n")
        self.log.see(END)
        self.log.configure(state="disabled")

    def refresh_count(self) -> None:
        try:
            count = self.runtime.card_count()
        except Exception as exc:  # noqa: BLE001
            self.count_var.set("当前卡片数：读取失败")
            self.status_var.set(f"读取卡片数失败：{exc}")
            return
        self.count_var.set(f"当前卡片数：{count}")

    def write_current(self) -> None:
        raw = self.editor.get("1.0", END).strip()
        if not raw:
            messagebox.showwarning(APP_TITLE, "先输入要写入的记忆内容。")
            return
        try:
            results = self.runtime.write_memory_blocks(raw)
        except Exception as exc:  # noqa: BLE001
            self.status_var.set(f"写入失败：{exc}")
            messagebox.showerror(APP_TITLE, f"写入失败：{exc}")
            return
        if not results:
            messagebox.showwarning(APP_TITLE, "没有识别到有效记忆块。多段写入请用单独一行 --- 分隔。")
            return
        self.editor.delete("1.0", END)
        self.refresh_count()
        self.status_var.set("写入完成。刷新 Web UI 就能看到新卡。")
        for item in results:
            self.append_log(f"[OK] {item.get('main_id') or '-'} | {item.get('title') or '-'}")

    def on_close(self) -> None:
        try:
            self.runtime.stop()
        finally:
            self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def run_web() -> int:
    from .web import app

    _debug_log("run_web enter")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=QUICK_START_PORT,
        log_level="warning",
        access_log=False,
        log_config=None,
    )
    return 0


def run_overlay() -> int:
    from .shrine_overlay import main as overlay_main

    _debug_log("run_overlay enter")
    return overlay_main()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Memlink Shrine Quick Start")
    parser.add_argument(
        "--quick-start-role",
        choices=("gui", "web", "overlay"),
        default="gui",
        help="Quick Start 运行角色",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    os.environ.update(_base_env())
    args = parse_args(argv)
    _debug_log(f"main role={args.quick_start_role} frozen={getattr(sys, 'frozen', False)} executable={sys.executable}")
    try:
        if args.quick_start_role == "web":
            return run_web()
        if args.quick_start_role == "overlay":
            return run_overlay()
        app = QuickStartWindow()
        return app.run()
    except Exception as exc:  # noqa: BLE001
        _debug_log(f"fatal {type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
