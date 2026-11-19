"""Чтение логов (только чтение): локальные файлы и сервер по ssh. Модель выбирает ИМЯ источника из config["log_sources"],
путь и хост она не задаёт. ssh — по ключу (BatchMode), команда фиксированная: tail -n N -- <путь из настроек>.
Секреты в выводе (токены, пароли, ключи) маскируются.

config.json:
  "log_sources": [
    {"name": "app", "type": "file", "path": "C:/Projects/myproject/logs/app.log"},
    {"name": "prod", "type": "ssh", "host": "deploy@1.2.3.4", "port": 22,
     "path": "/var/log/app.log"}]"""
import re
import shlex
import subprocess
import sys

from . import ToolError, tool

HOST_RE = re.compile(r"[A-Za-z0-9._-]+@[A-Za-z0-9._-]+")
SECRET_RE = re.compile(r"(?i)((?:password|passwd|pwd|secret|token|api[_-]?key|authorization|bearer)"
                       r"[\"']?\s*[:=]?\s*[\"']?)([^\s\"',;]{6,})")


def _sources(cfg):
    return [s for s in (cfg.get("log_sources") or []) if isinstance(s, dict) and s.get("name") and s.get("path")]


def _schema(cfg):
    names = [s["name"] for s in _sources(cfg)] or ["—"]
    return {"type": "object", "properties": {
        "source": {"type": "string", "enum": names, "description": "источник лога из настроек"},
        "lines": {"type": "integer", "minimum": 1, "maximum": 400, "description": "сколько последних строк (по умолчанию 80)"},
        "grep": {"type": "string", "maxLength": 80, "description": "оставить только строки с этим текстом (например ERROR)"}},
        "required": ["source"], "additionalProperties": False}


def mask(text):
    return SECRET_RE.sub(lambda m: m.group(1) + "***", text)


def _tail_file(path, n):
    import os
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        raise ToolError(f"файл не найден: {path}")
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 512 * 1024))
        data = f.read().decode("utf-8", errors="replace")
    return data.splitlines()[-n:]


def _tail_ssh(src, n):
    host = str(src.get("host", ""))
    if not HOST_RE.fullmatch(host):
        raise ToolError("в настройках источника неверный host (нужно user@host)")
    port = int(src.get("port") or 22)
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=yes",
            "-p", str(port), host, f"tail -n {int(n)} -- {shlex.quote(str(src['path']))}"]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25,
                           creationflags=0x08000000 if sys.platform == "win32" else 0)
    except FileNotFoundError:
        raise ToolError("не найден ssh (установите OpenSSH-клиент)")
    except subprocess.TimeoutExpired:
        raise ToolError("сервер не ответил за 25 секунд")
    if r.returncode != 0:
        raise ToolError("ssh: " + ((r.stderr or "").strip()[:300] or f"код {r.returncode}"))
    return r.stdout.splitlines()


@tool("read_log", "Прочитать последние строки лога (приложение, сервер): только чтение, источник из настроек.",
      _schema, risk="read", summary=lambda a: f"Прочитать лог {a['source']}")
def read_log(ctx, source, lines=80, grep=""):
    src = next((s for s in _sources(ctx.cfg) if s["name"] == source), None)
    if not src:
        raise ToolError(f"источника «{source}» нет в настройках (log_sources)")
    ctx.ui_action(f"Читаю лог {source}")
    rows = _tail_ssh(src, 400 if grep else lines) if src.get("type") == "ssh" else _tail_file(src["path"], 2000 if grep else lines)
    if grep:
        rows = [r for r in rows if grep.lower() in r.lower()][-lines:]
    text = mask("\n".join(r[:400] for r in rows))
    return text[-6000:] if text else "Лог пуст или строк по фильтру нет."


from . import REGISTRY  # noqa: E402

REGISTRY["read_log"].when = lambda cfg: bool(_sources(cfg))
