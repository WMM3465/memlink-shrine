from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from math import hypot
from pathlib import Path
from typing import Any
from tkinter import BooleanVar, StringVar, Tk, Toplevel, Canvas, Label, Frame, Button, Checkbutton, Text, Menu, simpledialog
from tkinter import ttk
from ctypes import wintypes

try:
    from PIL import Image, ImageTk, ImageOps, ImageDraw
except Exception:  # pragma: no cover - Pillow is optional at runtime.
    Image = None
    ImageTk = None
    ImageOps = None
    ImageDraw = None


API_BASE = os.getenv("MEMLINK_SHRINE_API_BASE", "http://127.0.0.1:7861").rstrip("/")
ROOT_DIR = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT_DIR / "assets"
FALLBACK_ICON_DIR = ROOT_DIR.parents[3] / "图标"


def _asset_path(primary_name: str, fallback_name: str | None = None) -> Path | None:
    primary = ICON_DIR / primary_name
    if primary.exists():
        return primary
    if fallback_name:
        secondary = FALLBACK_ICON_DIR / fallback_name
        if secondary.exists():
            return secondary
    return primary if primary.exists() else None


LIT_ICON_PATH = _asset_path("memlink_shrine_lit.png", "g1.png")
UNLIT_ICON_PATH = _asset_path("memlink_shrine_unlit.png", "g2.png")
UI_SKIN_PATH = _asset_path("memlink_shrine_ui_skin.jpg", "g3.jpg")
PANEL_BG_PATH = _asset_path("memlink_shrine_panel_bg.png", "g4.png")
DROPDOWN_ARROW_PATH = _asset_path("memlink_shrine_dropdown_arrow.png", "g7.png")
UI_BASE_WIDTH = 1688
UI_BASE_HEIGHT = 2528
PANEL_STONE_PATCH_CROP = (930, 330, 1230, 1180)
MODE_BUTTON_CROP = (70, 350, 294, 468)
MODE_BUTTON_ACTIVE_CROP = (590, 340, 910, 478)
DRAFT_BUTTON_CROP = (54, 616, 312, 736)
PARCHMENT_BAR_CROP = (352, 640, 1302, 742)
COMBO_SLOT_CROP = (58, 995, 1497, 1132)
REFRESH_BUTTON_CROP = (1184, 2340, 1596, 2464)
MODE_OFF_RECT = (70, 350, 294, 468)
MODE_AUTO_RECT = (319, 350, 566, 468)
MODE_PASSIVE_RECT = (591, 340, 910, 478)
CHECKBOX_RECT = (68, 503, 117, 550)
DRAFT_BUTTON_RECT = (54, 616, 312, 736)
COUNT_BAR_RECT = (322, 620, 1322, 738)
WITNESS_COMBO_RECT = (60, 997, 1496, 1128)
ADMIN_COMBO_RECT = (60, 1467, 1496, 1598)
VCP_COMBO_RECT = (60, 1938, 1496, 2069)
REFRESH_BUTTON_RECT = (1184, 2338, 1596, 2464)
STATUS_TEXT_POINT = (66, 240)
TITLE_TEXT_POINT = (70, 150)
HEADER_DIVIDER_LINE = (62, 275, 1188, 275)
TOP_PANEL_COVER_RECT = (42, 110, 1245, 900)
WITNESS_SECTION_COVER_RECT = (42, 760, 1560, 1380)
ADMIN_SECTION_COVER_RECT = (42, 1230, 1560, 1860)
VCP_SECTION_COVER_RECT = (42, 1700, 1560, 2478)
TRANSPARENT = "#ff00ff"
THEME_BG = "#15120f"
THEME_PANEL = "#1c1815"
THEME_CARD = "#26211d"
THEME_CARD_ALT = "#211c18"
THEME_EDGE = "#5f5141"
THEME_GOLD = "#d8bc92"
THEME_GOLD_DIM = "#b59a74"
THEME_TEXT = "#efe1c9"
THEME_MUTED = "#b7aa97"
THEME_MUTED_2 = "#8f8374"
THEME_PARCHMENT = "#cdb890"
THEME_PARCHMENT_TEXT = "#3c2d20"
THEME_ACTIVE = "#7e5a35"
THEME_ACTIVE_TEXT = "#f7ead5"
PANEL_FONT_FAMILY = "STSong"
PANEL_DETAIL_FONT_FAMILY = "Microsoft YaHei UI"
PANEL_TEXT_GOLD = "#ceb08a"
PANEL_TEXT_GOLD_MUTED = "#b6956f"
PANEL_TEXT_GOLD_BRIGHT = "#ecd4ab"
PANEL_TEXT_BROWN = "#735739"
PANEL_TEXT_BROWN_ACTIVE = "#9b7247"
PANEL_TEXT_DARK = "#18110b"
BEIJING_TZ = timezone(timedelta(hours=8))
USER32 = ctypes.windll.user32 if os.name == "nt" else None
ENUM_WINDOWS_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM) if USER32 else None
GWLP_HWNDPARENT = -8
HWND_TOP = 0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020


def _get_window_owner(hwnd: int) -> int:
    if not USER32 or not hwnd:
        return 0
    getter = getattr(USER32, "GetWindowLongPtrW", None) or getattr(USER32, "GetWindowLongW", None)
    if getter is None:
        return 0
    try:
        return int(getter(hwnd, GWLP_HWNDPARENT) or 0)
    except Exception:
        return 0


def _set_window_owner(hwnd: int, owner_hwnd: int) -> None:
    if not USER32 or not hwnd:
        return
    setter = getattr(USER32, "SetWindowLongPtrW", None) or getattr(USER32, "SetWindowLongW", None)
    if setter is None:
        return
    target = int(owner_hwnd or 0)
    try:
        current = int(_get_window_owner(hwnd) or 0)
        if current != target:
            setter(hwnd, GWLP_HWNDPARENT, target)
        USER32.SetWindowPos(
            hwnd,
            HWND_TOP,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    except Exception:
        return

def _normalize_host_id(value: str | None) -> str:
    raw = str(value or os.getenv("MEMLINK_SHRINE_HOST_ID") or "default").strip().lower()
    clean = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in raw).strip(".-_")
    return clean or "default"


HOST_ID = _normalize_host_id(None)
HOST_WINDOW_TITLE = str(os.getenv("MEMLINK_SHRINE_HOST_WINDOW_TITLE") or "Codex").strip() or "Codex"
HOST_REGION_LEFT = int(os.getenv("MEMLINK_SHRINE_HOST_REGION_LEFT") or "304")
HOST_REGION_TOP = int(os.getenv("MEMLINK_SHRINE_HOST_REGION_TOP") or "52")
HOST_REGION_RIGHT = int(os.getenv("MEMLINK_SHRINE_HOST_REGION_RIGHT") or "20")
HOST_REGION_BOTTOM = int(os.getenv("MEMLINK_SHRINE_HOST_REGION_BOTTOM") or "18")
HOST_ICON_FOCUS_GRACE_SECONDS = float(os.getenv("MEMLINK_SHRINE_HOST_ICON_FOCUS_GRACE_SECONDS") or "0.0")
HOST_PANEL_FOCUS_GRACE_SECONDS = float(os.getenv("MEMLINK_SHRINE_HOST_PANEL_FOCUS_GRACE_SECONDS") or "0.18")
HOST_SCOPE_TICK_MS = int(os.getenv("MEMLINK_SHRINE_HOST_SCOPE_TICK_MS") or "120")
RESIZE_PREVIEW_REFRESH_MS = int(os.getenv("MEMLINK_SHRINE_RESIZE_PREVIEW_REFRESH_MS") or "90")
HOST_PRESENCE_GRACE_SECONDS = float(os.getenv("MEMLINK_SHRINE_HOST_PRESENCE_GRACE_SECONDS") or "1.2")
RECOVERY_COOLDOWN_SECONDS = float(os.getenv("MEMLINK_SHRINE_RECOVERY_COOLDOWN_SECONDS") or "12")
RECOVERY_RETRY_ON_FAILURE_SECONDS = float(os.getenv("MEMLINK_SHRINE_RECOVERY_RETRY_ON_FAILURE_SECONDS") or "6")


def _position_path() -> Path:
    return ROOT_DIR / "data" / f"memlink_shrine_overlay_position.{HOST_ID}.json"


def _legacy_position_path() -> Path:
    return ROOT_DIR / "data" / "memlink_shrine_overlay_position.json"


def _request_json(method: str, path: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json", "X-Memory-Host": HOST_ID}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=3) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
    except OSError:
        return {}
    return values


def _resolve_python_command(*, windowless: bool = False) -> str | None:
    current = Path(sys.executable).resolve()
    if current.exists():
        if windowless and current.name.lower() == "python.exe":
            sibling = current.with_name("pythonw.exe")
            if sibling.exists():
                return str(sibling)
        if not windowless and current.name.lower() == "pythonw.exe":
            sibling = current.with_name("python.exe")
            if sibling.exists():
                return str(sibling)
        return str(current)

    for candidate in (
        shutil.which("pythonw") if windowless else None,
        shutil.which("python"),
        shutil.which("py"),
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _process_running(needle: str) -> bool:
    try:
        processes = ctypes  # tiny anchor to avoid lint noise in frozen runs
        del processes
        import subprocess as _subprocess

        result = _subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Get-CimInstance Win32_Process | Where-Object {{ $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -like '*{needle}*' }} | Select-Object -First 1 | ConvertTo-Json -Compress"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return bool((result.stdout or "").strip())
    except Exception:
        return False


def _load_position() -> dict[str, Any] | None:
    for path in (_position_path(), _legacy_position_path()):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _lifecycle_state_path() -> Path:
    return ROOT_DIR / "data" / "memlink_shrine_codex_lifecycle_state.json"


def _read_lifecycle_state() -> dict[str, Any]:
    path = _lifecycle_state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_position(offset_x: int, offset_y: int, scale: float = 1.0) -> None:
    path = _position_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "host_id": HOST_ID,
                "offset_x": int(offset_x),
                "offset_y": int(offset_y),
                "scale": round(scale, 3),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _window_text(hwnd: int) -> str:
    if not USER32 or not hwnd:
        return ""
    length = USER32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    USER32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _enum_windows() -> list[tuple[int, str]]:
    if not USER32 or not ENUM_WINDOWS_PROC:
        return []
    items: list[tuple[int, str]] = []

    @ENUM_WINDOWS_PROC
    def _callback(hwnd, _lparam):
        if not USER32.IsWindowVisible(hwnd):
            return True
        title = _window_text(hwnd).strip()
        if title:
            items.append((int(hwnd), title))
        return True

    USER32.EnumWindows(_callback, 0)
    return items


def _find_host_window() -> int:
    hint = HOST_WINDOW_TITLE.lower()
    exact: list[int] = []
    contains: list[int] = []
    for hwnd, title in _enum_windows():
        lowered = title.lower()
        if lowered == hint:
            exact.append(hwnd)
        elif hint and hint in lowered:
            contains.append(hwnd)
    if exact:
        return exact[0]
    if contains:
        return contains[0]
    return 0


def _window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if not USER32 or not hwnd:
        return None
    rect = wintypes.RECT()
    if not USER32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def _window_process_id(hwnd: int) -> int:
    if not USER32 or not hwnd:
        return 0
    pid = wintypes.DWORD()
    USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value or 0)


def _window_hwnd(window) -> int:
    try:
        frame_value = window.frame()
    except Exception:
        frame_value = None
    if frame_value:
        try:
            return int(str(frame_value), 0)
        except Exception:
            try:
                return int(str(frame_value).strip(), 16)
            except Exception:
                pass
    try:
        return int(window.winfo_id())
    except Exception:
        return 0


class ToolTip:
    def __init__(self, widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip: Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event=None) -> None:
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tip = Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.attributes("-topmost", True)
        self.tip.geometry(f"+{x}+{y}")
        Label(
            self.tip,
            text=self.text,
            bg="#0b1220",
            fg="#e5efff",
            justify="left",
            wraplength=320,
            padx=10,
            pady=7,
            relief="solid",
            borderwidth=1,
            font=("Microsoft YaHei UI", 9),
        ).pack()

    def _hide(self, _event=None) -> None:
        if self.tip:
            self.tip.destroy()
            self.tip = None


class MemlinkShrineOverlay:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("Memlink Shrine")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", False)
        self.root.configure(bg=TRANSPARENT)
        try:
            self.root.wm_attributes("-transparentcolor", TRANSPARENT)
        except Exception:
            pass
        self.ttk_style = ttk.Style()
        self._init_theme_styles()

        self.state: dict = {
            "mode": "passive",
            "label": "被动写入",
            "confirm_before_write": True,
            "model_roles": {},
            "selected_models": {},
        }
        self.connected = False
        self.panel: Toplevel | None = None
        self.panel_dropdown_popup: Toplevel | None = None
        self.pending_prompt: Toplevel | None = None
        self.pending_point_editors: list[Text] = []
        self.pending_graph_vars: list[StringVar] = []
        self.pending_graph_boxes: list[ttk.Combobox] = []
        self.pending_point_cards: list[dict[str, Any]] = []
        self.pending_raw_editor: Text | None = None
        self.dragging = False
        self.resizing = False
        self.moved = False
        self.start_x = 0
        self.start_y = 0
        self.root_x = 0
        self.root_y = 0
        self.last_click_time = 0.0
        self.flame_phase = 0
        self.scale = 1.0
        self.min_scale = 1.0
        self.max_scale = 4.4
        self.start_scale = 1.0
        self.resize_center_x = 0.0
        self.resize_center_y = 0.0
        self.resize_anchor = 1.0
        self.icon_sources: dict[str, Any] = {}
        self.icon_images: dict[tuple[str, int], Any] = {}
        self.window_skin_source: Any = None
        self.panel_bg_source: Any = None
        self.dropdown_arrow_source: Any = None
        self.window_skin_images: dict[tuple[int, int], Any] = {}
        self.panel_skin_images: dict[tuple[int, int], Any] = {}
        self.panel_bg_images: dict[tuple[int, int], Any] = {}
        self.panel_field_images: dict[tuple[int, int], Any] = {}
        self.dropdown_arrow_images: dict[tuple[int, int], Any] = {}
        self.window_crop_images: dict[tuple[tuple[int, int, int, int], int, int], Any] = {}
        self.writer_status: dict[str, Any] = {}
        self.lifecycle_state: dict[str, Any] = {}
        self.last_status_refresh = 0.0
        self.last_prompted_draft_id = ""
        self.last_panel_signature = ""
        self.last_prompt_signature = ""
        self.snoozed_draft_id = ""
        self.pending_preview_expanded = False
        self.pending_prompt_is_empty = False
        self.host_hwnd = 0
        self.host_pid = 0
        self.host_rect: tuple[int, int, int, int] | None = None
        self.host_region: tuple[int, int, int, int] | None = None
        self.relative_x: int | None = None
        self.relative_y: int | None = None
        self.host_visible = False
        self.host_focus_grace_until = 0.0
        self.host_presence_grace_until = 0.0
        self.overlay_pid = os.getpid()
        self._saved_position_state = _load_position() or {}
        self.panel_bounds: dict[str, int] | None = None
        self.prompt_bounds: dict[str, int] | None = None
        self.empty_prompt_bounds: dict[str, int] | None = None
        self.panel_refresh_job = None
        self.pending_prompt_refresh_job = None
        self.owner_sync_job = None
        self.last_recovery_attempt = 0.0
        self.last_recovery_error = ""

        self.canvas = Canvas(
            self.root,
            width=self._canvas_size()[0],
            height=self._canvas_size()[1],
            bg=TRANSPARENT,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack()
        self._load_icon_images()
        self._load_window_skin()
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", lambda _event: self._toggle_panel())
        self.canvas.bind("<Motion>", self._hover_state)
        self.canvas.bind("<Leave>", self._leave_hover)
        self.canvas.bind("<MouseWheel>", self._wheel_scale)
        ToolTip(
            self.canvas,
            "点击篝火切换写入开关；点击剑打开 Memlink Shrine 控制台。滚轮可放大缩小，最小就是当前尺寸。",
        )

        self._restore_position()
        self.root.withdraw()
        self._refresh_state()
        self._tick()

    def _init_theme_styles(self) -> None:
        try:
            self.ttk_style.theme_use("clam")
        except Exception:
            pass
        self.ttk_style.configure(
            "Memlink.TCombobox",
            fieldbackground=THEME_CARD,
            background=THEME_CARD,
            foreground=THEME_TEXT,
            arrowcolor=THEME_GOLD,
            bordercolor=THEME_EDGE,
            lightcolor=THEME_EDGE,
            darkcolor=THEME_EDGE,
            insertcolor=THEME_TEXT,
            padding=6,
        )
        self.ttk_style.map(
            "Memlink.TCombobox",
            fieldbackground=[("readonly", THEME_CARD)],
            background=[("readonly", THEME_CARD)],
            foreground=[("readonly", THEME_TEXT)],
            arrowcolor=[("readonly", THEME_GOLD)],
        )
        self.ttk_style.configure(
            "Memlink.Vertical.TScrollbar",
            background=THEME_CARD,
            troughcolor=THEME_BG,
            bordercolor=THEME_EDGE,
            arrowcolor=THEME_GOLD,
            darkcolor=THEME_EDGE,
            lightcolor=THEME_EDGE,
        )
        self.ttk_style.configure(
            "ClassicPanel.TCombobox",
            fieldbackground="#ffffff",
            background="#ffffff",
            foreground="#111827",
            arrowcolor="#111827",
            padding=4,
        )
        self.ttk_style.map(
            "ClassicPanel.TCombobox",
            fieldbackground=[("readonly", "#ffffff")],
            background=[("readonly", "#ffffff")],
            foreground=[("readonly", "#111827")],
            arrowcolor=[("readonly", "#111827")],
        )

    def _tracked_hwnds(self) -> set[int]:
        tracked = {int(self.root.winfo_id())}
        if self.panel and self.panel.winfo_exists():
            tracked.add(int(self.panel.winfo_id()))
        if self.pending_prompt and self.pending_prompt.winfo_exists():
            tracked.add(int(self.pending_prompt.winfo_id()))
        return tracked

    def _foreground_belongs_to_scope(self, host_hwnd: int) -> bool:
        if not USER32:
            return True
        foreground = int(USER32.GetForegroundWindow() or 0)
        if not foreground:
            return False
        if foreground == host_hwnd or foreground in self._tracked_hwnds():
            return True
        foreground_pid = _window_process_id(foreground)
        # Keep overlay-owned popups in scope, but do not treat every host-PID
        # dialog as part of the scope; otherwise the icon lingers over other UI.
        if foreground_pid and foreground_pid == self.overlay_pid:
            return True
        return False

    def _host_region_for_rect(self, rect: tuple[int, int, int, int] | None) -> tuple[int, int, int, int] | None:
        if not rect:
            return None
        left, top, right, bottom = rect
        region = (
            left + HOST_REGION_LEFT,
            top + HOST_REGION_TOP,
            right - HOST_REGION_RIGHT,
            bottom - HOST_REGION_BOTTOM,
        )
        if region[2] - region[0] < 180 or region[3] - region[1] < 120:
            region = (left + 8, top + 8, right - 8, bottom - 8)
        return region

    def _host_state(self) -> dict[str, Any] | None:
        hwnd = _find_host_window()
        if not hwnd or not USER32:
            return None
        if USER32.IsIconic(hwnd):
            return None
        rect = _window_rect(hwnd)
        if not rect:
            return None
        self.host_pid = _window_process_id(hwnd)
        active = self._foreground_belongs_to_scope(hwnd)
        return {
            "hwnd": hwnd,
            "rect": rect,
            "region": self._host_region_for_rect(rect),
            "active": active,
        }

    def _window_bounds(self) -> tuple[int, int, int, int]:
        region = self.host_region
        if region:
            return region
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        return 8, 8, screen_w - 8, screen_h - 8

    def _clamp_origin(self, x: float, y: float, width: int, height: int) -> tuple[int, int]:
        left, top, right, bottom = self._window_bounds()
        max_x = max(left, right - width)
        max_y = max(top, bottom - height)
        clamped_x = max(left, min(max_x, int(round(x))))
        clamped_y = max(top, min(max_y, int(round(y))))
        return clamped_x, clamped_y

    def _ensure_relative_position(self) -> None:
        if not self.host_region:
            return
        if self.relative_x is not None and self.relative_y is not None:
            return
        left, top, right, bottom = self.host_region
        width, height = self._canvas_size()
        state = self._saved_position_state
        if "offset_x" in state and "offset_y" in state:
            self.relative_x = int(state.get("offset_x") or 0)
            self.relative_y = int(state.get("offset_y") or 0)
        elif "x" in state and "y" in state:
            self.relative_x = int(state.get("x") or left) - left
            self.relative_y = int(state.get("y") or top) - top
        else:
            self.relative_x = max(12, (right - left) - width - 24)
            self.relative_y = max(24, min((bottom - top) // 3, (bottom - top) - height - 24))

    def _remember_relative_position(self, *, persist: bool = True) -> None:
        if not self.host_region:
            return
        left, top, right, bottom = self.host_region
        width, height = self._canvas_size()
        x, y = self._clamp_origin(self.root.winfo_x(), self.root.winfo_y(), width, height)
        self.relative_x = x - left
        self.relative_y = y - top
        if persist:
            _save_position(self.relative_x, self.relative_y, self.scale)

    def _place_window(self, window, *, width: int, height: int, preferred_x: float, preferred_y: float) -> None:
        remembered = getattr(window, "_memlink_bounds", None)
        if isinstance(remembered, dict):
            width = int(remembered.get("width") or width)
            height = int(remembered.get("height") or height)
            preferred_x = float(remembered.get("x") or preferred_x)
            preferred_y = float(remembered.get("y") or preferred_y)
        x, y = self._clamp_origin(preferred_x, preferred_y, width, height)
        last_bounds = getattr(window, "_memlink_last_bounds", None)
        bounds = (width, height, x, y)
        if last_bounds != bounds:
            window.geometry(f"{width}x{height}+{x}+{y}")
            try:
                window._memlink_last_bounds = bounds
            except Exception:
                pass

    def _position_panel(self) -> None:
        if not (self.panel and self.panel.winfo_exists()):
            return
        width, height = 500, 748
        preferred_x = self.root.winfo_x() + self.root.winfo_width() + 10
        preferred_y = self.root.winfo_y()
        if self.panel_bounds:
            self.panel._memlink_bounds = dict(self.panel_bounds)
        self._place_window(self.panel, width=width, height=height, preferred_x=preferred_x, preferred_y=preferred_y)

    def _position_pending_prompt(self, *, empty: bool = False) -> None:
        if not (self.pending_prompt and self.pending_prompt.winfo_exists()):
            return
        width, height = (420, 220) if empty else (470, 540)
        preferred_x = self.root.winfo_x() + self.root.winfo_width() + 18
        preferred_y = self.root.winfo_y() + (80 if empty else 60)
        remembered = self.empty_prompt_bounds if empty else self.prompt_bounds
        if remembered:
            self.pending_prompt._memlink_bounds = dict(remembered)
        self._place_window(self.pending_prompt, width=width, height=height, preferred_x=preferred_x, preferred_y=preferred_y)

    def _window_min_size(self, window) -> tuple[int, int]:
        kind = getattr(window, "_memlink_window_kind", "panel")
        if kind == "empty-prompt":
            return 360, 200
        if kind == "prompt":
            return 420, 360
        return 420, 560

    def _clamp_window_size(self, window, width: int, height: int) -> tuple[int, int]:
        min_width, min_height = self._window_min_size(window)
        left, top, right, bottom = self._window_bounds()
        max_width = max(min_width, right - left - 8)
        max_height = max(min_height, bottom - top - 8)
        return (
            max(min_width, min(max_width, int(round(width)))),
            max(min_height, min(max_height, int(round(height)))),
        )

    def _remember_window_bounds(self, window) -> None:
        width, height = self._clamp_window_size(window, window.winfo_width(), window.winfo_height())
        x, y = self._clamp_origin(window.winfo_x(), window.winfo_y(), width, height)
        bounds = {"x": x, "y": y, "width": width, "height": height}
        try:
            window._memlink_bounds = dict(bounds)
        except Exception:
            pass
        kind = getattr(window, "_memlink_window_kind", "panel")
        if kind == "empty-prompt":
            self.empty_prompt_bounds = bounds
        elif kind == "prompt":
            self.prompt_bounds = bounds
        else:
            self.panel_bounds = bounds

    def _set_window_geometry(self, window, x: int, y: int, width: int, height: int) -> None:
        width, height = self._clamp_window_size(window, width, height)
        x, y = self._clamp_origin(x, y, width, height)
        bounds = (width, height, x, y)
        if getattr(window, "_memlink_last_bounds", None) != bounds:
            window.geometry(f"{width}x{height}+{x}+{y}")
            try:
                window._memlink_last_bounds = bounds
                window._memlink_bounds = {"x": x, "y": y, "width": width, "height": height}
            except Exception:
                pass

    def _window_edge_margin(self, window) -> int:
        return max(10, min(18, max(window.winfo_width(), window.winfo_height()) // 28))

    def _window_near_edge(self, window, event) -> bool:
        local_x = int(event.x_root - window.winfo_x())
        local_y = int(event.y_root - window.winfo_y())
        margin = self._window_edge_margin(window)
        return (
            local_x <= margin
            or local_y <= margin
            or local_x >= window.winfo_width() - margin
            or local_y >= window.winfo_height() - margin
        )

    def _window_event_is_interactive(self, event) -> bool:
        widget = event.widget
        seen = set()
        while widget is not None and str(widget) not in seen:
            seen.add(str(widget))
            if getattr(widget, "_memlink_interactive", False):
                return True
            widget_class = ""
            try:
                widget_class = widget.winfo_class()
            except Exception:
                widget_class = ""
            if widget_class in {"Button", "Checkbutton", "Text", "Entry", "TCombobox", "Scrollbar", "TScrollbar", "Menu"}:
                return True
            parent_name = ""
            try:
                parent_name = widget.winfo_parent()
            except Exception:
                parent_name = ""
            if not parent_name:
                break
            try:
                widget = widget.nametowidget(parent_name)
            except Exception:
                break
        canvas = event.widget if isinstance(event.widget, Canvas) else None
        if canvas is not None:
            current = canvas.find_withtag("current")
            for item in current:
                for tag in canvas.gettags(item):
                    if tag.startswith(("action_", "icon_", "toggle_")) or tag in {"scrollbar_track", "scrollbar_thumb"}:
                        return True
        return False

    def _bind_window_interactions(self, window) -> None:
        if getattr(window, "_memlink_interaction_bound", False):
            return
        window._memlink_interaction_bound = True
        window._memlink_drag_state = {}
        window.bind("<ButtonPress-1>", lambda event, current=window: self._window_start_drag(current, event), add="+")
        window.bind("<B1-Motion>", lambda event, current=window: self._window_drag(current, event), add="+")
        window.bind("<ButtonRelease-1>", lambda event, current=window: self._window_release(current, event), add="+")
        window.bind("<Motion>", lambda event, current=window: self._window_hover(current, event), add="+")
        window.bind("<Leave>", lambda event, current=window: self._window_leave(current, event), add="+")
        window.bind("<MouseWheel>", lambda event, current=window: self._window_wheel_scale(current, event), add="+")

    def _window_start_drag(self, window, event):
        state = getattr(window, "_memlink_drag_state", {})
        state.clear()
        state.update(
            {
                "dragging": False,
                "resizing": False,
                "moved": False,
                "start_x": event.x_root,
                "start_y": event.y_root,
                "window_x": window.winfo_x(),
                "window_y": window.winfo_y(),
                "start_width": window.winfo_width(),
                "start_height": window.winfo_height(),
                "last_refresh_at": 0.0,
            }
        )
        if self._window_near_edge(window, event):
            state["resizing"] = True
            state["center_x"] = window.winfo_x() + window.winfo_width() / 2
            state["center_y"] = window.winfo_y() + window.winfo_height() / 2
            state["anchor"] = max(
                24.0,
                hypot(event.x_root - state["center_x"], event.y_root - state["center_y"]),
            )
            window.configure(cursor="sizing")
            return "break"
        if self._window_event_is_interactive(event):
            return None
        state["dragging"] = True
        window.configure(cursor="fleur")
        return "break"

    def _window_drag(self, window, event):
        state = getattr(window, "_memlink_drag_state", {})
        if state.get("resizing"):
            current_radius = max(
                24.0,
                hypot(event.x_root - state["center_x"], event.y_root - state["center_y"]),
            )
            factor = current_radius / max(state["anchor"], 1.0)
            width = int(round(state["start_width"] * factor))
            height = int(round(state["start_height"] * factor))
            center_x = state["center_x"]
            center_y = state["center_y"]
            x = int(round(center_x - width / 2))
            y = int(round(center_y - height / 2))
            self._set_window_geometry(window, x, y, width, height)
            self._schedule_resizable_refresh(window)
            state["moved"] = True
            return "break"
        if not state.get("dragging"):
            return None
        dx = event.x_root - state["start_x"]
        dy = event.y_root - state["start_y"]
        if abs(dx) + abs(dy) > 4:
            state["moved"] = True
        self._set_window_geometry(
            window,
            state["window_x"] + dx,
            state["window_y"] + dy,
            state["start_width"],
            state["start_height"],
        )
        return "break"

    def _window_release(self, window, event):
        state = getattr(window, "_memlink_drag_state", {})
        if state.get("dragging") or state.get("resizing") or state.get("moved"):
            self._remember_window_bounds(window)
            self._refresh_resizable_window(window)
            state["dragging"] = False
            state["resizing"] = False
            self._window_hover(window, event)
            return "break"
        state["dragging"] = False
        state["resizing"] = False
        self._window_hover(window, event)
        return None

    def _window_hover(self, window, event):
        state = getattr(window, "_memlink_drag_state", {})
        if state.get("resizing"):
            window.configure(cursor="sizing")
        elif self._window_near_edge(window, event):
            window.configure(cursor="sizing")
        elif self._window_event_is_interactive(event):
            window.configure(cursor="hand2")
        else:
            window.configure(cursor="fleur")

    def _window_leave(self, window, _event=None):
        state = getattr(window, "_memlink_drag_state", {})
        if not state.get("resizing"):
            window.configure(cursor="arrow")

    def _window_wheel_scale(self, window, event):
        if not self._window_near_edge(window, event):
            return None
        delta = getattr(event, "delta", 0)
        if delta == 0:
            return "break"
        factor = 1.06 if delta > 0 else 0.94
        width = int(round(window.winfo_width() * factor))
        height = int(round(window.winfo_height() * factor))
        center_x = window.winfo_x() + window.winfo_width() / 2
        center_y = window.winfo_y() + window.winfo_height() / 2
        x = int(round(center_x - width / 2))
        y = int(round(center_y - height / 2))
        self._set_window_geometry(window, x, y, width, height)
        self._remember_window_bounds(window)
        self._refresh_resizable_window(window)
        return "break"

    def _refresh_resizable_window(self, window) -> None:
        kind = getattr(window, "_memlink_window_kind", "")
        if kind == "panel" and self.panel and window is self.panel and self.panel.winfo_exists():
            self._fill_panel()
        elif kind == "empty-prompt" and self.pending_prompt and window is self.pending_prompt and self.pending_prompt.winfo_exists():
            self._render_empty_pending_prompt()
        elif kind == "prompt" and self.pending_prompt and window is self.pending_prompt and self.pending_prompt.winfo_exists():
            draft = self._current_pending_draft(include_snoozed=True)
            if isinstance(draft, dict):
                self._render_pending_draft_prompt(self._draft_with_local_prompt_edits(draft))

    def _schedule_resizable_refresh(self, window) -> None:
        kind = getattr(window, "_memlink_window_kind", "")
        if kind == "panel":
            if not self.panel or window is not self.panel or not self.panel.winfo_exists():
                return
            if self.panel_refresh_job:
                return

            def _run():
                self.panel_refresh_job = None
                if self.panel and self.panel.winfo_exists():
                    self._fill_panel()

            self.panel_refresh_job = self.root.after(RESIZE_PREVIEW_REFRESH_MS, _run)
            return

        if kind in {"prompt", "empty-prompt"}:
            if not self.pending_prompt or window is not self.pending_prompt or not self.pending_prompt.winfo_exists():
                return
            if self.pending_prompt_refresh_job:
                return

            def _run_prompt():
                self.pending_prompt_refresh_job = None
                if self.pending_prompt and self.pending_prompt.winfo_exists():
                    self._refresh_resizable_window(self.pending_prompt)

            self.pending_prompt_refresh_job = self.root.after(RESIZE_PREVIEW_REFRESH_MS, _run_prompt)
            return

    def _set_root_visible(self, visible: bool) -> None:
        if visible == self.host_visible:
            return
        self.host_visible = visible
        if visible:
            if not self.root.winfo_viewable():
                self.root.deiconify()
        else:
            if self.root.winfo_viewable():
                self.root.withdraw()

    def _set_attached_windows_visible(self, visible: bool) -> None:
        windows = []
        if self.panel and self.panel.winfo_exists():
            windows.append(self.panel)
        if self.pending_prompt and self.pending_prompt.winfo_exists():
            windows.append(self.pending_prompt)
        for window in windows:
            if visible:
                if not window.winfo_viewable():
                    window.deiconify()
            else:
                if window.winfo_viewable():
                    window.withdraw()

    def _sync_window_ownership(self) -> None:
        self.owner_sync_job = None
        owner_hwnd = int(self.host_hwnd or 0)
        if not owner_hwnd:
            return
        windows = [self.root]
        for window in windows:
            try:
                window.update_idletasks()
                hwnd = _window_hwnd(window)
            except Exception:
                hwnd = 0
            if hwnd and int(_get_window_owner(hwnd) or 0) != owner_hwnd:
                _set_window_owner(hwnd, owner_hwnd)

    def _queue_window_ownership_sync(self) -> None:
        if self.owner_sync_job:
            return

        def _run():
            self._sync_window_ownership()

        self.owner_sync_job = self.root.after(30, _run)

    def _sync_host_scope(self) -> None:
        now = time.time()
        host = self._host_state()
        self.host_hwnd = int(host.get("hwnd") or 0) if host else 0
        self.host_pid = _window_process_id(self.host_hwnd) if self.host_hwnd else 0
        if host:
            self.host_rect = host.get("rect")
            self.host_region = host.get("region")
            self.host_presence_grace_until = now + HOST_PRESENCE_GRACE_SECONDS
        interactive_open = (
            (self.panel and self.panel.winfo_exists())
            or (self.pending_prompt and self.pending_prompt.winfo_exists())
        )
        if host and host.get("active"):
            grace_seconds = HOST_PANEL_FOCUS_GRACE_SECONDS if interactive_open else HOST_ICON_FOCUS_GRACE_SECONDS
            self.host_focus_grace_until = now + grace_seconds
        elif not interactive_open:
            self.host_focus_grace_until = 0.0
        icon_visible = bool(self.host_region) and (bool(host) or now < self.host_presence_grace_until)
        attached_visible = icon_visible and (
            interactive_open
            or bool(self.panel and self.panel.winfo_exists())
            or bool(self.pending_prompt and self.pending_prompt.winfo_exists())
        )
        if not icon_visible:
            self._set_attached_windows_visible(False)
            self._set_root_visible(False)
            return
        self._ensure_relative_position()
        left, top, *_ = self.host_region
        width, height = self._canvas_size()
        preferred_x = left + (self.relative_x or 0)
        preferred_y = top + (self.relative_y or 0)
        if not (self.dragging or self.resizing or interactive_open):
            self._set_geometry(preferred_x, preferred_y)
        self._set_root_visible(True)
        self._set_attached_windows_visible(attached_visible)
        if attached_visible and not (self.dragging or self.resizing or interactive_open):
            self._position_panel()
            self._position_pending_prompt(empty=self.pending_prompt_is_empty)
        self._queue_window_ownership_sync()

    def _clean_mode(self) -> str:
        mode = str(self.state.get("mode") or "off")
        return "passive" if mode == "ask" else mode

    def _load_icon_images(self) -> None:
        self.icon_sources = {}
        self.icon_images = {}
        if Image is None or ImageTk is None or ImageOps is None or ImageDraw is None:
            return
        for key, path in [("lit", LIT_ICON_PATH), ("unlit", UNLIT_ICON_PATH)]:
            prepared = self._prepare_icon_source(path)
            if prepared is not None:
                self.icon_sources[key] = prepared

    def _load_window_skin(self) -> None:
        self.window_skin_source = None
        self.panel_bg_source = None
        self.dropdown_arrow_source = None
        self.window_skin_images = {}
        self.panel_bg_images = {}
        self.panel_field_images = {}
        self.dropdown_arrow_images = {}
        if Image is None or ImageTk is None or ImageOps is None:
            return
        if not UI_SKIN_PATH.exists():
            self.window_skin_source = None
        else:
            try:
                self.window_skin_source = Image.open(UI_SKIN_PATH).convert("RGBA")
            except Exception:
                self.window_skin_source = None
        if PANEL_BG_PATH and PANEL_BG_PATH.exists():
            try:
                self.panel_bg_source = Image.open(PANEL_BG_PATH).convert("RGBA")
            except Exception:
                self.panel_bg_source = None
        if DROPDOWN_ARROW_PATH and DROPDOWN_ARROW_PATH.exists():
            try:
                self.dropdown_arrow_source = Image.open(DROPDOWN_ARROW_PATH).convert("RGBA")
            except Exception:
                self.dropdown_arrow_source = None

    def _scaled_panel_background(self, width: int, height: int):
        cache_key = (width, height)
        if cache_key in self.panel_bg_images:
            return self.panel_bg_images[cache_key]
        if self.panel_bg_source is None or Image is None or ImageTk is None or ImageOps is None:
            return None
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        skin = ImageOps.fit(self.panel_bg_source, (width, height), method=resample, centering=(0.5, 0.0))
        result = ImageTk.PhotoImage(skin)
        self.panel_bg_images[cache_key] = result
        return result

    def _scaled_panel_field_background(self, width: int, height: int):
        cache_key = (width, height)
        if cache_key in self.panel_field_images:
            return self.panel_field_images[cache_key]
        if self.panel_bg_source is None or Image is None or ImageTk is None or ImageOps is None or ImageDraw is None:
            return None
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        skin = ImageOps.fit(self.panel_bg_source, (width, height), method=resample, centering=(0.5, 0.0)).convert("RGBA")

        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        radius = max(4, int(min(width, height) * 0.16))
        draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=(0, 0, 0, 0), outline=(43, 32, 23, 190), width=1)
        draw.rounded_rectangle((1, 1, width - 2, height - 2), radius=max(3, radius - 1), fill=(0, 0, 0, 0), outline=(232, 204, 163, 40), width=1)
        draw.line((2, 2, width - 4, 2), fill=(241, 220, 184, 55), width=1)
        draw.line((2, 2, 2, height - 4), fill=(241, 220, 184, 40), width=1)
        draw.line((2, height - 2, width - 3, height - 2), fill=(18, 13, 10, 120), width=2)
        draw.line((width - 2, 2, width - 2, height - 3), fill=(18, 13, 10, 105), width=2)
        skin = Image.alpha_composite(skin, overlay)

        result = ImageTk.PhotoImage(skin)
        self.panel_field_images[cache_key] = result
        return result

    def _scaled_dropdown_arrow(self, width: int, height: int):
        cache_key = (width, height)
        if cache_key in self.dropdown_arrow_images:
            return self.dropdown_arrow_images[cache_key]
        if self.dropdown_arrow_source is None or Image is None or ImageTk is None:
            return None
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        image = self.dropdown_arrow_source.resize((max(1, width), max(1, height)), resample)
        result = ImageTk.PhotoImage(image)
        self.dropdown_arrow_images[cache_key] = result
        return result

    def _prepare_icon_source(self, path: Path):
        if not path.exists():
            return None
        try:
            image = Image.open(path).convert("RGBA")
        except Exception:
            return None

        pixels = image.load()
        width, height = image.size
        for y in range(height):
            for x in range(width):
                r, g, b, a = pixels[x, y]
                average = (r + g + b) / 3
                spread = max(r, g, b) - min(r, g, b)
                if r > 238 and g > 238 and b > 238:
                    pixels[x, y] = (255, 255, 255, 0)
                    continue
                if average > 210 and spread < 45:
                    fade = max(0.0, min(1.0, (248.0 - average) / 38.0))
                    pixels[x, y] = (r, g, b, int(a * fade))
        return image

    def _scaled_icon(self, key: str, max_width: int, max_height: int):
        cache_key = (key, max_width, max_height)
        if cache_key in self.icon_images:
            return self.icon_images[cache_key]
        if Image is None or ImageTk is None or ImageOps is None or ImageDraw is None:
            return None
        source = self.icon_sources.get(key)
        if source is None:
            return None

        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        source_w, source_h = source.size
        scale = min(max_width / max(source_w, 1), max_height / max(source_h, 1))
        scaled_w = max(1, int(round(source_w * scale)))
        scaled_h = max(1, int(round(source_h * scale)))
        resized = source.resize((scaled_w, scaled_h), resample).convert("RGBA")

        # Tk 的 transparentcolor 只能做色键透明，不能保留半透明边缘。
        # 所以这里把图标先压到深色哑光底上，再把完全透明区域替换成色键透明，
        # 避免放大时出现紫边或黑块。
        matte_r = int(THEME_BG[1:3], 16)
        matte_g = int(THEME_BG[3:5], 16)
        matte_b = int(THEME_BG[5:7], 16)
        key_r = int(TRANSPARENT[1:3], 16)
        key_g = int(TRANSPARENT[3:5], 16)
        key_b = int(TRANSPARENT[5:7], 16)

        matte = Image.new("RGBA", (scaled_w, scaled_h), (matte_r, matte_g, matte_b, 255))
        matte.alpha_composite(resized)
        matte_pixels = matte.load()
        alpha_pixels = resized.getchannel("A").load()
        for py in range(scaled_h):
            for px in range(scaled_w):
                alpha = alpha_pixels[px, py]
                if alpha <= 12:
                    matte_pixels[px, py] = (key_r, key_g, key_b, 255)
                else:
                    r, g, b, _a = matte_pixels[px, py]
                    matte_pixels[px, py] = (r, g, b, 255)

        canvas = Image.new("RGBA", (max_width, max_height), (key_r, key_g, key_b, 255))
        x = (max_width - scaled_w) // 2
        y = (max_height - scaled_h) // 2
        canvas.alpha_composite(matte, (x, y))
        result = ImageTk.PhotoImage(canvas)
        self.icon_images[cache_key] = result
        return result

    def _scaled_window_skin(self, width: int, height: int):
        cache_key = (width, height)
        if cache_key in self.window_skin_images:
            return self.window_skin_images[cache_key]
        if self.window_skin_source is None or Image is None or ImageTk is None or ImageOps is None:
            return None
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        skin = ImageOps.fit(self.window_skin_source, (width, height), method=resample, centering=(0.5, 0.0))
        result = ImageTk.PhotoImage(skin)
        self.window_skin_images[cache_key] = result
        return result

    def _compose_panel_skin(self, width: int, height: int):
        cache_key = (width, height)
        if cache_key in self.panel_skin_images:
            return self.panel_skin_images[cache_key]
        if self.window_skin_source is None or Image is None or ImageTk is None or ImageOps is None:
            return self._scaled_window_skin(width, height)
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        skin = ImageOps.fit(self.window_skin_source, (width, height), method=resample, centering=(0.5, 0.0)).convert("RGBA")
        stone = self.window_skin_source.crop(PANEL_STONE_PATCH_CROP).resize((max(64, width), max(64, height)), resample)

        def cover(rect: tuple[int, int, int, int]) -> None:
            x, y, w, h = self._scale_ui_rect(rect, width, height)
            if w <= 0 or h <= 0:
                return
            patch = stone.crop((0, 0, min(stone.width, w), min(stone.height, h)))
            if patch.size != (w, h):
                patch = stone.resize((w, h), resample)
            skin.alpha_composite(patch.convert("RGBA"), (x, y))

        for rect in (
            TOP_PANEL_COVER_RECT,
            WITNESS_SECTION_COVER_RECT,
            ADMIN_SECTION_COVER_RECT,
            VCP_SECTION_COVER_RECT,
        ):
            cover(rect)

        result = ImageTk.PhotoImage(skin)
        self.panel_skin_images[cache_key] = result
        return result

    def _panel_text(self, canvas, x: int, y: int, *, text: str, font: tuple[str, int, str], fill: str, shadow: str = "#1a1410", anchor: str = "nw", width: int | None = None) -> None:
        kwargs = {"anchor": anchor, "text": text, "font": font, "fill": shadow}
        if width:
            kwargs["width"] = width
            kwargs["justify"] = "left"
        canvas.create_text(x + 2, y + 2, **kwargs)
        kwargs["fill"] = fill
        canvas.create_text(x, y, **kwargs)

    def _canvas_action_text(self, canvas, x: int, y: int, *, text: str, command, fill: str, font: tuple[str, int, str], shadow: str = "#241912", active_fill: str | None = None) -> tuple[int, int]:
        tag = f"action_{int(time.time() * 1000000)}_{x}_{y}"
        canvas.create_text(x + 2, y + 2, text=text, font=font, fill=shadow, anchor="nw", tags=(tag,))
        canvas.create_text(x, y, text=text, font=font, fill=active_fill or fill, anchor="nw", tags=(tag,))
        bbox = canvas.bbox(tag) or (x, y, x + 10, y + 10)
        hit = canvas.create_rectangle(bbox[0] - 12, bbox[1] - 8, bbox[2] + 12, bbox[3] + 8, outline="", fill="")
        canvas.addtag_withtag(tag, hit)
        canvas.tag_bind(tag, "<Button-1>", lambda _event: command())
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _canvas_icon_button(
        self,
        canvas,
        x: int,
        y: int,
        *,
        text: str,
        command,
        size: int = 20,
        fill: str = PANEL_TEXT_GOLD,
        outline: str = "#6a5136",
        font: tuple[str, int, str] = (PANEL_FONT_FAMILY, 12, "bold"),
    ) -> None:
        tag = f"icon_{int(time.time() * 1000000)}_{x}_{y}"
        canvas.create_rectangle(x, y, x + size, y + size, outline=outline, width=1, fill="", tags=(tag,))
        canvas.create_text(x + size / 2 + 1, y + size / 2 + 1, text=text, font=font, fill="#241912", tags=(tag,))
        canvas.create_text(x + size / 2, y + size / 2, text=text, font=font, fill=fill, tags=(tag,))
        canvas.tag_bind(tag, "<Button-1>", lambda _event: command())

    def _canvas_toggle(self, canvas, x: int, y: int, *, text: str, value: bool, command, fill: str, font: tuple[str, int, str]) -> int:
        tag = f"toggle_{int(time.time() * 1000000)}_{x}_{y}"
        box_size = 14
        outline = PANEL_TEXT_GOLD_BRIGHT if value else PANEL_TEXT_DARK
        canvas.create_rectangle(x, y + 2, x + box_size, y + 2 + box_size, outline=outline, width=1, fill="", tags=(tag,))
        if value:
            canvas.create_line(x + 3, y + 9, x + 6, y + 13, x + 12, y + 4, fill=PANEL_TEXT_GOLD_BRIGHT, width=2, tags=(tag,))
        canvas.create_text(x + box_size + 8, y, text=text, font=font, fill=fill, anchor="nw", tags=(tag,))
        bbox = canvas.bbox(tag) or (x, y, x + 10, y + 10)
        hit = canvas.create_rectangle(bbox[0] - 4, bbox[1] - 2, bbox[2] + 4, bbox[3] + 2, outline="", fill="")
        canvas.addtag_withtag(tag, hit)
        canvas.tag_bind(tag, "<Button-1>", lambda _event: command())
        return bbox[3] - bbox[1]

    def _cropped_window_skin(self, crop_box: tuple[int, int, int, int], width: int, height: int):
        cache_key = (crop_box, width, height)
        if cache_key in self.window_crop_images:
            return self.window_crop_images[cache_key]
        if self.window_skin_source is None or Image is None or ImageTk is None:
            return None
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        texture = self.window_skin_source.crop(crop_box).resize((width, height), resample)
        result = ImageTk.PhotoImage(texture)
        self.window_crop_images[cache_key] = result
        return result

    def _render_widget_skin(
        self,
        crop_box: tuple[int, int, int, int],
        width: int,
        height: int,
        *,
        cover_rect: tuple[float, float, float, float] | None = None,
        cover_fill: tuple[int, int, int, int] = (35, 30, 26, 210),
    ):
        cache_key = (crop_box, width, height, cover_rect, cover_fill)
        if cache_key in self.window_crop_images:
            return self.window_crop_images[cache_key]
        if self.window_skin_source is None or Image is None or ImageTk is None or ImageDraw is None:
            return None
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        texture = self.window_skin_source.crop(crop_box).resize((width, height), resample).convert("RGBA")
        if cover_rect is not None:
            left = int(round(width * cover_rect[0]))
            top = int(round(height * cover_rect[1]))
            right = int(round(width * cover_rect[2]))
            bottom = int(round(height * cover_rect[3]))
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            radius = max(4, int(min(width, height) * 0.08))
            draw.rounded_rectangle((left, top, right, bottom), radius=radius, fill=cover_fill)
            texture = Image.alpha_composite(texture, overlay)
        result = ImageTk.PhotoImage(texture)
        self.window_crop_images[cache_key] = result
        return result

    def _build_skinned_window(self, window, *, width: int, height: int, content_rect: tuple[int, int, int, int]):
        shell = Frame(window, bg=THEME_BG, highlightthickness=0, bd=0)
        shell.pack(fill="both", expand=True)
        skin = self._scaled_window_skin(width, height)
        if skin is not None:
            background = Label(shell, image=skin, borderwidth=0, highlightthickness=0)
            background.image = skin
            background.place(x=0, y=0, relwidth=1, relheight=1)
            shell._memlink_skin_image = skin
            shell._memlink_skin_label = background
        left, top, right, bottom = content_rect
        content = Frame(shell, bg=THEME_BG, highlightthickness=0, bd=0)
        content.place(x=left, y=top, width=max(1, right - left), height=max(1, bottom - top))
        return shell, content

    def _metric(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def _canvas_size(self) -> tuple[int, int]:
        return self._metric(92), self._metric(118)

    def _edge_margin(self) -> int:
        return max(6, self._metric(6))

    def _icon_box(self) -> tuple[int, int, int, int]:
        return self._metric(5), self._metric(4), self._metric(87), self._metric(112)

    def _icon_center(self) -> tuple[int, int]:
        left, top, right, bottom = self._icon_box()
        return (left + right) // 2, (top + bottom) // 2

    def _icon_radius(self) -> int:
        return max(18, self._metric(22))

    def _is_near_icon_ring(self, x: int, y: int) -> bool:
        return False

    def _icon_hotspots(self) -> dict[str, tuple[int, int, int, int]]:
        left, top, right, bottom = self._icon_box()
        center_x = (left + right) // 2
        return {
            "panel": (
                center_x - self._metric(11),
                top + self._metric(2),
                center_x + self._metric(11),
                top + self._metric(54),
            ),
            "fire": (
                left + self._metric(2),
                top + self._metric(50),
                right - self._metric(2),
                bottom - self._metric(2),
            ),
        }

    def _hit_action(self, x: int, y: int) -> str | None:
        for action, (left, top, right, bottom) in self._icon_hotspots().items():
            if left <= x <= right and top <= y <= bottom:
                return action
        left, top, right, bottom = self._icon_box()
        if left <= x <= right and top <= y <= bottom:
            return "fire"
        return None

    def _is_near_edge(self, x: int, y: int) -> bool:
        width, height = self._canvas_size()
        margin = self._edge_margin()
        return (
            x <= margin
            or y <= margin
            or x >= width - margin
            or y >= height - margin
            or self._is_near_icon_ring(x, y)
        )

    def _set_geometry(self, x: int, y: int) -> None:
        width, height = self._canvas_size()
        x, y = self._clamp_origin(x, y, width, height)
        if (
            self.root.winfo_width() != width
            or self.root.winfo_height() != height
            or self.root.winfo_x() != x
            or self.root.winfo_y() != y
        ):
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        if self.canvas.winfo_width() != width or self.canvas.winfo_height() != height:
            self.canvas.configure(width=width, height=height)

    def _apply_scale(self, scale: float, center: tuple[float, float] | None = None) -> None:
        self.scale = max(self.min_scale, min(self.max_scale, scale))
        if center is None:
            center = (
                self.root.winfo_x() + self.root.winfo_width() / 2,
                self.root.winfo_y() + self.root.winfo_height() / 2,
            )
        width, height = self._canvas_size()
        x = center[0] - width / 2
        y = center[1] - height / 2
        self._set_geometry(int(round(x)), int(round(y)))
        self._remember_relative_position()

    def _restore_position(self) -> None:
        saved = self._saved_position_state
        scale = float(saved.get("scale", 1.0)) if isinstance(saved, dict) else 1.0
        self.scale = max(self.min_scale, min(self.max_scale, scale))
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        fallback_x = screen_w - 150
        fallback_y = screen_h - 180
        if isinstance(saved, dict) and "x" in saved and "y" in saved:
            fallback_x = int(saved.get("x") or fallback_x)
            fallback_y = int(saved.get("y") or fallback_y)
        self._set_geometry(fallback_x, fallback_y)

    def _tick(self) -> None:
        self._sync_host_scope()
        self.flame_phase = (self.flame_phase + 1) % 4
        self.lifecycle_state = _read_lifecycle_state()
        if time.time() - self.last_status_refresh >= 2.5:
            self._refresh_writer_status()
        self._draw()
        self.root.after(HOST_SCOPE_TICK_MS, self._tick)

    def _refresh_state(self) -> None:
        self.lifecycle_state = _read_lifecycle_state()
        try:
            self.state = _request_json("GET", "/api/session-memory-gate")
            self.connected = True
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            self.connected = False
            self._maybe_recover_runtime()
        self._draw()
        if self.panel and self.panel.winfo_exists():
            self._refresh_panel_if_needed()

    def _refresh_writer_status(self) -> None:
        self.last_status_refresh = time.time()
        self.lifecycle_state = _read_lifecycle_state()
        try:
            self.writer_status = _request_json("GET", "/api/session-auto-writer-status")
            self.connected = True
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            self.writer_status = {}
            self._maybe_recover_runtime()
            return
        self._maybe_prompt_pending_draft()
        if self.panel and self.panel.winfo_exists():
            self._refresh_panel_if_needed()

    def _runtime_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT_DIR)
        env["MEMLINK_SHRINE_API_BASE"] = API_BASE
        env["MEMLINK_SHRINE_HOST_ID"] = HOST_ID
        env["MEMLINK_SHRINE_HOST_WINDOW_TITLE"] = HOST_WINDOW_TITLE
        env["MEMLINK_SHRINE_DB"] = str(ROOT_DIR / "data" / "memlink_shrine.db")

        vcp_root = ROOT_DIR.parents[3] / "__inspect_vcp_toolbox"
        vcp_config = _parse_env_file(vcp_root / "config.env")
        if vcp_root.exists():
            env.setdefault("VCP_ROOT_PATH", str(vcp_root))
        port = str(vcp_config.get("PORT") or "").strip()
        if port:
            env.setdefault("VCP_BASE_URL", f"http://127.0.0.1:{port}/admin_api/dailynotes")
        username = str(vcp_config.get("AdminUsername") or "").strip()
        password = str(vcp_config.get("AdminPassword") or "").strip()
        if username:
            env.setdefault("VCP_ADMIN_USERNAME", username)
        if password:
            env.setdefault("VCP_ADMIN_PASSWORD", password)
        bridge_root_text = str(vcp_config.get("KNOWLEDGEBASE_ROOT_PATH") or "").strip()
        if bridge_root_text:
            bridge_root = Path(bridge_root_text)
            if not bridge_root.is_absolute():
                bridge_root = vcp_root / bridge_root
            env.setdefault("VCP_BRIDGE_ROOT_PATH", str(bridge_root.resolve()))
        env.setdefault("VCP_BRIDGE_NAMESPACE", "MemlinkShrineBridge")
        api_key = str(vcp_config.get("API_Key") or "").strip()
        if api_key:
            env.setdefault("GOOGLE_API_KEY", api_key)
        env.setdefault("MEMLINK_SHRINE_GEMINI_MODEL", "gemini-3-flash-preview")
        env.setdefault("OPENMEMORY_BASE_URL", "http://localhost:8765")
        env.setdefault("OPENMEMORY_USER_ID", "administrator-main")
        env.setdefault("OPENMEMORY_APP_NAME", "codex")
        return env

    def _start_python_module(self, module: str, module_args: list[str] | None = None, *, windowless: bool = False) -> bool:
        python_exe = _resolve_python_command(windowless=windowless)
        if not python_exe:
            return False
        args = ["-m", module, *(module_args or [])]
        try:
            subprocess.Popen(
                [python_exe, *args],
                cwd=str(ROOT_DIR),
                env=self._runtime_env(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except OSError:
            return False

    def _maybe_recover_runtime(self) -> None:
        now = time.time()
        cooldown = RECOVERY_COOLDOWN_SECONDS if self.last_recovery_error == "" else RECOVERY_RETRY_ON_FAILURE_SECONDS
        if now - self.last_recovery_attempt < cooldown:
            return
        self.last_recovery_attempt = now
        self.last_recovery_error = ""

        if not _process_running("memlink_shrine.web:app"):
            if not self._start_python_module(
                "uvicorn",
                ["memlink_shrine.web:app", "--host", "127.0.0.1", "--port", "7861"],
                windowless=False,
            ):
                self.last_recovery_error = "web"
                return

        if not _process_running("memlink_shrine.cli*session-auto-watch"):
            self._start_python_module(
                "memlink_shrine.cli",
                ["session-auto-watch", "--interval", "8", "--session-limit", "4"],
                windowless=False,
            )

    def _parse_iso_timestamp(self, value: str | None) -> float:
        text = str(value or "").strip()
        if not text:
            return 0.0
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    def _pending_drafts(self) -> list[dict]:
        drafts = self.writer_status.get("pending_drafts")
        if not isinstance(drafts, list) or not drafts:
            return []
        items = [draft for draft in drafts if isinstance(draft, dict)]
        items.sort(
            key=lambda draft: max(
                self._parse_iso_timestamp(draft.get("updated_at")),
                self._parse_iso_timestamp(draft.get("last_message_at")),
                self._parse_iso_timestamp(draft.get("created_at")),
            ),
            reverse=True,
        )
        return items

    def _current_pending_draft(self, *, include_snoozed: bool = False) -> dict | None:
        drafts = self._pending_drafts()
        if not drafts:
            return None
        if include_snoozed:
            return drafts[0]
        for draft in drafts:
            draft_id = str(draft.get("draft_id") or "")
            if self.snoozed_draft_id and draft_id == self.snoozed_draft_id:
                continue
            return draft
        return None

    def _close_pending_prompt(self, *, snooze: bool = False) -> None:
        current_draft = self._current_pending_draft(include_snoozed=True)
        if snooze and isinstance(current_draft, dict):
            self.snoozed_draft_id = str(current_draft.get("draft_id") or "")
        if self.pending_prompt and self.pending_prompt.winfo_exists():
            self.pending_prompt.destroy()
        self.pending_prompt = None
        self.pending_prompt_is_empty = False
        self.pending_point_editors = []
        self.pending_graph_vars = []
        self.pending_graph_boxes = []
        self.pending_point_cards = []
        self.pending_raw_editor = None
        self.last_prompt_signature = ""

    def _pending_draft_signature(self, draft: dict | None) -> str:
        if not isinstance(draft, dict):
            return ""
        preview = draft.get("preview") if isinstance(draft.get("preview"), dict) else {}
        payload = {
            "draft_id": draft.get("draft_id"),
            "updated_at": draft.get("updated_at"),
            "trigger_reason": draft.get("trigger_reason"),
            "message_count": draft.get("message_count"),
            "first_message_at": draft.get("first_message_at"),
            "last_message_at": draft.get("last_message_at"),
            "preview": preview,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _draft_with_local_prompt_edits(self, draft: dict) -> dict:
        if not isinstance(draft, dict):
            return draft
        if not (self.pending_prompt and self.pending_prompt.winfo_exists() and self.pending_point_cards):
            return draft
        preview = dict(draft.get("preview") or {})
        local_edits = self._collect_pending_prompt_edits()
        remote_points = [str(item).strip() for item in preview.get("memory_points") or [] if str(item).strip()]
        local_points = [str(item).strip() for item in local_edits.get("memory_points") or [] if str(item).strip()]
        if local_points:
            merged_points = list(local_points)
            if len(remote_points) > len(local_points):
                merged_points.extend(remote_points[len(local_points) :])
            preview["memory_points"] = merged_points
        elif remote_points:
            preview["memory_points"] = remote_points

        remote_graphs = [str(item).strip() for item in preview.get("graph_assignments") or [] if str(item).strip()]
        local_graphs = [str(item).strip() for item in local_edits.get("graph_assignments") or [] if str(item).strip()]
        merged_points = [str(item).strip() for item in preview.get("memory_points") or [] if str(item).strip()]
        if local_graphs:
            merged_graphs = list(local_graphs)
            if len(remote_graphs) > len(local_graphs):
                merged_graphs.extend(remote_graphs[len(local_graphs) :])
        else:
            merged_graphs = list(remote_graphs)
        fallback_graph = str(draft.get("thread_name") or "未归属项目").strip() or "未归属项目"
        while len(merged_graphs) < len(merged_points):
            merged_graphs.append(fallback_graph)
        if merged_points:
            preview["graph_assignments"] = merged_graphs[: len(merged_points)]

        local_raw = str(local_edits.get("raw_excerpt") or "").strip()
        if local_raw:
            preview["raw_excerpt"] = local_raw

        merged = dict(draft)
        merged["preview"] = preview
        return merged

    def _open_pending_prompt_from_panel(self) -> None:
        self.snoozed_draft_id = ""
        self.last_prompted_draft_id = ""
        self.last_prompt_signature = ""
        if not self._current_pending_draft(include_snoozed=True):
            self._show_empty_pending_prompt()
            return
        self._maybe_prompt_pending_draft(force=True)

    def _show_empty_pending_prompt(self) -> None:
        self._close_pending_prompt()
        self.pending_prompt = Toplevel(self.root)
        self.pending_prompt._memlink_window_kind = "empty-prompt"
        self.pending_prompt_is_empty = True
        self.pending_prompt.title("Memlink Shrine · 残影草稿箱")
        self.pending_prompt.overrideredirect(True)
        self.pending_prompt.attributes("-topmost", False)
        self.pending_prompt.configure(bg=THEME_BG, bd=0, highlightthickness=0)
        self.pending_prompt.protocol("WM_DELETE_WINDOW", self._close_pending_prompt)
        self._bind_window_interactions(self.pending_prompt)
        self._position_pending_prompt(empty=True)
        self._queue_window_ownership_sync()
        self._render_empty_pending_prompt()
        try:
            self.pending_prompt.deiconify()
            self.pending_prompt.lift()
            self.pending_prompt.focus_force()
        except Exception:
            pass

    def _panel_signature(self) -> str:
        payload = {
            "connected": self.connected,
            "mode": self._clean_mode(),
            "confirm_before_write": bool(self.state.get("confirm_before_write", True)),
            "selected_models": self.state.get("selected_models", {}),
            "available_graphs": self.state.get("available_graphs", []),
            "pending_draft": self._current_pending_draft(),
        }
        try:
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return repr(payload)

    def _refresh_panel_if_needed(self, *, force: bool = False) -> None:
        if not self.panel or not self.panel.winfo_exists():
            return
        signature = self._panel_signature()
        if not force and signature == self.last_panel_signature:
            return
        self._fill_panel()

    def _build_scrollable_area(
        self,
        parent,
        *,
        bg: str,
        fill: str = "both",
        expand: bool = True,
        padx: int = 0,
        pady: int | tuple[int, int] = 0,
    ) -> tuple[Frame, Canvas, Frame]:
        outer = Frame(parent, bg=bg)
        outer.pack(fill=fill, expand=expand, padx=padx, pady=pady)
        canvas = Canvas(outer, bg=bg, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview, style="Memlink.Vertical.TScrollbar")
        content = Frame(canvas, bg=bg)
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def _sync(_event=None) -> None:
            bbox = canvas.bbox("all")
            if bbox:
                canvas.configure(scrollregion=bbox)
            canvas.itemconfigure(content_window, width=canvas.winfo_width())

        def _on_wheel(event) -> str:
            delta = getattr(event, "delta", 0)
            if delta:
                canvas.yview_scroll(-1 * int(delta / 120), "units")
                return "break"
            return "break"

        content.bind("<Configure>", _sync)
        canvas.bind("<Configure>", _sync)
        canvas.bind("<MouseWheel>", _on_wheel)
        content.bind("<MouseWheel>", _on_wheel)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return outer, canvas, content

    def _build_prompt_shell(self, window, *, width: int, height: int, title: str, on_close) -> Frame:
        shell = Frame(window, bg=THEME_BG, highlightthickness=0, bd=0)
        shell.pack(fill="both", expand=True)
        canvas = Canvas(shell, width=width, height=height, bg=THEME_BG, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        bg_image = self._scaled_panel_background(width, height)
        if bg_image is not None:
            canvas.create_image(0, 0, image=bg_image, anchor="nw")
            shell._bg_image = bg_image
        self._panel_text(canvas, 16, 14, text=title, font=(PANEL_FONT_FAMILY, 19, "bold"), fill=PANEL_TEXT_GOLD)
        self._canvas_icon_button(
            canvas,
            width - 36,
            12,
            text="×",
            command=on_close,
            size=18,
            fill=PANEL_TEXT_GOLD_BRIGHT,
            font=(PANEL_FONT_FAMILY, 11, "bold"),
        )
        content = Frame(canvas, bg=THEME_BG, highlightthickness=0, bd=0)
        canvas.create_window(12, 52, window=content, anchor="nw", width=width - 24, height=height - 60)
        shell._canvas = canvas
        shell._content = content
        return content

    def _prompt_window_size(self, *, default_width: int, default_height: int) -> tuple[int, int]:
        if not self.pending_prompt or not self.pending_prompt.winfo_exists():
            return default_width, default_height
        self.pending_prompt.update_idletasks()
        remembered = getattr(self.pending_prompt, "_memlink_bounds", {}) or {}
        actual_width = max(1, int(self.pending_prompt.winfo_width() or 0))
        actual_height = max(1, int(self.pending_prompt.winfo_height() or 0))
        width = int(remembered.get("width") or 0)
        height = int(remembered.get("height") or 0)
        width = width if width > 40 else (actual_width if actual_width > 40 else default_width)
        height = height if height > 40 else (actual_height if actual_height > 40 else default_height)
        return self._clamp_window_size(self.pending_prompt, width, height)

    def _clear_pending_prompt_children(self) -> None:
        if not self.pending_prompt or not self.pending_prompt.winfo_exists():
            return
        for child in self.pending_prompt.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

    def _render_empty_pending_prompt(self) -> None:
        if not self.pending_prompt or not self.pending_prompt.winfo_exists():
            return
        width, height = self._prompt_window_size(default_width=420, default_height=220)
        self._set_window_geometry(self.pending_prompt, self.pending_prompt.winfo_x(), self.pending_prompt.winfo_y(), width, height)
        self._clear_pending_prompt_children()
        self.pending_prompt_is_empty = True
        content = self._build_prompt_shell(
            self.pending_prompt,
            width=width,
            height=height,
            title="残影草稿箱",
            on_close=self._close_pending_prompt,
        )

        wraplength = max(260, width - 60)
        Label(
            content,
            text="当前没有待确认残影草稿。命中写入阈值后，新草稿会出现在这里。",
            bg=THEME_BG,
            fg=PANEL_TEXT_GOLD,
            font=(PANEL_FONT_FAMILY, 12, "bold"),
            wraplength=wraplength,
            justify="left",
        ).pack(anchor="w", pady=(8, 8), padx=10)
        Label(
            content,
            text="你也可以保持被动写入开启，等下一次草稿生成后直接从这里确认。",
            bg=THEME_BG,
            fg=PANEL_TEXT_GOLD_MUTED,
            font=(PANEL_FONT_FAMILY, 11, "normal"),
            wraplength=wraplength,
            justify="left",
        ).pack(anchor="w", padx=10)

        row = Frame(content, bg=THEME_BG)
        row.pack(fill="x", side="bottom", pady=(18, 0), padx=10)
        close_wrap = Canvas(row, width=56, height=24, bg=THEME_BG, highlightthickness=0, bd=0)
        close_wrap.pack(side="right")
        self._canvas_action_text(
            close_wrap,
            0,
            2,
            text="关闭",
            command=self._close_pending_prompt,
            fill=PANEL_TEXT_GOLD,
            font=(PANEL_FONT_FAMILY, 11, "bold"),
        )

    def _render_pending_draft_prompt(self, draft: dict[str, Any]) -> None:
        if not self.pending_prompt or not self.pending_prompt.winfo_exists():
            return
        width, height = self._prompt_window_size(default_width=470, default_height=540)
        self._set_window_geometry(self.pending_prompt, self.pending_prompt.winfo_x(), self.pending_prompt.winfo_y(), width, height)
        self._clear_pending_prompt_children()
        self.pending_prompt_is_empty = False

        session_id = str(draft.get("session_id") or "")
        self.pending_point_editors = []
        self.pending_graph_vars = []
        self.pending_graph_boxes = []
        self.pending_point_cards = []
        self.pending_raw_editor = None
        preview = draft.get("preview", {}) if isinstance(draft.get("preview"), dict) else {}
        time_text = self._draft_time_text(draft)
        graph_options = self._graph_options(draft)
        graph_assignments = preview.get("graph_assignments") if isinstance(preview.get("graph_assignments"), list) else []

        shell_content = self._build_prompt_shell(
            self.pending_prompt,
            width=width,
            height=height,
            title="残影草稿确认",
            on_close=lambda: self._close_pending_prompt(snooze=True),
        )
        outer, _, content = self._build_scrollable_area(
            shell_content,
            bg=THEME_BG,
            padx=0,
            pady=0,
        )
        wraplength = max(280, width - 50)
        Label(
            content,
            bg=THEME_BG,
            text="自动残影草稿已生成",
            fg=PANEL_TEXT_GOLD,
            font=(PANEL_FONT_FAMILY, 14, "bold"),
        ).pack(anchor="w", padx=16, pady=(14, 6))
        Label(
            content,
            text=f"线程：{draft.get('thread_name') or 'Codex 会话'}",
            bg=THEME_BG,
            fg=PANEL_TEXT_GOLD,
            font=(PANEL_FONT_FAMILY, 11, "normal"),
            wraplength=wraplength,
            justify="left",
        ).pack(anchor="w", padx=16)
        Label(
            content,
            text=f"触发原因：{draft.get('trigger_reason') or '自动写入阈值命中'}",
            bg=THEME_BG,
            fg=PANEL_TEXT_GOLD_MUTED,
            font=(PANEL_FONT_FAMILY, 11, "normal"),
            wraplength=wraplength,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(4, 10))
        points = self._preview_points(draft)
        if not points:
            points = ["暂无可确认的记忆点。"]
        points_container = Frame(content, bg=THEME_BG)
        points_container.pack(fill="x")

        def build_point_card(point_text: str, assigned_graph: str, note_text: str) -> None:
            card_ref: dict[str, Any] = {}

            def remove_point() -> None:
                block = card_ref.get("block")
                if block and block.winfo_exists():
                    block.destroy()
                if card_ref in self.pending_point_cards:
                    self.pending_point_cards.remove(card_ref)
                self._renumber_pending_point_cards()

            card_ref.update(
                self._make_memory_card(
                    points_container,
                    memory_label=f"记忆{len(self.pending_point_cards) + 1}",
                    time_text=time_text,
                    initial_text=point_text,
                    card_bg=THEME_CARD,
                    text_fg=THEME_TEXT,
                    height=3,
                    expanded_height=9,
                    padx=16,
                    editable=True,
                    note_text=note_text,
                    graph_value=assigned_graph,
                    graph_options=self._graph_options(draft),
                    allow_graph_add=True,
                    add_graph_callback=self._add_graph_from_prompt,
                    show_graph_selector=True,
                    remove_callback=remove_point,
                )
            )
            self.pending_point_cards.append(card_ref)
            self._renumber_pending_point_cards()

        for index, point in enumerate(points, start=1):
            assigned_graph = ""
            if index - 1 < len(graph_assignments):
                assigned_graph = str(graph_assignments[index - 1] or "").strip()
            if not assigned_graph:
                assigned_graph = str(draft.get("thread_name") or "未归属项目").strip() or "未归属项目"
            build_point_card(point, assigned_graph, "可直接修改这条记忆点，确认后按修改版写入。")

        add_row = Frame(content, bg=THEME_BG)
        add_row.pack(fill="x", padx=16, pady=(0, 6))

        def add_point() -> None:
            fallback_graph = self.pending_graph_vars[-1].get().strip() if self.pending_graph_vars else (str(draft.get("thread_name") or "未归属项目").strip() or "未归属项目")
            build_point_card("", fallback_graph, "可直接补进遗漏内容，确认后按修改版写入。")

        add_btn = self._textured_button(
            add_row,
            text="新增记忆点",
            crop_box=DRAFT_BUTTON_CROP,
            size=(138, 42),
            command=add_point,
            fg=PANEL_TEXT_GOLD,
            font=(PANEL_FONT_FAMILY, 11, "bold"),
        )
        add_btn.pack(side="right")
        raw_card = self._make_memory_card(
            content,
            memory_label="原文节选",
            time_text=time_text,
            initial_text=str(preview.get("raw_excerpt") or "暂无原文节选"),
            card_bg=THEME_CARD,
            text_fg=THEME_MUTED,
            height=6,
            expanded_height=14,
            padx=16,
            editable=True,
            note_text="这里仅用于核对与补充，不直接等于最终记忆点。",
        )
        self.pending_raw_editor = raw_card["editor"]
        row = Frame(content, bg=THEME_BG)
        row.pack(fill="x", padx=16, pady=(8, 14))
        confirm_btn = self._textured_button(
            row,
            text="确认写入",
            crop_box=MODE_BUTTON_ACTIVE_CROP,
            size=(138, 44),
            command=lambda sid=session_id: self._confirm_pending_draft(sid),
            fg=PANEL_TEXT_GOLD_BRIGHT,
            font=(PANEL_FONT_FAMILY, 11, "bold"),
            active=True,
        )
        confirm_btn.pack(side="left")
        reject_btn = self._textured_button(
            row,
            text="这段不要",
            crop_box=MODE_BUTTON_CROP,
            size=(122, 44),
            command=lambda sid=session_id: self._reject_pending_draft(sid),
            fg=PANEL_TEXT_GOLD,
            font=(PANEL_FONT_FAMILY, 11, "bold"),
        )
        reject_btn.pack(side="left", padx=8)
        close_btn = self._textured_button(
            row,
            text="关闭",
            crop_box=REFRESH_BUTTON_CROP,
            size=(116, 44),
            command=lambda: self._close_pending_prompt(snooze=True),
            fg=PANEL_TEXT_GOLD,
            font=(PANEL_FONT_FAMILY, 11, "bold"),
        )
        close_btn.pack(side="right")

    def _preview_points(self, draft: dict | None) -> list[str]:
        preview = draft.get("preview", {}) if isinstance(draft, dict) and isinstance(draft.get("preview"), dict) else {}
        points = preview.get("memory_points")
        if isinstance(points, list):
            normalized = [str(item).strip() for item in points if str(item).strip()]
            if normalized:
                return normalized
        fallback = [
            str(preview.get("title") or "").strip(),
            str(preview.get("fact_summary") or "").strip(),
            str(preview.get("meaning_summary") or "").strip(),
        ]
        return [item for item in fallback if item]

    def _draft_time_text(self, draft: dict | None) -> str:
        if not isinstance(draft, dict):
            return "未知时间"
        first_text = str(draft.get("first_message_at") or "").strip()
        last_text = str(draft.get("last_message_at") or "").strip()
        if not first_text and not last_text:
            return "未知时间"

        def _format(value: str) -> str:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=BEIJING_TZ)
                return parsed.astimezone(BEIJING_TZ).strftime("%m-%d %H:%M")
            except ValueError:
                return value[:16] if len(value) >= 16 else value

        if first_text and last_text:
            return f"{_format(first_text)} - {_format(last_text)}"
        return _format(first_text or last_text)

    def _project_name_from_card(self, card: dict | None) -> str:
        if not isinstance(card, dict):
            return "未归属项目"
        domain = card.get("domain_facets") if isinstance(card.get("domain_facets"), dict) else {}
        enterprise = domain.get("enterprise") if isinstance(domain, dict) and isinstance(domain.get("enterprise"), dict) else {}
        values = enterprise.get("项目")
        if isinstance(values, list):
            for item in values:
                clean = str(item or "").strip()
                if clean:
                    return clean
        clean = str(values or "").strip()
        return clean or "未归属项目"

    def _graph_options(self, draft: dict | None = None) -> list[str]:
        seen: list[str] = []

        def _add(value: str | None) -> None:
            clean = str(value or "").strip()
            if clean and clean not in seen:
                seen.append(clean)

        for item in self.state.get("available_graphs", []) or []:
            _add(item)
        if isinstance(draft, dict):
            for item in ((draft.get("preview") or {}) if isinstance(draft.get("preview"), dict) else {}).get("graph_assignments", []) or []:
                _add(item)
            _add(draft.get("thread_name"))
        try:
            cards = _request_json("GET", "/api/cards?limit=300")
            if isinstance(cards, list):
                for card in cards:
                    _add(self._project_name_from_card(card))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        _add("未归属项目")
        return seen

    def _remember_graph(self, value: str) -> None:
        clean = str(value or "").strip()
        if not clean:
            return
        graphs = list(self.state.get("available_graphs", []) or [])
        if clean not in graphs:
            graphs.append(clean)
            self.state["available_graphs"] = graphs
            self._write_state()

    def _sync_pending_graph_boxes(self, draft: dict | None = None) -> None:
        options = self._graph_options(draft)
        menu_options = options + (["＋ 新增图谱..."] if "＋ 新增图谱..." not in options else [])
        for box in self.pending_graph_boxes:
            try:
                box.configure(values=menu_options)
            except Exception:
                continue

    def _add_graph_from_prompt(self, target_var: StringVar | None = None) -> None:
        value = simpledialog.askstring("新增归属图谱", "输入新的图谱 / 项目名：", parent=self.pending_prompt or self.panel or self.root)
        clean = str(value or "").strip()
        if not clean:
            return
        self._remember_graph(clean)
        if target_var is not None:
            target_var.set(clean)
        self._sync_pending_graph_boxes(self._current_pending_draft())

    def _bind_graph_selector(self, graph_box: ttk.Combobox, graph_var: StringVar) -> None:
        previous = {"value": str(graph_var.get() or "").strip()}

        def on_select(_event=None) -> None:
            current = str(graph_var.get() or "").strip()
            if current == "＋ 新增图谱...":
                graph_var.set(previous["value"] or "未归属项目")
                self._add_graph_from_prompt(graph_var)
                previous["value"] = str(graph_var.get() or "").strip()
                return
            previous["value"] = current or previous["value"]

        graph_box.bind("<<ComboboxSelected>>", on_select, add="+")

    def _renumber_pending_point_cards(self) -> None:
        self.pending_point_editors = []
        self.pending_graph_vars = []
        self.pending_graph_boxes = []
        alive_cards: list[dict[str, Any]] = []
        for index, card in enumerate(self.pending_point_cards, start=1):
            block = card.get("block")
            if not block or not block.winfo_exists():
                continue
            label_widget = card.get("label_widget")
            if label_widget and label_widget.winfo_exists():
                label_widget.configure(text=f"记忆{index}")
            editor = card.get("editor")
            if editor and editor.winfo_exists():
                self.pending_point_editors.append(editor)
            graph_var = card.get("graph_var")
            if graph_var is not None:
                self.pending_graph_vars.append(graph_var)
            graph_box = card.get("graph_box")
            if graph_box is not None and graph_box.winfo_exists():
                self.pending_graph_boxes.append(graph_box)
            alive_cards.append(card)
        self.pending_point_cards = alive_cards

    def _make_memory_card(
        self,
        parent,
        *,
        memory_label: str,
        time_text: str,
        initial_text: str,
        card_bg: str,
        text_fg: str,
        height: int = 4,
        expanded_height: int = 10,
        padx: int = 10,
        editable: bool = False,
        note_text: str = "",
        graph_value: str = "",
        graph_options: list[str] | None = None,
        allow_graph_add: bool = False,
        add_graph_callback=None,
        show_graph_selector: bool = False,
        remove_callback=None,
    ) -> dict[str, Any]:
        block = Frame(parent, bg=card_bg, highlightbackground="#2d3a52", highlightthickness=1)
        block.configure(highlightbackground=THEME_EDGE, highlightthickness=1)
        block.pack(fill="x", padx=padx, pady=(0, 8))
        top = Frame(block, bg=card_bg)
        top.pack(fill="x", padx=12, pady=(10, 4))
        label_widget = Label(
            top,
            text=memory_label,
            bg=card_bg,
            fg=PANEL_TEXT_GOLD,
            font=(PANEL_FONT_FAMILY, 11, "bold"),
        )
        label_widget.pack(side="left")
        Label(
            top,
            text=time_text,
            bg=card_bg,
            fg=PANEL_TEXT_GOLD_MUTED,
            font=(PANEL_FONT_FAMILY, 9, "normal"),
        ).pack(side="right")
        graph_var: StringVar | None = None
        graph_box: ttk.Combobox | None = None
        if show_graph_selector:
            graph_wrap = Frame(top, bg=card_bg)
            graph_wrap.pack(side="left", padx=(10, 0))
            Label(
                graph_wrap,
                text="归属图谱",
                bg=card_bg,
                fg=PANEL_TEXT_GOLD_MUTED,
                font=(PANEL_FONT_FAMILY, 9, "normal"),
            ).pack(side="left", padx=(0, 6))
            graph_value = str(graph_value or "未归属项目").strip() or "未归属项目"
            if editable:
                graph_var = StringVar(value=graph_value)
                menu_values = list(graph_options or [graph_value])
                if "＋ 新增图谱..." not in menu_values:
                    menu_values.append("＋ 新增图谱...")
                graph_box = ttk.Combobox(
                    graph_wrap,
                    textvariable=graph_var,
                    values=menu_values,
                    state="readonly",
                    width=16,
                    style="Memlink.TCombobox",
                )
                graph_box.pack(side="left")
                self._bind_graph_selector(graph_box, graph_var)
                if allow_graph_add:
                    Button(
                        graph_wrap,
                        text="＋",
                        command=lambda var=graph_var: add_graph_callback(var) if add_graph_callback else None,
                        bg=card_bg,
                        fg=PANEL_TEXT_GOLD,
                        relief="flat",
                        activebackground=card_bg,
                        activeforeground=PANEL_TEXT_GOLD_BRIGHT,
                        borderwidth=0,
                        highlightthickness=0,
                        padx=6,
                        pady=0,
                    ).pack(side="left", padx=(4, 0))
            else:
                Label(
                    graph_wrap,
                    text=graph_value,
                    bg=THEME_CARD_ALT,
                    fg=PANEL_TEXT_GOLD,
                    font=(PANEL_FONT_FAMILY, 9, "normal"),
                    padx=8,
                    pady=1,
                ).pack(side="left")
        text_frame = Frame(block, bg=card_bg)
        text_frame.pack(fill="x", padx=12, pady=(2, 4))
        text_widget = Text(
            text_frame,
            height=height,
            wrap="word",
            bg=card_bg,
            fg=text_fg,
            insertbackground=PANEL_TEXT_GOLD_BRIGHT,
            relief="flat",
            font=(PANEL_FONT_FAMILY, 11),
            padx=2,
            pady=2,
            borderwidth=0,
            highlightthickness=0,
        )
        text_widget.insert("1.0", initial_text)
        if not editable:
            text_widget.configure(state="disabled")
        text_widget.pack(side="left", fill="x", expand=True)

        expanded = {"value": False}

        def toggle_expand() -> None:
            expanded["value"] = not expanded["value"]
            text_widget.configure(height=expanded_height if expanded["value"] else height)
            toggle_btn.configure(text="收起" if expanded["value"] else "展开全部")

        bottom = Frame(block, bg=card_bg)
        bottom.pack(fill="x", padx=12, pady=(0, 10))
        if note_text:
            Label(
                bottom,
                text=note_text,
                bg=card_bg,
                fg=PANEL_TEXT_GOLD_MUTED,
                font=(PANEL_FONT_FAMILY, 9, "normal"),
            ).pack(side="left")
        toggle_btn = Button(
            bottom,
            text="展开全部",
            command=toggle_expand,
            bg=card_bg,
            fg=PANEL_TEXT_GOLD,
            relief="flat",
            activebackground=card_bg,
            activeforeground=PANEL_TEXT_GOLD_BRIGHT,
            padx=8,
            pady=0,
            borderwidth=0,
            highlightthickness=0,
        )
        toggle_btn.pack(side="right")
        if editable and remove_callback is not None:
            Button(
                bottom,
                text="删除记忆",
                command=remove_callback,
                bg=card_bg,
                fg="#ff6b6b",
                relief="flat",
                activebackground=card_bg,
                activeforeground="#ff8d8d",
                padx=8,
                pady=0,
                borderwidth=0,
                highlightthickness=0,
            ).pack(side="right", padx=(0, 8))
        return {
            "block": block,
            "label_widget": label_widget,
            "editor": text_widget,
            "graph_var": graph_var,
            "graph_box": graph_box,
        }

    def _collect_pending_prompt_edits(self) -> dict[str, Any]:
        points = []
        for card in self.pending_point_cards:
            widget = card.get("editor")
            if not widget or not widget.winfo_exists():
                continue
            text = widget.get("1.0", "end").strip()
            if text:
                points.append(text)
        graph_assignments = []
        for card in self.pending_point_cards:
            var = card.get("graph_var")
            if var is None:
                continue
            text = str(var.get() or "").strip()
            if text:
                graph_assignments.append(text)
        raw_excerpt = self.pending_raw_editor.get("1.0", "end").strip() if self.pending_raw_editor else ""
        return {
            "memory_points": points,
            "graph_assignments": graph_assignments,
            "raw_excerpt": raw_excerpt,
        }

    def _confirm_pending_draft(self, session_id: str) -> None:
        try:
            _request_json(
                "POST",
                f"/api/session-auto-writer-drafts/{session_id}/confirm",
                self._collect_pending_prompt_edits(),
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            self.connected = False
            return
        self._close_pending_prompt()
        self._refresh_state()
        self._refresh_writer_status()

    def _reject_pending_draft(self, session_id: str) -> None:
        try:
            _request_json("POST", f"/api/session-auto-writer-drafts/{session_id}/reject")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            self.connected = False
            return
        self._close_pending_prompt()
        self._refresh_state()
        self._refresh_writer_status()

    def _maybe_prompt_pending_draft(self, *, force: bool = False) -> None:
        remote_draft = self._current_pending_draft()
        if not remote_draft:
            self.last_prompted_draft_id = ""
            self.snoozed_draft_id = ""
            if self.pending_prompt and self.pending_prompt.winfo_exists() and self.pending_prompt_is_empty:
                return
            self._close_pending_prompt()
            return
        draft_id = str(remote_draft.get("draft_id") or "")
        if not force and self.snoozed_draft_id and draft_id == self.snoozed_draft_id and not (self.pending_prompt and self.pending_prompt.winfo_exists()):
            return
        prompt_signature = self._pending_draft_signature(remote_draft)
        if self.pending_prompt and self.pending_prompt.winfo_exists():
            if draft_id == self.last_prompted_draft_id and prompt_signature == self.last_prompt_signature:
                return
        elif draft_id == self.last_prompted_draft_id and prompt_signature == self.last_prompt_signature:
            return
        self.last_prompted_draft_id = draft_id
        self.last_prompt_signature = prompt_signature
        draft = self._draft_with_local_prompt_edits(remote_draft)
        if not (self.pending_prompt and self.pending_prompt.winfo_exists()):
            self.pending_prompt = Toplevel(self.root)
            self.pending_prompt_is_empty = False
            self.pending_prompt._memlink_window_kind = "prompt"
            self.pending_prompt.title("Memlink Shrine · 残影草稿确认")
            self.pending_prompt.overrideredirect(True)
            self.pending_prompt.attributes("-topmost", False)
            self.pending_prompt.configure(bg=THEME_BG, bd=0, highlightthickness=0)
            self.pending_prompt.protocol("WM_DELETE_WINDOW", lambda: self._close_pending_prompt(snooze=True))
            self._bind_window_interactions(self.pending_prompt)
            self._position_pending_prompt(empty=False)
            self._queue_window_ownership_sync()
        else:
            for child in self.pending_prompt.winfo_children():
                child.destroy()
            self._position_pending_prompt(empty=False)

        self._render_pending_draft_prompt(draft)
        try:
            self.pending_prompt.deiconify()
            self.pending_prompt.lift()
            self.pending_prompt.focus_force()
        except Exception:
            pass

    def _write_state(self, mode: str | None = None) -> None:
        payload = {
            "mode": mode or self.state.get("mode", "off"),
            "confirm_before_write": bool(self.state.get("confirm_before_write", True)),
            "selected_models": self.state.get("selected_models", {}),
            "available_graphs": self.state.get("available_graphs", []),
        }
        try:
            self.state = _request_json("PUT", "/api/session-memory-gate", payload)
            self.connected = True
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            self.connected = False
        self._draw()
        if self.panel and self.panel.winfo_exists():
            self._fill_panel()

    def _toggle_fire(self) -> None:
        mode = self._clean_mode()
        self._write_state("passive" if mode == "off" else "off")

    def _draw(self) -> None:
        self.canvas.delete("all")
        mode = self._clean_mode()
        if not self._draw_icon(mode):
            inner_left, inner_top, inner_right, inner_bottom = (
                self._metric(17),
                self._metric(13),
                self._metric(61),
                self._metric(57),
            )
            self.canvas.create_oval(
                inner_left,
                inner_top,
                inner_right,
                inner_bottom,
                fill="#202938",
                outline="",
                width=0,
            )
            self._draw_torch(mode)

    def _draw_icon(self, mode: str) -> bool:
        key = "lit" if self.connected and self._codex_network_ok() and mode != "off" else "unlit"
        left, top, right, bottom = self._icon_box()
        image = self._scaled_icon(key, max(28, right - left), max(36, bottom - top))
        if not image:
            return False
        cx, cy = self._icon_center()
        self.canvas.create_image(cx, cy, image=image)
        if not self.connected:
            self.canvas.create_text(
                self._metric(46),
                self._metric(68),
                text="断",
                fill="#b5bfcd",
                font=("Microsoft YaHei UI", max(9, self._metric(10)), "bold"),
            )
        elif not self._codex_network_ok():
            self.canvas.create_text(
                self._metric(46),
                self._metric(68),
                text="网",
                fill="#c9b08c",
                font=("Microsoft YaHei UI", max(9, self._metric(10)), "bold"),
            )
        return True

    def _draw_torch(self, mode: str) -> None:
        handle = "#8b6a42" if mode != "off" and self.connected else "#6f7787"
        metal = "#c4d2e6" if mode != "off" and self.connected else "#8a95a6"
        self.canvas.create_line(
            self._metric(35),
            self._metric(44),
            self._metric(44),
            self._metric(25),
            fill=handle,
            width=max(3, self._metric(5)),
            capstyle="round",
        )
        self.canvas.create_line(
            self._metric(34),
            self._metric(45),
            self._metric(45),
            self._metric(25),
            fill="#2b3342",
            width=max(1, self._metric(1)),
        )
        self.canvas.create_line(
            self._metric(31),
            self._metric(28),
            self._metric(47),
            self._metric(28),
            fill=metal,
            width=max(2, self._metric(3)),
            capstyle="round",
        )
        if not self.connected:
            self.canvas.create_text(
                self._metric(40),
                self._metric(24),
                text="断",
                fill="#b5bfcd",
                font=("Microsoft YaHei UI", max(9, self._metric(10)), "bold"),
            )
            return
        if mode == "off":
            self.canvas.create_oval(
                self._metric(35),
                self._metric(19),
                self._metric(43),
                self._metric(27),
                fill="#182233",
                outline="#7b8798",
                width=max(1, self._metric(1)),
            )
            return

        flicker = [-2, 1, -1, 2][self.flame_phase]
        outer = "#ff9d22" if mode == "passive" else "#71ff9f"
        inner = "#fff4a3" if mode == "passive" else "#e8ffd3"
        self.canvas.create_polygon(
            self._metric(39),
            self._metric(12 + flicker),
            self._metric(29),
            self._metric(28),
            self._metric(38),
            self._metric(36),
            self._metric(49),
            self._metric(28),
            fill=outer,
            outline="#ffd37a" if mode == "passive" else "#b9ffcc",
            width=max(1, self._metric(1)),
        )
        self.canvas.create_polygon(
            self._metric(40),
            self._metric(17 - flicker),
            self._metric(34),
            self._metric(29),
            self._metric(40),
            self._metric(33),
            self._metric(45),
            self._metric(28),
            fill=inner,
            outline="",
        )

    def _hover_state(self, event) -> None:
        if self.resizing:
            self.canvas.configure(cursor="sizing")
            return
        if self._is_near_edge(event.x, event.y):
            self.canvas.configure(cursor="sizing")
        elif self._hit_action(event.x, event.y):
            self.canvas.configure(cursor="hand2")
        else:
            self.canvas.configure(cursor="arrow")

    def _leave_hover(self, _event=None) -> None:
        if not self.resizing:
            self.canvas.configure(cursor="arrow")

    def _wheel_scale(self, event) -> str:
        delta = getattr(event, "delta", 0)
        if delta == 0:
            return "break"
        factor = 1.08 if delta > 0 else 0.92
        center = (
            self.root.winfo_x() + self.root.winfo_width() / 2,
            self.root.winfo_y() + self.root.winfo_height() / 2,
        )
        self._apply_scale(self.scale * factor, center=center)
        self._remember_relative_position()
        self._draw()
        return "break"

    def _start_drag(self, event) -> None:
        self.dragging = False
        self.resizing = False
        self.moved = False
        self.start_x = event.x_root
        self.start_y = event.y_root
        self.root_x = self.root.winfo_x()
        self.root_y = self.root.winfo_y()
        if self._is_near_edge(event.x, event.y):
            self.resizing = True
            self.start_scale = self.scale
            self.resize_center_x = self.root.winfo_x() + self.root.winfo_width() / 2
            self.resize_center_y = self.root.winfo_y() + self.root.winfo_height() / 2
            self.resize_anchor = max(
                24.0,
                hypot(event.x_root - self.resize_center_x, event.y_root - self.resize_center_y),
            )
            self.canvas.configure(cursor="sizing")
            return
        self.dragging = True

    def _drag(self, event) -> None:
        if self.resizing:
            current_radius = max(
                24.0,
                hypot(event.x_root - self.resize_center_x, event.y_root - self.resize_center_y),
            )
            new_scale = self.start_scale * current_radius / max(self.resize_anchor, 1.0)
            if abs(new_scale - self.scale) > 0.01:
                self.moved = True
            self._apply_scale(new_scale, center=(self.resize_center_x, self.resize_center_y))
            return
        if not self.dragging:
            return
        dx = event.x_root - self.start_x
        dy = event.y_root - self.start_y
        if abs(dx) + abs(dy) > 4:
            self.moved = True
        self._set_geometry(self.root_x + dx, self.root_y + dy)
        self._remember_relative_position()

    def _release(self, event) -> None:
        was_resizing = self.resizing
        self.dragging = False
        self.resizing = False
        self._remember_relative_position()
        self._hover_state(event)
        if self.moved or was_resizing:
            return
        if time.time() - self.last_click_time < 0.18:
            return
        self.last_click_time = time.time()
        action = self._hit_action(event.x, event.y)
        if action == "fire":
            self._toggle_fire()
        elif action == "panel":
            self._toggle_panel()

    def _toggle_panel(self) -> None:
        if self.panel and self.panel.winfo_exists():
            self._close_panel()
            return
        self.panel = Toplevel(self.root)
        self.panel._memlink_window_kind = "panel"
        self.panel.title("Memlink Shrine")
        self.panel.overrideredirect(True)
        self.panel.attributes("-topmost", False)
        self.panel.configure(bg=THEME_BG, bd=0, highlightthickness=0)
        self.panel.protocol("WM_DELETE_WINDOW", self._close_panel)
        self._bind_window_interactions(self.panel)
        self._position_panel()
        self._queue_window_ownership_sync()
        self._fill_panel()

    def _close_panel(self) -> None:
        self._close_panel_dropdown_popup()
        if self.panel and self.panel.winfo_exists():
            self.panel.destroy()
        self.panel = None
        self.last_panel_signature = ""
        self._draw()

    def _clear_panel(self) -> None:
        self._close_panel_dropdown_popup()
        if not self.panel:
            return
        for child in self.panel.winfo_children():
            child.destroy()

    def _close_panel_dropdown_popup(self) -> None:
        if self.panel_dropdown_popup and self.panel_dropdown_popup.winfo_exists():
            self.panel_dropdown_popup.destroy()
        self.panel_dropdown_popup = None

    def _mode_label(self, mode: str) -> str:
        return {"off": "熄火", "passive": "被动写入", "ask": "被动写入", "auto": "自动写入"}.get(mode, "熄火")

    def _codex_network_ok(self) -> bool:
        if not isinstance(self.lifecycle_state, dict):
            return True
        if not self.lifecycle_state.get("codex_running", False):
            return True
        return bool(self.lifecycle_state.get("codex_network_ok", True))

    def _runtime_status_text(self, mode: str) -> str:
        if not self.connected:
            return "Memlink 未连接"
        if not self._codex_network_ok():
            return "Codex 未联网"
        return self._mode_label(mode)

    def _runtime_status_detail(self) -> str:
        detail = str((self.lifecycle_state or {}).get("detail") or "").strip()
        if detail:
            return detail
        if not self._codex_network_ok():
            return "Codex 未连接互联网，Memlink 已拉起但当前不可用。"
        return ""

    def _scale_ui_rect(self, rect: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
        sx = width / UI_BASE_WIDTH
        sy = height / UI_BASE_HEIGHT
        left = int(round(rect[0] * sx))
        top = int(round(rect[1] * sy))
        right = int(round(rect[2] * sx))
        bottom = int(round(rect[3] * sy))
        return left, top, right - left, bottom - top

    def _scale_ui_point(self, point: tuple[int, int], width: int, height: int) -> tuple[int, int]:
        sx = width / UI_BASE_WIDTH
        sy = height / UI_BASE_HEIGHT
        return int(round(point[0] * sx)), int(round(point[1] * sy))

    def _panel_role_combo(
        self,
        parent,
        *,
        key: str,
        role: dict | str,
        selected: str,
        crop_box: tuple[int, int, int, int],
        width: int = 432,
        height: int = 32,
        ui_scale: float = 1.0,
    ):
        if isinstance(role, dict):
            current = selected or role.get("current") or "未配置"
            candidates = role.get("candidates") or [current]
        else:
            current = selected or str(role or "未配置")
            candidates = [current]

        wrap = Frame(parent, bg=THEME_BG, width=width, height=height, highlightthickness=0, bd=0)
        wrap.pack_propagate(False)
        wrap._memlink_interactive = True
        value = StringVar(value=current)
        text_font_size = max(9, int(round(13 * ui_scale)))
        shadow_font_size = max(9, int(round(13 * ui_scale)))
        arrow_w = max(10, int(round(12 * ui_scale)))
        arrow_h = max(8, int(round(10 * ui_scale)))

        def refresh_menu_colors() -> None:
            return

        def save_choice(choice: str) -> None:
            value.set(choice)
            self.state.setdefault("selected_models", {})[key] = choice
            self._write_state()
            refresh_display()
            refresh_menu_colors()

        field_canvas = Canvas(wrap, width=width, height=height, bg=THEME_BG, highlightthickness=0, bd=0)
        field_canvas._memlink_interactive = True
        field_canvas.place(x=0, y=0, width=width, height=height)

        field_bg = self._scaled_panel_field_background(width, height)
        if field_bg is not None:
            field_canvas.create_image(0, 0, image=field_bg, anchor="nw")
            wrap._field_bg = field_bg

        shadow_id = field_canvas.create_text(
            13,
            height // 2 + 1,
            text=value.get(),
            fill="#23180f",
            font=(PANEL_FONT_FAMILY, shadow_font_size, "bold"),
            anchor="w",
        )
        text_id = field_canvas.create_text(
            12,
            height // 2,
            text=value.get(),
            fill=PANEL_TEXT_GOLD_BRIGHT,
            font=(PANEL_FONT_FAMILY, text_font_size, "bold"),
            anchor="w",
        )

        arrow_image = self._scaled_dropdown_arrow(arrow_w, arrow_h)
        if arrow_image is not None:
            arrow_label = field_canvas.create_image(width - max(12, int(round(16 * ui_scale))), height // 2, image=arrow_image)
            wrap._arrow_image = arrow_image
            wrap._arrow_label = arrow_label
        else:
            arrow_label = field_canvas.create_text(width - max(12, int(round(16 * ui_scale))), height // 2, text="v", fill=PANEL_TEXT_GOLD_BRIGHT, font=(PANEL_FONT_FAMILY, max(9, int(round(12 * ui_scale))), "bold"))
            wrap._arrow_label = arrow_label

        def refresh_display() -> None:
            current_value = value.get()
            field_canvas.itemconfigure(text_id, text=current_value)
            field_canvas.itemconfigure(shadow_id, text=current_value)

        def close_popup(_event=None) -> None:
            self._close_panel_dropdown_popup()

        def open_menu(_event=None) -> None:
            if self.panel_dropdown_popup and self.panel_dropdown_popup.winfo_exists():
                self._close_panel_dropdown_popup()
                return
            popup = Toplevel(wrap)
            popup.overrideredirect(True)
            popup.attributes("-topmost", False)
            popup.configure(bg=THEME_BG, bd=0, highlightthickness=0)
            option_h = max(28, int(round(34 * ui_scale)))
            pad = max(4, int(round(6 * ui_scale)))
            popup_h = pad * 2 + len(candidates) * option_h
            popup_x = wrap.winfo_rootx()
            popup_y_below = wrap.winfo_rooty() + height + 4
            popup_y_above = wrap.winfo_rooty() - popup_h - 4
            screen_h = wrap.winfo_screenheight()
            panel_top = self.panel.winfo_rooty() if self.panel and self.panel.winfo_exists() else 0
            panel_bottom = (self.panel.winfo_rooty() + self.panel.winfo_height()) if self.panel and self.panel.winfo_exists() else screen_h
            available_above = max(0, wrap.winfo_rooty() - panel_top - 8)
            available_below = max(0, panel_bottom - popup_y_below - 8)
            if available_above >= min(popup_h, 140):
                popup_y = max(4, popup_y_above)
            elif popup_y_below + popup_h > screen_h - 8 and popup_y_above > 4:
                popup_y = popup_y_above
            else:
                popup_y = popup_y_below
            popup.geometry(f"{width}x{popup_h}+{popup_x}+{popup_y}")
            popup_canvas = Canvas(popup, width=width, height=popup_h, bg=THEME_BG, highlightthickness=0, bd=0)
            popup_canvas.pack(fill="both", expand=True)
            popup_bg = self._scaled_panel_background(width, popup_h)
            if popup_bg is not None:
                popup_canvas.create_image(0, 0, image=popup_bg, anchor="nw")
                popup._bg_image = popup_bg

            for idx, candidate in enumerate(candidates):
                row_y = pad + idx * option_h
                row_bg = self._scaled_panel_field_background(width - 12, option_h - 4)
                if row_bg is not None:
                    popup_canvas.create_image(6, row_y + 2, image=row_bg, anchor="nw")
                    setattr(popup, f"_row_bg_{idx}", row_bg)
                selected_now = str(candidate) == str(value.get())
                tag = f"popup_option_{idx}"
                popup_canvas.create_text(
                    max(14, int(round(18 * ui_scale))),
                    row_y + option_h / 2 + 1,
                    text=str(candidate),
                    font=(PANEL_FONT_FAMILY, max(9, int(round(12 * ui_scale))), "bold"),
                    fill="#241912",
                    anchor="w",
                    tags=(tag,),
                )
                popup_canvas.create_text(
                    max(13, int(round(17 * ui_scale))),
                    row_y + option_h / 2,
                    text=str(candidate),
                    font=(PANEL_FONT_FAMILY, max(9, int(round(12 * ui_scale))), "bold"),
                    fill=PANEL_TEXT_GOLD_BRIGHT if selected_now else PANEL_TEXT_GOLD,
                    anchor="w",
                    tags=(tag,),
                )
                popup_canvas.create_rectangle(6, row_y + 2, width - 6, row_y + option_h - 2, outline="", fill="", tags=(tag,))
                popup_canvas.tag_bind(tag, "<Button-1>", lambda _e, choice=str(candidate): (save_choice(choice), close_popup()))

            popup.bind("<FocusOut>", close_popup)
            popup.bind("<Escape>", close_popup)
            popup.focus_force()
            self.panel_dropdown_popup = popup

        refresh_display()
        field_canvas.bind("<Button-1>", open_menu)
        wrap.bind("<Button-1>", open_menu)

        wrap._value = value
        wrap._field_canvas = field_canvas
        wrap._open_menu = open_menu
        return wrap

    def _textured_button(
        self,
        parent,
        *,
        text: str,
        crop_box: tuple[int, int, int, int],
        size: tuple[int, int],
        command,
        fg: str = THEME_GOLD,
        font: tuple[str, int, str] = ("Microsoft YaHei UI", 10, "bold"),
        active: bool = False,
    ):
        image = self._render_widget_skin(
            crop_box,
            size[0],
            size[1],
            cover_rect=(0.04, 0.04, 0.96, 0.99),
            cover_fill=(112, 83, 47, 255) if active else (40, 36, 31, 255),
        )
        button = Button(
            parent,
            text=text,
            command=command,
            image=image,
            compound="center",
            bg=THEME_BG,
            fg=fg,
            activebackground=THEME_BG,
            activeforeground=THEME_ACTIVE_TEXT,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=0,
            pady=0,
            font=font,
            cursor="hand2",
        )
        button.image = image
        return button

    def _textured_label(
        self,
        parent,
        *,
        text: str,
        crop_box: tuple[int, int, int, int],
        size: tuple[int, int],
        fg: str = THEME_PARCHMENT_TEXT,
        font: tuple[str, int, str] = ("Microsoft YaHei UI", 10, "normal"),
        anchor: str = "w",
        padx: int = 10,
    ):
        image = self._render_widget_skin(
            crop_box,
            size[0],
            size[1],
            cover_rect=(0.02, 0.10, 0.96, 0.90),
            cover_fill=(222, 206, 175, 242),
        )
        wrap = Frame(parent, bg=THEME_BG, width=size[0], height=size[1], highlightthickness=0, bd=0)
        wrap.pack_propagate(False)
        bg_label = Label(wrap, image=image, borderwidth=0, highlightthickness=0, bg=THEME_BG)
        bg_label.image = image
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
        text_label = Label(
            wrap,
            text=text,
            bg="#d8c7a4",
            fg=fg,
            font=font,
            anchor=anchor,
            padx=padx,
            borderwidth=0,
            highlightthickness=0,
        )
        text_label.place(x=0, y=0, relwidth=1, relheight=1)
        wrap._bg_label = bg_label
        wrap._text_label = text_label
        return wrap

    def _fill_panel(self) -> None:
        if not self.panel or not self.panel.winfo_exists():
            return
        self.panel.update_idletasks()
        self.last_panel_signature = self._panel_signature()
        self._close_panel_dropdown_popup()
        old_children = list(self.panel.winfo_children())
        panel_bg = THEME_BG
        panel_text = PANEL_TEXT_GOLD
        panel_muted = PANEL_TEXT_GOLD_MUTED
        panel_active = PANEL_TEXT_GOLD_BRIGHT
        panel_inactive = PANEL_TEXT_GOLD_MUTED
        base_width, base_height = 500, 920
        remembered = getattr(self.panel, "_memlink_bounds", {}) if self.panel else {}
        actual_width = max(1, int(self.panel.winfo_width() or 0))
        actual_height = max(1, int(self.panel.winfo_height() or 0))
        width = max(int(remembered.get("width") or 0), actual_width, min(base_width, actual_width))
        height = max(int(remembered.get("height") or 0), actual_height, min(base_height, actual_height))
        width, height = self._clamp_window_size(self.panel, width, height)
        scale_x = width / base_width
        scale_y = height / base_height
        ui_scale = min(scale_x, scale_y)

        def mx(value: float) -> int:
            return max(1, int(round(value * scale_x)))

        def my(value: float) -> int:
            return max(1, int(round(value * scale_y)))

        def mf(value: int, minimum: int = 8) -> int:
            return max(minimum, int(round(value * ui_scale)))

        self.panel.configure(bg=panel_bg)
        shell = Frame(self.panel, bg=panel_bg, highlightthickness=0, bd=0)
        canvas = Canvas(shell, width=width, height=height, bg=panel_bg, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        canvas.configure(width=width, height=height)

        mode = self._clean_mode()
        status_text = self._runtime_status_text(mode)
        y = my(18)

        self._canvas_icon_button(
            canvas,
            width - mx(62),
            my(12),
            text="—",
            command=self._close_panel,
            size=max(16, mx(18)),
            fill=panel_muted,
            font=(PANEL_FONT_FAMILY, mf(12), "bold"),
        )
        self._canvas_icon_button(
            canvas,
            width - mx(36),
            my(12),
            text="×",
            command=self._close_panel,
            size=max(16, mx(18)),
            fill=panel_active,
            font=(PANEL_FONT_FAMILY, mf(11), "bold"),
        )

        self._panel_text(canvas, mx(16), y, text="Memlink Shrine", font=(PANEL_FONT_FAMILY, mf(22, 12), "bold"), fill=panel_text)
        y += my(46)
        self._panel_text(canvas, mx(16), y, text=status_text, font=(PANEL_FONT_FAMILY, mf(14, 10), "bold"), fill=panel_muted)
        y += my(40)
        detail_text = self._runtime_status_detail()
        if detail_text:
            self._panel_text(
                canvas,
                mx(16),
                y,
                text=detail_text,
                font=(PANEL_DETAIL_FONT_FAMILY, mf(11, 10), "normal"),
                fill=panel_muted,
                width=max(220, width - mx(60)),
            )
            y += my(42)

        mode_help = {
            "off": "熄火：只暂停写入；读取层仍在线，可随时调取记忆。",
            "auto": "自动写入：按半小时、轮数、字符量或主动口令命中后直接落库，并给出非打断式提示。",
            "passive": "被动写入：按半小时、轮数、字符量或主动口令命中后先弹草稿，由你确认再写入。",
        }

        x = mx(16)
        for value, label in (("off", "熄火"), ("auto", "自动写入"), ("passive", "被动写入")):
            text_w, _ = self._canvas_action_text(
                canvas,
                x,
                y,
                text=label,
                command=lambda current=value: self._write_state(current),
                fill=panel_inactive if mode != value else panel_active,
                active_fill=panel_active if mode == value else None,
                font=(PANEL_FONT_FAMILY, mf(12, 10), "bold"),
            )
            x += text_w + mx(32)
        y += my(42)

        confirm_var = BooleanVar(value=bool(self.state.get("confirm_before_write", True)))

        def save_confirm() -> None:
            self.state["confirm_before_write"] = confirm_var.get()
            self._write_state()

        toggle_h = self._canvas_toggle(
            canvas,
            mx(16),
            y,
            text="写入前展示残影草稿，避免闲聊污染",
            value=confirm_var.get(),
            command=save_confirm,
            fill=panel_muted,
            font=(PANEL_FONT_FAMILY, mf(12, 10), "bold"),
        )
        y += toggle_h + my(26)

        text_w, text_h = self._canvas_action_text(
            canvas,
            mx(16),
            y,
            text="打开草稿箱",
            command=self._open_pending_prompt_from_panel,
            fill=panel_text,
            font=(PANEL_FONT_FAMILY, mf(12, 10), "bold"),
        )
        self._panel_text(
            canvas,
            mx(16) + text_w + mx(24),
            y,
            text=f"当前待确认：{len(self._pending_drafts())}",
            font=(PANEL_FONT_FAMILY, mf(12, 10), "bold"),
            fill=panel_muted,
        )
        y += max(text_h, my(18)) + my(34)

        roles = self.state.get("model_roles", {}) or {}
        selected = self.state.get("selected_models", {}) or {}

        def role_block(key: str, fallback_label: str) -> None:
            nonlocal y
            role = roles.get(key, {}) if isinstance(roles.get(key), dict) else {}
            label = str(role.get("label") or fallback_label)
            current = selected.get(key, "") or str(role.get("current") or "未配置")
            candidates = role.get("candidates") or [current]
            position = str(role.get("position") or "未定义")
            responsibility = str(role.get("responsibility") or "未定义")

            self._panel_text(canvas, mx(16), y, text=label, font=(PANEL_FONT_FAMILY, mf(14, 10), "bold"), fill=panel_text)
            y += my(34)
            combo = self._panel_role_combo(
                canvas,
                key=key,
                role=role,
                selected=current,
                crop_box=WITNESS_COMBO_RECT,
                width=max(240, width - mx(74)),
                height=max(28, my(32)),
                ui_scale=ui_scale,
            )
            canvas.create_window(mx(16), y, anchor="nw", window=combo)
            y += my(46)
            self._panel_text(
                canvas,
                mx(16),
                y,
                text=f"位置：{position}",
                font=(PANEL_DETAIL_FONT_FAMILY, mf(12, 10), "normal"),
                fill=panel_muted,
                width=max(220, width - mx(70)),
            )
            y += my(32)
            self._panel_text(
                canvas,
                mx(16),
                y,
                text=f"职责：{responsibility}",
                font=(PANEL_DETAIL_FONT_FAMILY, mf(12, 10), "normal"),
                fill=panel_muted,
                width=max(220, width - mx(70)),
            )
            y += my(78)

        role_block("witness_model", "知情者模型 / 协作模型")
        role_block("admin_model", "管理员模型 / 治理馆员")
        role_block("embedding_model", "底层召回 / 联想引擎")
        role_block("engine_embedding_model", "联想引擎嵌入模型")

        self._canvas_action_text(
            canvas,
            max(mx(16), width - mx(140)),
            y,
            text="刷新状态",
            command=lambda: (self._refresh_state(), self._refresh_panel_if_needed(force=True)),
            fill=panel_text,
            font=(PANEL_FONT_FAMILY, mf(12, 10), "bold"),
        )
        y += my(40)
        content_height = max(height, y + my(16))
        canvas.configure(scrollregion=(0, 0, width, content_height))

        bg_image = self._scaled_panel_background(width, content_height)
        if bg_image is not None:
            bg_id = canvas.create_image(0, 0, image=bg_image, anchor="nw")
            canvas._bg_image = bg_image
            canvas.tag_lower(bg_id)

        track_x0 = width - mx(10)
        track_x1 = width - mx(4)
        track = canvas.create_rectangle(track_x0, 0, track_x1, height, outline="", fill="#1f1711", tags=("scrollbar_track",))
        thumb = canvas.create_rectangle(track_x0 + 1, 0, track_x1 - 1, max(my(64), 40), outline="#5a442e", fill="#b39063", tags=("scrollbar_thumb",))
        canvas.tag_raise(track)
        canvas.tag_raise(thumb)
        scroll_state = {"dragging": False, "offset": 0.0}

        def _update_scrollbar(first, last):
            try:
                first_f = float(first)
                last_f = float(last)
            except (TypeError, ValueError):
                return
            travel = max(1, height - 8)
            thumb_top = 2 + int(round(first_f * travel))
            thumb_bottom = 2 + int(round(last_f * travel))
            thumb_bottom = max(thumb_top + 28, thumb_bottom)
            thumb_bottom = min(height - 2, thumb_bottom)
            canvas.coords(track, track_x0, 0, track_x1, height)
            canvas.coords(thumb, track_x0 + 1, thumb_top, track_x1 - 1, thumb_bottom)

        def _yscroll(first, last):
            _update_scrollbar(first, last)

        canvas.configure(yscrollcommand=_yscroll)
        _update_scrollbar(*canvas.yview())

        def _scroll_wheel(event):
            delta = getattr(event, "delta", 0)
            if delta:
                canvas.yview_scroll(-1 * int(delta / 120), "units")
                return "break"
            return "break"

        def _track_click(event):
            current = canvas.coords(thumb)
            thumb_h = max(28, current[3] - current[1]) if current else 28
            target = max(0, min(height - thumb_h - 2, event.y - thumb_h / 2))
            fraction = target / max(1, height - thumb_h - 4)
            canvas.yview_moveto(fraction)
            _update_scrollbar(*canvas.yview())
            return "break"

        def _thumb_press(event):
            current = canvas.coords(thumb)
            scroll_state["dragging"] = True
            scroll_state["offset"] = event.y - (current[1] if current else 0)
            return "break"

        def _thumb_drag(event):
            if not scroll_state["dragging"]:
                return "break"
            current = canvas.coords(thumb)
            if not current:
                return "break"
            thumb_h = max(28, current[3] - current[1])
            target = max(2, min(height - thumb_h - 2, event.y - scroll_state["offset"]))
            fraction = (target - 2) / max(1, height - thumb_h - 4)
            canvas.yview_moveto(fraction)
            _update_scrollbar(*canvas.yview())
            return "break"

        def _thumb_release(_event):
            scroll_state["dragging"] = False
            return "break"

        canvas.bind("<MouseWheel>", _scroll_wheel)
        canvas.tag_bind(track, "<Button-1>", _track_click)
        canvas.tag_bind(thumb, "<ButtonPress-1>", _thumb_press)
        canvas.tag_bind(thumb, "<B1-Motion>", _thumb_drag)
        canvas.tag_bind(thumb, "<ButtonRelease-1>", _thumb_release)
        for child in old_children:
            try:
                child.destroy()
            except Exception:
                pass
        shell.pack(fill="both", expand=True)

    def _role_block(self, parent, key: str, role: dict | str, selected: str) -> None:
        if not parent:
            return
        if isinstance(role, dict):
            label = role.get("label") or key
            current = selected or role.get("current") or "未配置"
            candidates = role.get("candidates") or [current]
            position = role.get("position") or "未定义"
            responsibility = role.get("responsibility") or "未定义"
        else:
            label = key
            current = selected or str(role or "未配置")
            candidates = [current]
            position = "未定义"
            responsibility = "未定义"

        box = Frame(parent, bg=THEME_CARD, highlightbackground=THEME_EDGE, highlightthickness=1)
        box.pack(fill="x", padx=16, pady=5)
        Label(box, text=label, bg=THEME_CARD, fg=THEME_GOLD, font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 2))
        value = StringVar(value=current)

        def save_choice(_event=None) -> None:
            self.state.setdefault("selected_models", {})[key] = value.get()
            self._write_state()

        combo_wrap = Frame(box, bg=THEME_CARD, height=38)
        combo_wrap.pack(fill="x", padx=10, pady=3)
        combo_wrap.pack_propagate(False)
        combo_crop_map = {
            "witness_model": WITNESS_COMBO_RECT,
            "admin_model": ADMIN_COMBO_RECT,
            "embedding_model": VCP_COMBO_RECT,
            "engine_embedding_model": VCP_COMBO_RECT,
        }
        combo_bg = self._render_widget_skin(
            combo_crop_map.get(key, WITNESS_COMBO_RECT),
            410,
            38,
            cover_rect=(0.02, 0.16, 0.92, 0.84),
            cover_fill=(42, 39, 36, 210),
        )
        if combo_bg is not None:
            combo_back = Label(combo_wrap, image=combo_bg, borderwidth=0, highlightthickness=0)
            combo_back.image = combo_bg
            combo_back.place(x=0, y=0, relwidth=1, relheight=1)
        combo = ttk.Combobox(combo_wrap, textvariable=value, values=candidates, state="readonly", style="Memlink.TCombobox")
        combo.place(x=6, y=3, relwidth=1.0, width=-12, height=32)
        combo.bind("<<ComboboxSelected>>", save_choice)
        Label(
            box,
            text=f"位置：{position}",
            bg=THEME_CARD,
            fg=THEME_MUTED,
            wraplength=410,
            justify="left",
            font=(PANEL_DETAIL_FONT_FAMILY, 11, "normal"),
        ).pack(anchor="w", padx=10, pady=(2, 0))
        Label(
            box,
            text=f"职责：{responsibility}",
            bg=THEME_CARD,
            fg=THEME_MUTED,
            wraplength=410,
            justify="left",
            font=(PANEL_DETAIL_FONT_FAMILY, 11, "normal"),
        ).pack(anchor="w", padx=10, pady=(0, 8))

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    try:
        MemlinkShrineOverlay().run()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



