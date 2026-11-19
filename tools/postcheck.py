"""Проверка после записи, откат последнего изменения, статистика инструментов, пробуждение ноутбука.

- VERIFY: реестр проверок «после записи»: инструмент может перечитать состояние и добавить «Проверка: …» к результату.
- UNDO: обратимые изменения пишутся в undo.json; «отмени последнее» готовит обратное действие, которое выполнится
  только после подтверждения. Реестр обратных действий (_inverse) расширяется под ваши коннекторы.
- tool_stats: сколько вызовов, ошибок и какое время — из журнала logs/tools.jsonl."""
import json
import os
import socket
import threading
import time

from config import DATA

from . import REGISTRY, ToolError, read_log, tool

UNDO_PATH = os.path.join(DATA, "undo.json")
UNDO_MAX = 10
_lock = threading.Lock()


# ------------------------------------------------------------------ проверка после записи
VERIFY = {}   # имя инструмента → функция(ctx, args, res) → строка проверки


def verify(name, ctx, args, res):
    """Возвращает res с добавленной проверкой (ошибка проверки результат не ломает)."""
    fn = VERIFY.get(name)
    if not fn:
        return res
    try:
        note = fn(ctx, args, res)
    except Exception:           # noqa: BLE001
        return res
    if isinstance(res, dict):
        return dict(res, проверка=note)
    return f"{res}\n{note}"


# ------------------------------------------------------------------ откат
def _inverse(name, args):
    """(инструмент, аргументы, описание) или None, если действие необратимо."""
    return None


def _undo_load():
    try:
        with open(UNDO_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _undo_save(items):
    tmp = UNDO_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items[-UNDO_MAX:], f, ensure_ascii=False)
    os.replace(tmp, UNDO_PATH)


def record(name, args):
    inv = _inverse(name, args)
    if not inv:
        return
    with _lock:
        items = _undo_load()
        items.append({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "tool": inv[0], "args": inv[1], "what": inv[2]})
        _undo_save(items)


@tool("undo_last", "Отменить последнее обратимое изменение, если для него есть обратное действие. "
      "Нужно подтверждение.", {"type": "object", "properties": {}, "additionalProperties": False}, risk="change",
      summary=lambda a: "Отменить последнее изменение: " + (_undo_load()[-1]["what"] if _undo_load() else "нечего отменять"))
def undo_last(ctx):
    from . import call
    with _lock:
        items = _undo_load()
        if not items:
            raise ToolError("отменять нечего")
        last = items[-1]
    res = call(last["tool"], last["args"], ctx, via="undo", confirmed=True)
    with _lock:
        items = _undo_load()
        if items and items[-1] == last:
            items.pop()
            _undo_save(items)
    return f"Отменено: {last['what']}. {res if isinstance(res, str) else ''}".strip()


# ------------------------------------------------------------------ статистика
def stats(limit=2000):
    rows = {}
    for r in read_log(limit):
        s = rows.setdefault(r["tool"], {"ok": 0, "error": 0, "invalid": 0, "confirm": 0, "ms": 0, "n": 0, "last_err": ""})
        st = r.get("status")
        if st == "ok":
            s["ok"] += 1
            s["ms"] += r.get("ms", 0)
            s["n"] += 1
        elif st in ("error", "invalid", "unknown"):
            s["error" if st == "error" else "invalid"] += 1
            s["last_err"] = (r.get("result") or "")[:120]
        elif st == "needs_confirm":
            s["confirm"] += 1
    return rows


@tool("tool_stats", "Статистика вызовов инструментов ХРАЗа: успехи, ошибки, время — чтобы понять, что работает плохо.",
      {"type": "object", "properties": {}, "additionalProperties": False}, risk="read")
def tool_stats(ctx):
    rows = stats()
    if not rows:
        return "Журнал инструментов пуст."
    lines = []
    for name, s in sorted(rows.items(), key=lambda kv: -(kv[1]["error"] + kv[1]["invalid"])):
        avg = f"{s['ms'] // s['n']} мс" if s["n"] else "—"
        bad = s["error"] + s["invalid"]
        lines.append(f"{name}: ок {s['ok']}, ошибок {s['error']}, неверных аргументов {s['invalid']}, "
                     f"подтверждений {s['confirm']}, среднее {avg}" + (f" · последняя: {s['last_err']}" if bad and s["last_err"] else ""))
    return "\n".join(lines[:30])


# ------------------------------------------------------------------ Wake-on-LAN
def magic_packet(mac):
    h = "".join(c for c in mac if c in "0123456789abcdefABCDEF")
    if len(h) != 12:
        raise ToolError("MAC-адрес вида AA:BB:CC:DD:EE:FF")
    return bytes.fromhex("FF" * 6 + h * 16)


def wake(mac, broadcast="255.255.255.255", port=9):
    pkt = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(pkt, (broadcast, port))
    return pkt


@tool("wake_laptop", "Разбудить ноутбук с мощной моделью (Wake-on-LAN). Ноутбук включится за 20–60 секунд.",
      {"type": "object", "properties": {}, "additionalProperties": False}, risk="action",
      summary=lambda a: "Разбудить ноутбук (Wake-on-LAN)")
def wake_laptop(ctx):
    mac = ctx.cfg.get("wol_mac")
    if not mac:
        raise ToolError("MAC-адрес ноутбука не задан (wol_mac в настройках)")
    wake(mac, ctx.cfg.get("wol_broadcast") or "255.255.255.255")
    return "Сигнал отправлен. Ноутбук проснётся через 20–60 секунд; ХРАЗ вернётся на мощную модель сам."


REGISTRY["wake_laptop"].when = lambda cfg: bool(cfg.get("wol_mac"))
