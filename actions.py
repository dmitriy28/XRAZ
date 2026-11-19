"""Действия, из которых собираются команды. Каждое: fn(param:str, ctx) -> str|None (что сказать)."""
import datetime
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

from textutil import translit

IS_WIN = sys.platform == "win32"

# --- справочники -----------------------------------------------------------
SITES = {
    "ютуб": "https://youtube.com", "youtube": "https://youtube.com",
    "вк": "https://vk.com", "вконтакте": "https://vk.com", "контакт": "https://vk.com",
    "гугл": "https://google.com", "google": "https://google.com",
    "яндекс": "https://ya.ru", "почту": "https://mail.yandex.ru", "почта": "https://mail.yandex.ru",
    "гитхаб": "https://github.com", "github": "https://github.com",
    "кинопоиск": "https://kinopoisk.ru", "переводчик": "https://translate.yandex.ru",
    "карты": "https://yandex.ru/maps", "погоду": "https://yandex.ru/pogoda", "погода": "https://yandex.ru/pogoda",
}
APP_ALIASES = {
    "стим": "steam", "дискорд": "discord", "телеграм": "telegram", "телеграмм": "telegram", "тг": "telegram",
    "хром": "chrome", "гугл хром": "chrome", "браузер": "chrome", "яндекс браузер": "yandex",
    "блокнот": "notepad", "калькулятор": "calc", "проводник": "explorer", "вс код": "code",
    "визуал студио код": "code", "спотифай": "spotify", "ворд": "winword", "эксель": "excel",
    "обс": "obs", "диспетчер задач": "taskmgr", "настройки": "ms-settings:", "паинт": "mspaint",
    "командную строку": "cmd", "терминал": "wt", "опен сервер": "open server", "ватсап": "whatsapp",
}
PROCESS_NAMES = {
    "steam": "steam.exe", "discord": "Discord.exe", "telegram": "Telegram.exe", "chrome": "chrome.exe",
    "yandex": "browser.exe", "notepad": "notepad.exe", "calc": "CalculatorApp.exe", "code": "Code.exe",
    "spotify": "Spotify.exe", "winword": "WINWORD.EXE", "excel": "EXCEL.EXE", "obs": "obs64.exe",
    "taskmgr": "Taskmgr.exe", "whatsapp": "WhatsApp.exe",
}
DIRECT = {"notepad", "calc", "explorer", "cmd", "taskmgr", "mspaint", "wt", "code"}

# --- клавиатура через WinAPI -------------------------------------------------
VK = {"win": 0x5B, "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "tab": 0x09, "enter": 0x0D, "esc": 0x1B,
      "space": 0x20, "backspace": 0x08, "delete": 0x2E, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
      "volup": 0xAF, "voldown": 0xAE, "mute": 0xAD, "playpause": 0xB3, "next": 0xB0, "prev": 0xB1,
      "printscreen": 0x2C}
VK.update({f"f{i}": 0x6F + i for i in range(1, 13)})


def _vk(key):
    key = key.strip().lower()
    if key in VK:
        return VK[key]
    if len(key) == 1:
        return ord(key.upper())
    raise ValueError(f"неизвестная клавиша {key}")


def press(combo, times=1):
    if not IS_WIN:
        print(f"[dry] press {combo} x{times}"); return
    import ctypes
    kb = ctypes.windll.user32.keybd_event
    codes = [_vk(k) for k in combo.split("+")]
    for _ in range(times):
        for c in codes:
            kb(c, 0, 0, 0)
        for c in reversed(codes):
            kb(c, 0, 2, 0)
        time.sleep(0.01)


def _run(cmd, shell=True):
    if not IS_WIN:
        print(f"[dry] {cmd}"); return
    subprocess.Popen(cmd, shell=shell, creationflags=0x08000000)  # CREATE_NO_WINDOW


def _ps(script):
    _run(["powershell", "-NoProfile", "-Command", script], shell=False)


def _int(param, default=0):
    import re
    m = re.search(r"\d+", str(param))
    return int(m.group()) if m else default


# --- поиск приложений в меню Пуск / на рабочем столе ------------------------
_index = None


def _app_index():
    global _index
    if _index is not None:
        return _index
    _index = {}
    if not IS_WIN:
        return _index
    roots = [
        os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.expandvars(r"%PUBLIC%\Desktop"),
        os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"),
        os.path.join(os.path.expanduser("~"), "OneDrive", "Рабочий стол"),
    ]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for d, _, files in os.walk(root):
            for f in files:
                if f.lower().endswith((".lnk", ".url", ".exe")):
                    name = os.path.splitext(f)[0].lower()
                    if "uninstall" in name or "удален" in name:
                        continue
                    _index.setdefault(name, os.path.join(d, f))
    return _index


def find_app(query):
    from rapidfuzz import fuzz, process
    q = query.lower().strip()
    q = APP_ALIASES.get(q, q)
    idx = _app_index()
    if not idx:
        return None, q
    best = None
    for variant in {q, translit(q)}:
        r = process.extractOne(variant, list(idx.keys()), scorer=fuzz.WRatio)
        if r and (best is None or r[1] > best[1]):
            best = r
    if best and best[1] >= 72:
        return idx[best[0]], best[0]
    return None, q


# --- сами действия -----------------------------------------------------------
def open_app(param, ctx):
    p = param.strip().strip('"')
    if p.lower() in SITES:
        return open_url(SITES[p.lower()], ctx)
    if os.path.exists(p):
        os.startfile(p) if IS_WIN else print(f"[dry] start {p}")
        return None
    import re as _re
    if _re.fullmatch(r"(steam://rungameid/\d+|shell:AppsFolder\\[\w.!-]+|com\.epicgames\.launcher://apps/[\w%:.-]+)", p, _re.I):
        os.startfile(p) if IS_WIN else print(f"[dry] start {p}")        # Steam / Microsoft Store / Epic: только эти шаблоны
        return None
    path, name = find_app(p)
    if path:
        os.startfile(path) if IS_WIN else print(f"[dry] start {path}")
        return None
    alias = APP_ALIASES.get(p.lower(), p)
    import re
    if (alias in DIRECT or alias.endswith(":")) and re.fullmatch(r"[\w.-]+:?", alias):   # без спецсимволов cmd
        _run(f'start "" {alias}')
        return None
    return f"Не нашёл приложение {p}"


def close_app(param, ctx):
    p = param.strip().lower()
    alias = APP_ALIASES.get(p, p)
    exe = PROCESS_NAMES.get(alias, alias if alias.endswith(".exe") else alias + ".exe")
    _run(["taskkill", "/im", exe, "/f"], shell=False)          # без оболочки: имя не может стать командой


def open_url(param, ctx):
    url = param.strip()
    if url.lower() in SITES:
        url = SITES[url.lower()]
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)


def youtube_search(param, ctx):
    webbrowser.open("https://www.youtube.com/results?search_query=" + urllib.parse.quote(param))


def web_search(param, ctx):
    webbrowser.open("https://ya.ru/search/?text=" + urllib.parse.quote(param))


def volume(param, ctx):
    level = max(0, min(100, _int(param, 50)))
    try:
        _set_volume_pycaw(level)
    except Exception:
        press("voldown", 50)          # запасной путь: до нуля и вверх шагами по 2%
        press("volup", level // 2)
    return f"Громкость {level}"


def _set_volume_pycaw(level):
    if not IS_WIN:
        raise RuntimeError
    import comtypes
    from pycaw.pycaw import AudioUtilities
    comtypes.CoInitialize()
    dev = AudioUtilities.GetSpeakers()
    ep = getattr(dev, "EndpointVolume", None)
    if ep is None:  # старые версии pycaw
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import IAudioEndpointVolume
        ep = cast(dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None), POINTER(IAudioEndpointVolume))
    ep.SetMute(0, None)
    ep.SetMasterVolumeLevelScalar(level / 100, None)


def volume_up(param, ctx):
    press("volup", max(1, _int(param, 10) // 2))


def volume_down(param, ctx):
    press("voldown", max(1, _int(param, 10) // 2))


def mute(param, ctx):
    press("mute")


def media(param, ctx):
    press({"pause": "playpause", "play": "playpause", "next": "next", "prev": "prev"}.get(param.strip(), "playpause"))


def brightness(param, ctx):
    level = max(0, min(100, _int(param, 50)))
    _ps(f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})")
    return f"Яркость {level}"


def hotkey(param, ctx):
    press(param)


def minimize_all(param, ctx):
    press("win+m")


SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow",
                "ApplicationFrameWindow_skip", "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland"}


def _top_windows():
    """Видимые окна приложений (как на панели задач), кроме самого Джарвиса и оболочки Windows."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    me = os.getpid()
    res = []
    GW_OWNER, GWL_EXSTYLE, WS_EX_TOOLWINDOW = 4, -20, 0x80

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not u.IsWindowVisible(hwnd) or u.GetWindow(hwnd, GW_OWNER):
            return True
        if u.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        n = u.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        cls = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, cls, 256)
        if cls.value in SKIP_CLASSES:
            return True
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == me:
            return True
        title = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, title, n + 1)
        res.append((hwnd, title.value))
        return True

    u.EnumWindows(cb, 0)
    return res


def close_all_windows(param, ctx):
    if not IS_WIN:
        print("[dry] close all windows"); return "Закрыл окна"
    import ctypes
    wins = _top_windows()
    for hwnd, _ in wins:
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE — как крестик, с вопросом «сохранить?»
    return f"Закрываю окна: {len(wins)}" if wins else "Открытых окон нет"


def close_window(param, ctx):
    press("alt+f4")


def close_tab(param, ctx):
    press("ctrl+w")


def lock(param, ctx):
    if IS_WIN:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
    else:
        print("[dry] lock")


def shutdown(param, ctx):
    minutes = _int(param, 0)
    _run(f"shutdown /s /t {minutes * 60}")
    return f"Выключу компьютер через {minutes} мин." if minutes else "Выключаю компьютер"


def restart(param, ctx):
    _run("shutdown /r /t 5")
    return "Перезагружаю"


def cancel_shutdown(param, ctx):
    _run("shutdown /a")
    return "Выключение отменено"


def sleep_pc(param, ctx):
    _run("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")


def screenshot(param, ctx):
    folder = os.path.join(os.path.expanduser("~"), "Pictures", "Jarvis")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, datetime.datetime.now().strftime("screen_%Y-%m-%d_%H-%M-%S.png"))
    try:
        from PIL import ImageGrab
        ImageGrab.grab(all_screens=True).save(path)
    except Exception:
        press("win+printscreen")
    return "Скриншот сохранён"


_timers = []


def _start_timer(seconds, fn, label=""):
    t = threading.Timer(seconds, fn)
    t.daemon = True
    t.khraz_label, t.khraz_at = label, time.time() + seconds
    _timers.append(t)
    t.start()


def pending_timers():
    """[(когда, подпись)] активных напоминаний и таймеров — для утреннего доклада."""
    return sorted((t.khraz_at, getattr(t, "khraz_label", "") or "таймер") for t in _timers
                  if t.is_alive() and hasattr(t, "khraz_at"))


def cancel_timers():
    """Снять все таймеры и напоминания."""
    while _timers:
        _timers.pop().cancel()


def timer(param, ctx):
    import persona
    seconds = _int(param, 60)
    _start_timer(seconds, lambda: ctx.notify(persona.say("timer_done")), "таймер")
    return f"Таймер на {_human(seconds)}"


def remind(param, ctx):
    # param: "<секунды>|<текст>"
    sec, _, text = param.partition("|")
    seconds = _int(sec, 60)
    _start_timer(seconds, lambda: ctx.notify(f"Напоминаю: {text or 'время пришло'}."), text or "напоминание")
    return f"Напомню через {_human(seconds)}"


def type_text(param, ctx):
    try:
        import pyperclip
        pyperclip.copy(param)
        time.sleep(0.05)
        press("ctrl+v")
    except Exception:
        return "Не получилось напечатать"


def say(param, ctx):
    return param


def wait(param, ctx):
    time.sleep(min(_int(param, 1), 60))


def tell_time(param, ctx):
    n = datetime.datetime.now()
    return f"Сейчас {n.hour}:{n.minute:02d}"


def tell_date(param, ctx):
    months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
    days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    n = datetime.date.today()
    return f"Сегодня {days[n.weekday()]}, {n.day} {months[n.month - 1]}"


def weather_now(param, ctx):
    # param: "город|день"  (день: 0 сегодня, 1 завтра, 2 послезавтра)
    import weather
    city, _, day = param.partition("|")
    city = city.strip() or ctx.cfg.get("city", "Москва")
    try:
        return weather.weather(city, _int(day, 0))
    except Exception as e:
        print("weather:", e)
        return "Не получилось узнать погоду, нет связи с сервисом"


def currency_rate(param, ctx):
    import weather
    try:
        return weather.currency(param.strip() or "USD")
    except Exception as e:
        print("currency:", e)
        return "Не получилось узнать курс, нет связи с сервисом"


def _human(sec):
    if sec % 3600 == 0 and sec >= 3600:
        return f"{sec // 3600} ч."
    if sec % 60 == 0:
        return f"{sec // 60} мин."
    return f"{sec} сек."


# type -> (функция, описание для модели и людей, подпись для озвучки)
ACTIONS = {
    "open_app":        (open_app, "открыть программу/игру/сайт по названию; param = название", "открыть {p}"),
    "close_app":       (close_app, "закрыть программу; param = название", "закрыть {p}"),
    "open_url":        (open_url, "открыть сайт; param = адрес", "открыть сайт {p}"),
    "youtube_search":  (youtube_search, "найти видео на YouTube; param = запрос", "найти на ютубе {p}"),
    "web_search":      (web_search, "поиск в интернете; param = запрос", "поиск {p}"),
    "volume":          (volume, "установить громкость; param = 0..100", "громкость {p}"),
    "volume_up":       (volume_up, "громче; param = на сколько процентов", "громче"),
    "volume_down":     (volume_down, "тише; param = на сколько процентов", "тише"),
    "mute":            (mute, "выключить/включить звук; param пустой", "выключить звук"),
    "media":           (media, "медиа: param = pause|next|prev", "медиа {p}"),
    "brightness":      (brightness, "яркость экрана; param = 0..100", "яркость {p}"),
    "hotkey":          (hotkey, "нажать сочетание клавиш; param вида ctrl+shift+esc", "нажать {p}"),
    "minimize_all":    (minimize_all, "свернуть все окна; param пустой", "свернуть все окна"),
    "close_all_windows": (close_all_windows, "закрыть все открытые окна и программы на рабочем столе; param пустой",
                          "закрыть все окна"),
    "close_window":    (close_window, "закрыть текущее активное окно; param пустой", "закрыть окно"),
    "close_tab":       (close_tab, "закрыть текущую вкладку браузера; param пустой", "закрыть вкладку"),
    "lock":            (lock, "заблокировать компьютер; param пустой", "заблокировать ПК"),
    "shutdown":        (shutdown, "выключить ПК; param = через сколько минут (0 = сейчас)", "выключить ПК через {p} мин."),
    "restart":         (restart, "перезагрузить ПК; param пустой", "перезагрузить ПК"),
    "cancel_shutdown": (cancel_shutdown, "отменить выключение; param пустой", "отменить выключение"),
    "sleep_pc":        (sleep_pc, "спящий режим; param пустой", "спящий режим"),
    "screenshot":      (screenshot, "сделать скриншот; param пустой", "скриншот"),
    "timer":           (timer, "таймер; param = секунды", "таймер {p} сек."),
    "remind":          (remind, "напоминание; param = 'секунды|текст'", "напоминание {p}"),
    "say":             (say, "сказать фразу; param = текст", "сказать «{p}»"),
    "wait":            (wait, "пауза; param = секунды", "пауза {p} сек."),
    "tell_time":       (tell_time, "сказать который час; param пустой", "сказать время"),
    "tell_date":       (tell_date, "сказать дату; param пустой", "сказать дату"),
    "weather":         (weather_now, "узнать погоду; param = 'город|день' (город пустой = домашний; день 0 сегодня, "
                                     "1 завтра, 2 послезавтра)", "сказать погоду"),
    "currency":        (currency_rate, "курс валюты ЦБ; param = USD|EUR|CNY", "курс {p}"),
}


def describe(step):
    if step.get("type") == "tool":                      # шаг-макрос: вызов инструмента (см. habits.py)
        try:
            import json
            d = json.loads(step.get("param") or "{}")
            return f"инструмент {d.get('tool')} " + ", ".join(f"{k}={v}" for k, v in (d.get("args") or {}).items())
        except Exception:
            return "инструмент"
    a = ACTIONS.get(step.get("type"))
    if not a:
        return f"неизвестное действие {step.get('type')}"
    p = str(step.get("param", "")).replace("https://", "").replace("http://", "").rstrip("/")
    if step.get("type") == "remind":
        sec, _, txt = p.partition("|")
        p = f"через {_human(_int(sec, 60))} «{txt}»"
    return a[2].format(p=p).strip()


def run_steps(steps, ctx):
    import pc
    said = []
    for i, s in enumerate(steps):
        a = ACTIONS.get(s.get("type"))
        if not a:
            said.append(f"Не знаю действие {s.get('type')}")
            continue
        has_next = i + 1 < len(steps)
        before = pc.window_snapshot() if (has_next and s["type"] in ("open_app", "open_url", "open_folder")) else None
        try:
            r = a[0](str(s.get("param", "")), ctx)
            if r:
                said.append(r)
            if before is not None:  # дальше будут печатать/жать клавиши — ждём окно и фокусируем
                if not pc.wait_new_window(before) and s["type"] == "open_app":
                    pc.focus_window(str(s.get("param", "")), ctx)
        except Exception as e:
            said.append(f"Ошибка: {e}")
    return said


CONFIRM = set()


def _register_pc(mod):
    """Подключение расширенных действий из pc.py (вызывается при любом порядке импорта)."""
    global CONFIRM
    ACTIONS.update(mod.EXTRA)
    ACTIONS.pop("hotkey", None)  # заменён на press_key
    CONFIRM = mod.CONFIRM


import pc as _pc  # noqa: E402
if hasattr(_pc, "EXTRA"):
    _register_pc(_pc)
