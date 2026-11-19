"""Звуки интерфейса в духе Предприятия: короткие «полимерные» отклики, синтезируются на лету (без файлов).
wake — услышал обращение; card — нужна ваша кнопка; done — действие выполнено; error — сбой; alert — ХРАЗ
сам хочет что-то сказать. Играют поверх речи тихо; выключаются в Настройках или режимом тишины."""
import threading

import numpy as np

SR = 44100
_cache = {}


def _tone(freqs, dur, vol=0.18, decay=8.0, wobble=0.0):
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    sig = np.zeros_like(t)
    for i, f in enumerate(freqs):
        seg = (t >= i * dur / len(freqs)) & (t < (i + 1) * dur / len(freqs))
        ft = f * (1 + wobble * np.sin(2 * np.pi * 7 * t))
        sig += seg * (np.sin(2 * np.pi * ft * t) + 0.3 * np.sin(4 * np.pi * ft * t))
    env = np.exp(-decay * t / dur) * np.minimum(1, t * 400)
    out = sig * env
    for ms, g in ((23, 0.25), (41, 0.12)):          # короткое «металлическое» эхо
        k = int(SR * ms / 1000)
        out[k:] += g * out[:-k]
    return (out / (np.abs(out).max() or 1) * vol).astype(np.float32)


SOUNDS = {
    "wake": lambda: _tone([660, 990], 0.18, wobble=0.004),
    "card": lambda: _tone([520, 520, 780], 0.30, vol=0.16),
    "done": lambda: _tone([880, 1320], 0.16, vol=0.13),
    "error": lambda: _tone([300, 220], 0.32, vol=0.17, decay=4),
    "alert": lambda: _tone([740, 980, 740], 0.42, vol=0.16, wobble=0.01),
}


def samples(name):
    if name not in _cache:
        _cache[name] = SOUNDS[name]()
    return _cache[name]


def play(name, cfg=None):
    if cfg is not None and not cfg.get("sfx", True):
        return
    if name not in SOUNDS:
        return

    def run():
        try:
            import sounddevice as sd
            data = samples(name).reshape(-1, 1)
            with sd.OutputStream(samplerate=SR, channels=1, dtype="float32") as st:   # свой поток: речь не трогаем
                st.write(data)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()
