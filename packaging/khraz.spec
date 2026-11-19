# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: сборка ХРАЗа в папку dist\KHRAZ (onedir — QtWebEngine в один файл не собирается).
# Запуск: build_installer.bat (из папки packaging).
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, collect_submodules

HERE = os.path.abspath(os.path.dirname(SPEC))
APP = os.path.abspath(os.path.join(HERE, ".."))

datas = [
    (os.path.join(APP, "assets"), "assets"),
    (os.path.join(APP, "KHRAZ_PERSONA.md"), "."),
    (os.path.join(APP, "docs"), "docs"),
]

binaries, hidden = [], []
for pkg in ("vosk", "onnxruntime", "piper", "_sounddevice_data", "docx", "openpyxl", "qrcode", "pypdf",
            "keyring", "pydantic", "pycaw", "comtypes", "rapidfuzz"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hidden += h
    except Exception as e:                          # пакет не установлен — пропускаем (например, pycaw вне Windows)
        print(f"[khraz.spec] пропущен {pkg}: {e}")
# MCP SDK: всё, кроме консольной утилиты mcp.cli (ей нужен typer, ХРАЗу — нет)
hidden += collect_submodules("mcp", filter=lambda n: not n.startswith("mcp.cli"))
datas += collect_data_files("mcp")
hidden += collect_submodules("tools") + ["keyring.backends.Windows", "win32ctypes", "mcp_hub", "models_dl",
                                         "startup", "router", "errors", "chats", "khraz_secrets", "khraz_mcp_adapter",
                                         "feedback", "kb", "habits", "watcher", "morning", "sfx", "hotkey"]

a = Analysis(
    [os.path.join(APP, "main.py")],
    pathex=[APP],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["torch", "torchaudio", "tkinter", "matplotlib", "IPython", "pytest"],   # silero (torch) — только из исходников
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="KHRAZ",
    icon=os.path.join(APP, "assets", "img", "khraz.ico"),
    console=False,
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="KHRAZ")
