"""Произвольный PowerShell — по умолчанию выключен (allow_shell). Показывается модели только при явной просьбе,
выполняется только после подтверждения кнопкой (брайн не принимает голосовое «да» для этого инструмента),
весь текст команды виден в карточке и пишется в журнал."""
import subprocess
import sys

from . import REGISTRY, ToolError, tool

IS_WIN = sys.platform == "win32"
SCHEMA = {"type": "object", "properties": {
    "script": {"type": "string", "maxLength": 4000, "description": "текст PowerShell; одна задача, без интерактива"}},
    "required": ["script"], "additionalProperties": False}


@tool("run_powershell", "Выполнить PowerShell на компьютере пользователя (только по явной просьбе; нужно подтверждение).",
      SCHEMA, risk="change",
      explicit=r"(powershell|пауэршелл|выполни команд|команд\w* строк|терминал|консол)",
      summary=lambda a: "Выполнить PowerShell:\n" + a["script"])
def run_powershell(ctx, script):
    if not IS_WIN:
        raise ToolError("PowerShell доступен только в Windows")
    ctx.ui_action("Выполняю PowerShell")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                           creationflags=0x08000000)
    except subprocess.TimeoutExpired:
        raise ToolError("команда не завершилась за 60 секунд и была остановлена")
    out = ((r.stdout or "").strip() + ("\n" + r.stderr.strip() if r.stderr.strip() else "")).strip()
    return f"код {r.returncode}\n{out[:3000]}" if out else f"код {r.returncode}, вывода нет"


REGISTRY["run_powershell"].when = lambda cfg: bool(cfg.get("allow_shell"))
