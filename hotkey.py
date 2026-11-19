"""Глобальная горячая клавиша Windows (по умолчанию Win+Shift+X): вызывает компактное окно ХРАЗа поверх всех окон.
RegisterHotKey в отдельном потоке с собственным циклом сообщений. Вне Windows — недоступно (работает Esc/кнопка)."""
import sys
import threading

MODS = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
NOREPEAT = 0x4000


def parse(combo):
    """'win+shift+x' → (модификаторы, код клавиши) или None."""
    parts = [p.strip().lower() for p in (combo or "").split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
    for p in parts[:-1]:
        if p not in MODS:
            return None
        mods |= MODS[p]
    key = parts[-1]
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key in ("space", "пробел"):
        vk = 0x20
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        vk = 0x6F + int(key[1:])
    else:
        return None
    return mods, vk


class GlobalHotkey:
    def __init__(self, combo, callback):
        self.combo, self.cb = combo, callback
        self.thread = None
        self.thread_id = None
        self.error = None

    def start(self):
        if sys.platform != "win32":
            self.error = "глобальная клавиша работает только в Windows"
            return False
        parsed = parse(self.combo)
        if not parsed:
            self.error = f"не понял сочетание «{self.combo}»"
            return False
        ready = threading.Event()

        def run():
            import ctypes
            from ctypes import wintypes
            u, k = ctypes.windll.user32, ctypes.windll.kernel32
            self.thread_id = k.GetCurrentThreadId()
            mods, vk = parsed
            if not u.RegisterHotKey(None, 1, mods | NOREPEAT, vk):
                self.error = f"сочетание {self.combo} занято другой программой"
                ready.set()
                return
            ready.set()
            msg = wintypes.MSG()
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:          # WM_HOTKEY
                    try:
                        self.cb()
                    except Exception:
                        pass
            u.UnregisterHotKey(None, 1)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        ready.wait(3)
        return self.error is None

    def stop(self):
        if self.thread_id and sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)   # WM_QUIT
