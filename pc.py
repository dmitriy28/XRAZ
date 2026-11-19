"""Расширенное управление ПК: окна, ввод текста и клавиш, мышь, папки, настройки Windows, PowerShell, ИИ-текст."""
import os
import subprocess
import time

import actions as A
from textutil import translit

# --- клавиши голосом ---------------------------------------------------------
KEY_WORDS = {
    "энтер": "enter", "ввод": "enter", "интер": "enter", "enter": "enter", "пробел": "space", "таб": "tab",
    "эскейп": "esc", "escape": "esc", "эскейт": "esc", "удалить": "delete", "делит": "delete",
    "бэкспейс": "backspace", "стереть": "backspace", "контрол": "ctrl", "контрл": "ctrl", "ctrl": "ctrl",
    "альт": "alt", "шифт": "shift", "вин": "win", "виндовс": "win", "пуск": "win", "вверх": "up", "вниз": "down",
    "влево": "left", "вправо": "right", "плюс": "+",
}
for i in range(1, 13):
    KEY_WORDS[f"ф{i}"] = f"f{i}"
    KEY_WORDS[f"f{i}"] = f"f{i}"
# одиночные буквы — по звучанию: «контрол эс/с» = Ctrl+S, «вин д» = Win+D
RU2EN = dict(zip("абвгдезиклмнопрстуфхц", "abvgdezikl" "mnoprstufhc"))
RU2EN.update({"й": "y", "ю": "u", "я": "a", "э": "e", "ы": "i", "ж": "j", "ч": "c", "ш": "w", "щ": "w"})
LETTER_NAMES = {"бэ": "b", "би": "b", "цэ": "c", "си": "c", "дэ": "d", "ди": "d", "эф": "f", "вэ": "v", "ви": "v",
                "икс": "x", "игрек": "y", "зэт": "z", "зет": "z", "эс": "s", "тэ": "t", "ти": "t", "кей": "k",
                "ка": "k", "эль": "l", "эн": "n", "пэ": "p", "пи": "p", "эр": "r", "ар": "r", "эм": "m",
                "джей": "j", "аш": "h", "эйч": "h", "дабл ю": "w", "ку": "q", "кью": "q", "о": "o", "ай": "i",
                "жи": "g", "джи": "g", "гэ": "g", "у": "u", "ю": "u", "а": "a", "е": "e", "и": "i"}


def voice_to_combo(text):
    """«контрол шифт эскейп» -> ctrl+shift+esc, «контрол с» -> ctrl+s, «альт ф4» -> alt+f4"""
    keys = []
    for w in text.replace("+", " ").split():
        if w in ("и", "плюс", "нажми", "клавишу", "клавиши", "кнопку"):
            continue
        if w in KEY_WORDS:
            keys.append(KEY_WORDS[w])
        elif w in LETTER_NAMES:
            keys.append(LETTER_NAMES[w])
        elif len(w) == 1:
            keys.append(RU2EN.get(w, w))   # «с» на русской раскладке = физическая клавиша C
        elif w.isdigit():
            keys.append(w)
        else:
            keys.append(w)
    return "+".join(keys)


def press_key(param, ctx):
    combo = voice_to_combo(param) if any("а" <= c <= "я" for c in param) else param
    A.press(combo)


# --- окна --------------------------------------------------------------------
def _focus(hwnd):
    if not A.IS_WIN:
        return
    import ctypes
    u = ctypes.windll.user32
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)          # SW_RESTORE
    A.press("alt")                     # снимает запрет Windows на смену фокуса из фона
    u.SetForegroundWindow(hwnd)
    u.BringWindowToTop(hwnd)


def _proc_name(hwnd):
    import ctypes
    from ctypes import wintypes
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    size = wintypes.DWORD(512)
    ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
    ctypes.windll.kernel32.CloseHandle(h)
    return os.path.basename(buf.value).lower()


def find_window(query):
    from rapidfuzz import fuzz
    q = A.APP_ALIASES.get(query.lower().strip(), query.lower().strip())
    variants = {q, translit(q)}
    best, score = None, 0
    for hwnd, title in A._top_windows():
        hay = f"{title.lower()} {_proc_name(hwnd)}"
        s = max(fuzz.partial_ratio(v, hay) for v in variants)
        if s > score:
            best, score = hwnd, s
    return best if score >= 75 else None


def focus_window(param, ctx):
    if not A.IS_WIN:
        print(f"[dry] focus {param}"); return None
    hwnd = find_window(param)
    if not hwnd:
        return f"Не нашёл окно {param}"
    _focus(hwnd)
    time.sleep(0.3)


def window_snapshot():
    return {h for h, _ in A._top_windows()} if A.IS_WIN else set()


def wait_new_window(before, timeout=8.0):
    """После запуска программы ждём её окно и делаем активным — чтобы следующий шаг печатал туда."""
    if not A.IS_WIN:
        return
    end = time.time() + timeout
    while time.time() < end:
        new = window_snapshot() - before
        if new:
            time.sleep(0.6)                 # окно появилось, даём ему дорисоваться
            _focus(next(iter(new)))
            time.sleep(0.3)
            return True
        time.sleep(0.25)
    return False


def window_op(param, ctx):
    combo = {"maximize": "win+up", "minimize": "win+down", "left": "win+left", "right": "win+right",
             "switch": "alt+tab", "desktop": "win+d", "fullscreen": "f11"}.get(param.strip(), "alt+tab")
    A.press(combo)


EDIT = {"save": "ctrl+s", "select_all": "ctrl+a", "copy": "ctrl+c", "paste": "ctrl+v", "cut": "ctrl+x",
        "undo": "ctrl+z", "redo": "ctrl+y", "new_tab": "ctrl+t", "reopen_tab": "ctrl+shift+t", "newline": "enter",
        "find": "ctrl+f", "refresh": "f5", "zoom_in": "ctrl+plus", "zoom_out": "ctrl+minus", "print": "ctrl+p",
        "new": "ctrl+n", "close_tab": "ctrl+w", "back": "alt+left", "forward": "alt+right"}
A.VK.update({"plus": 0xBB, "minus": 0xBD})


def edit(param, ctx):
    A.press(EDIT.get(param.strip(), param))


# --- ввод текста ----------------------------------------------------------------
def type_text(param, ctx):
    text = param.strip()
    if not text:
        return None
    if not A.IS_WIN:
        print(f"[dry] type «{text}»"); return None
    import pyperclip
    try:
        old = pyperclip.paste()
    except Exception:
        old = None
    pyperclip.copy(text)
    time.sleep(0.08)
    A.press("ctrl+v")
    time.sleep(0.25)
    if old is not None:
        try:
            pyperclip.copy(old)        # возвращаем буфер обмена как был
        except Exception:
            pass


def write_ai(param, ctx):
    """Модель пишет текст (стих, письмо, код…) и печатает его в активное окно."""
    ctx.ui.status("thinking")
    prompt = [{"role": "system", "content": "Напиши текст по просьбе пользователя на русском. Выведи ТОЛЬКО сам "
                                            "текст, без вступлений, пояснений и markdown."},
              {"role": "user", "content": param}]
    text = ctx.llm.chat(prompt, max_tokens=900)
    type_text(text, ctx)
    return "Готово, написал"


def dictate_fix(text):
    """Vosk пишет без заглавных и точек — чуть приводим в порядок."""
    t = text.strip()
    return (t[:1].upper() + t[1:]) if t else t


# --- мышь -------------------------------------------------------------------------
def mouse(param, ctx):
    if not A.IS_WIN:
        print(f"[dry] mouse {param}"); return
    import ctypes
    m = ctypes.windll.user32.mouse_event
    p = param.strip()
    if p in ("scroll_down", "scroll_up"):
        for _ in range(5):
            m(0x0800, 0, 0, -120 if p == "scroll_down" else 120, 0)
            time.sleep(0.02)
    elif p == "click":
        m(0x0002, 0, 0, 0, 0); m(0x0004, 0, 0, 0, 0)
    elif p == "double_click":
        for _ in range(2):
            m(0x0002, 0, 0, 0, 0); m(0x0004, 0, 0, 0, 0)
    elif p == "right_click":
        m(0x0008, 0, 0, 0, 0); m(0x0010, 0, 0, 0, 0)


# --- папки и настройки Windows ----------------------------------------------------
HOME = os.path.expanduser("~")
FOLDERS = {
    "загрузки": "Downloads", "документы": "Documents", "рабочий стол": "Desktop", "изображения": "Pictures",
    "картинки": "Pictures", "фото": "Pictures", "музыку": "Music", "музыка": "Music", "видео": "Videos",
    "скриншоты": os.path.join("Pictures", "Jarvis"), "диск ц": "C:\\", "диск с": "C:\\", "диск д": "D:\\",
    "диск d": "D:\\", "этот компьютер": "shell:MyComputerFolder", "корзину": "shell:RecycleBinFolder",
    "корзина": "shell:RecycleBinFolder", "автозагрузку": "shell:startup",
}


def open_folder(param, ctx):
    p = param.strip().lower()
    p = p.replace("папку ", "").strip()
    target = FOLDERS.get(p)
    if target is None:
        for k, v in FOLDERS.items():
            if k in p:
                target = v
                break
    if target is None:
        target = param.strip()
    if not (target.startswith("shell:") or os.path.isabs(target)):
        target = os.path.join(HOME, target)
    A._run(["explorer", target], shell=False)


SETTINGS = {
    "блютуз": "bluetooth", "bluetooth": "bluetooth", "звук": "sound", "звука": "sound", "экран": "display",
    "экрана": "display", "дисплей": "display", "вай фай": "network-wifi", "wifi": "network-wifi",
    "интернет": "network", "сеть": "network", "обновления": "windowsupdate", "батарея": "batterysaver",
    "питание": "powersleep", "приложения": "appsfeatures", "персонализация": "personalization",
    "фон": "personalization-background", "мышь": "mousetouchpad", "клавиатура": "typing", "язык": "regionlanguage",
    "уведомления": "notifications", "микрофон": "privacy-microphone", "принтеры": "printers",
    "хранилище": "storagesense", "память": "storagesense", "автозагрузка": "startupapps",
}


def open_settings(param, ctx):
    p = param.strip().lower()
    page = next((v for k, v in SETTINGS.items() if k in p), "")
    A._run(f'start "" ms-settings:{page}')


# --- PowerShell (только фиксированные внутренние команды; модели не отдаётся) ---------------
def powershell(param, ctx):
    """Внутренний помощник для фиксированных команд (очистка корзины). Модель произвольный PowerShell
    не получает — системные запросы идут через белый список tools/system.py."""
    if not A.IS_WIN:
        print(f"[dry] powershell {param}"); return "Готово"
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + param],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                       creationflags=0x08000000)
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if r.returncode != 0 and err:
        ctx.ui.assistant("PowerShell ошибка:\n" + err[:1500])
        return "Команда завершилась с ошибкой, подробности в чате"
    if not out:
        return "Готово"
    if len(out) <= 200:
        return out
    ctx.ui.assistant(out[:3000])
    return "Готово, результат в чате"


def empty_bin(param, ctx):
    return powershell("Clear-RecycleBin -Force -ErrorAction SilentlyContinue", ctx) and "Корзина очищена"


EXTRA = {
    "focus_window":  (focus_window, "переключиться на окно открытой программы; param = название", "переключиться на {p}"),
    "window":        (window_op, "окно: param = maximize|minimize|left|right|switch|desktop|fullscreen", "окно {p}"),
    "press_key":     (press_key, "нажать клавишу/сочетание; param вида ctrl+s, enter, alt+f4", "нажать {p}"),
    "edit":          (edit, "правка: param = save|select_all|copy|paste|cut|undo|redo|new_tab|reopen_tab|newline|"
                            "find|refresh|zoom_in|zoom_out|print|new|close_tab|back|forward", "{p}"),
    "type_text":     (type_text, "напечатать ТОЧНЫЙ текст в активное окно; param = текст", "напечатать «{p}»"),
    "write_ai":      (write_ai, "СОЧИНИТЬ текст (стих, письмо, код, список) и напечатать в активное окно; "
                                "param = что написать", "сочинить и напечатать: {p}"),
    "mouse":         (mouse, "мышь: param = scroll_down|scroll_up|click|double_click|right_click", "мышь {p}"),
    "open_folder":   (open_folder, "открыть папку; param = загрузки|документы|рабочий стол|картинки|музыка|видео|"
                                   "диск с|корзина или полный путь", "открыть папку {p}"),
    "open_settings": (open_settings, "открыть параметры Windows; param = bluetooth|звук|экран|wifi|обновления|"
                                     "питание|приложения|фон|микрофон|автозагрузка", "открыть настройки {p}"),
    "empty_bin":     (empty_bin, "очистить корзину; param пустой", "очистить корзину"),
}

# действия, которые модель может предложить, но выполняются только после «да»
CONFIRM = {"shutdown", "restart", "close_all_windows", "empty_bin", "close_app"}

A._register_pc(__import__(__name__))
