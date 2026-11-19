"""Системные команды — только из белого списка. Модель выбирает ИМЯ команды, а не пишет её текст.
Каждая команда — фиксированный список аргументов без оболочки (shell=False); единственный параметр
(адрес для ping) проверяется шаблоном."""
import datetime
import re
import subprocess
import sys

from . import ToolError, tool

IS_WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000 if IS_WIN else 0


def _run(argv, timeout=20):
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8" if not IS_WIN else "cp866",
                       errors="replace", timeout=timeout, creationflags=NO_WINDOW)
    out = (r.stdout or "").strip() or (r.stderr or "").strip()
    return out[:3000]


def _ps(script):
    if not IS_WIN:
        raise ToolError("команда доступна только в Windows")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
                       creationflags=NO_WINDOW)
    return ((r.stdout or "").strip() or (r.stderr or "").strip())[:3000]


def ip_address(arg):
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = socket.gethostbyname(socket.gethostname())
    return f"Локальный IP: {ip}"


def disk_space(arg):
    import psutil
    rows = []
    for p in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(p.mountpoint)
        except Exception:
            continue
        rows.append(f"{p.mountpoint} свободно {u.free // 1024 ** 3} из {u.total // 1024 ** 3} ГБ")
    return "; ".join(rows) or "дисков не найдено"


def battery(arg):
    import psutil
    b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if not b:
        return "Батарея не обнаружена (настольный ПК или нет данных)"
    return f"Батарея {round(b.percent)}%" + (", на зарядке" if b.power_plugged else "")


def uptime(arg):
    import psutil
    d = datetime.datetime.now() - datetime.datetime.fromtimestamp(psutil.boot_time())
    return f"Компьютер работает {d.days} дн. {d.seconds // 3600} ч. {d.seconds % 3600 // 60} мин."


def top_processes(arg):
    import psutil
    procs = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            procs.append((p.info["memory_info"].rss, p.info["name"]))
        except Exception:
            pass
    procs.sort(reverse=True)
    return "; ".join(f"{n} {m // 1024 ** 2} МБ" for m, n in procs[:8])


def ping(arg):
    if not arg or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", arg):
        raise ToolError("укажите адрес: домен или IP, например ya.ru")
    return _run(["ping", "-n" if IS_WIN else "-c", "4", arg], timeout=25)


def gpu_status(arg):
    import khraz_tools
    return khraz_tools._gpu() or "Видеокарта NVIDIA не найдена (nvidia-smi недоступен)"


def wifi_info(arg):
    if not IS_WIN:
        raise ToolError("команда доступна только в Windows")
    return _run(["netsh", "wlan", "show", "interfaces"])


def flush_dns(arg):
    if not IS_WIN:
        raise ToolError("команда доступна только в Windows")
    return _run(["ipconfig", "/flushdns"])


def system_report(arg):
    import khraz_tools
    return khraz_tools.system_report()


def ollama_models(arg):
    return _run(["ollama", "ps"])


# имя → (функция, описание, риск)
WHITELIST = {
    "ip_address": (ip_address, "локальный IP-адрес", "read"),
    "disk_space": (disk_space, "свободное место на дисках", "read"),
    "battery": (battery, "заряд батареи", "read"),
    "uptime": (uptime, "сколько работает компьютер", "read"),
    "top_processes": (top_processes, "самые прожорливые процессы по памяти", "read"),
    "ping": (ping, "проверить связь с адресом (arg = домен или IP)", "read"),
    "gpu_status": (gpu_status, "видеокарта: температура, загрузка, видеопамять", "read"),
    "wifi_info": (wifi_info, "текущее Wi-Fi подключение", "read"),
    "system_report": (system_report, "общий доклад: процессор, память, видеокарта, диск", "read"),
    "ollama_models": (ollama_models, "какие модели сейчас загружены в Ollama", "read"),
    "flush_dns": (flush_dns, "сбросить кэш DNS (меняет состояние системы)", "change"),
}

SCHEMA = {"type": "object", "properties": {
    "name": {"type": "string", "enum": list(WHITELIST),
             "description": "; ".join(f"{k} — {v[1]}" for k, v in WHITELIST.items())},
    "arg": {"type": "string", "maxLength": 253, "description": "параметр, только для ping"}},
    "required": ["name"], "additionalProperties": False}


@tool("run_command", "Выполнить системную команду из белого списка (информация о компьютере и сети). "
      "Произвольные команды запрещены.", SCHEMA, risk=lambda a: WHITELIST[a["name"]][2],
      summary=lambda a: f"Системная команда: {WHITELIST[a['name']][1]}")
def run_command(ctx, name, arg=""):
    fn = WHITELIST[name][0]
    ctx.ui_action(f"Команда: {WHITELIST[name][1]}")
    return fn(arg)
