from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from tkinter import Tk, messagebox


APP_NAME = "Memlink Shrine Quick Start"
EXE_NAME = "MemlinkShrineQuickStart.exe"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _message(title: str, body: str, *, error: bool = False) -> None:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if error:
            messagebox.showerror(title, body, parent=root)
        else:
            messagebox.showinfo(title, body, parent=root)
    finally:
        root.destroy()


def _ask_yes_no(title: str, body: str) -> bool:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return bool(messagebox.askyesno(title, body, parent=root))
    finally:
        root.destroy()


def default_install_dir() -> Path:
    base = os.getenv("LOCALAPPDATA")
    if base:
        return Path(base) / "Programs" / "MemlinkShrineQuickStart"
    return Path.home() / "AppData" / "Local" / "Programs" / "MemlinkShrineQuickStart"


def payload_zip_path() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")) / "payload" / "MemlinkShrineQuickStart_payload.zip"
    return Path(__file__).resolve().parent / "installer_payload" / "MemlinkShrineQuickStart_payload.zip"


def _common_zip_root(names: list[str]) -> str:
    first_parts = []
    for name in names:
        clean = name.replace("\\", "/").strip("/")
        if not clean:
            continue
        first_parts.append(clean.split("/", 1)[0])
    if not first_parts:
        return ""
    first = first_parts[0]
    return first if all(part == first for part in first_parts) else ""


def extract_payload(zip_path: Path, install_dir: Path) -> None:
    if not zip_path.exists():
        raise FileNotFoundError(f"Missing installer payload: {zip_path}")
    install_dir.mkdir(parents=True, exist_ok=True)
    install_root = install_dir.resolve()

    with zipfile.ZipFile(zip_path) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        root = _common_zip_root([info.filename for info in infos])
        for info in archive.infolist():
            raw_name = info.filename.replace("\\", "/").strip("/")
            if not raw_name:
                continue
            if root and raw_name == root:
                continue
            relative = raw_name
            if root and raw_name.startswith(root + "/"):
                relative = raw_name[len(root) + 1 :]
            if not relative:
                continue
            target = (install_root / relative).resolve()
            if not str(target).lower().startswith(str(install_root).lower()):
                raise RuntimeError(f"Refusing unsafe archive path: {raw_name}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def _powershell_quote(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def create_shortcut(shortcut_path: Path, target_exe: Path, working_dir: Path) -> None:
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    script = "\n".join(
        [
            "$shell = New-Object -ComObject WScript.Shell",
            f"$shortcut = $shell.CreateShortcut({_powershell_quote(shortcut_path)})",
            f"$shortcut.TargetPath = {_powershell_quote(target_exe)}",
            f"$shortcut.WorkingDirectory = {_powershell_quote(working_dir)}",
            f"$shortcut.IconLocation = {_powershell_quote(str(target_exe) + ',0')}",
            "$shortcut.Save()",
        ]
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        creationflags=CREATE_NO_WINDOW,
    )


def create_shortcuts(install_dir: Path) -> None:
    target = install_dir / EXE_NAME
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    create_shortcut(desktop / f"{APP_NAME}.lnk", target, install_dir)
    start_menu = Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    create_shortcut(start_menu / f"{APP_NAME}.lnk", target, install_dir)


def launch_app(install_dir: Path) -> None:
    target = install_dir / EXE_NAME
    subprocess.Popen([str(target)], cwd=str(install_dir), creationflags=CREATE_NO_WINDOW)


def install(install_dir: Path, *, quiet: bool, launch: bool, shortcuts: bool) -> None:
    if not quiet:
        ok = _ask_yes_no(APP_NAME, f"将安装到：\n{install_dir}\n\n继续安装吗？")
        if not ok:
            return
    extract_payload(payload_zip_path(), install_dir)
    target = install_dir / EXE_NAME
    if not target.exists():
        raise FileNotFoundError(f"Install finished but entry executable was not found: {target}")
    if shortcuts:
        create_shortcuts(install_dir)
    if launch:
        launch_app(install_dir)
    if not quiet:
        _message(APP_NAME, "安装完成。桌面已经创建 Memlink Shrine Quick Start 快捷方式。")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-dir", default="")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--no-shortcuts", action="store_true")
    args = parser.parse_args()

    install_dir = Path(args.install_dir).resolve() if args.install_dir else default_install_dir()
    try:
        install(install_dir, quiet=args.quiet, launch=not args.no_launch, shortcuts=not args.no_shortcuts)
        return 0
    except Exception as exc:
        if args.quiet:
            print(f"{APP_NAME} install failed: {exc}", file=sys.stderr)
        else:
            _message(APP_NAME, f"安装失败：\n{exc}", error=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
