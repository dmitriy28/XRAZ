"""Потоковая озвучка без пауз.

Два потока:
  синтез — берёт очередную фразу и превращает её в куски звука (Fish Audio отдаёт звук по мере генерации);
  плеер  — непрерывно пишет куски в один открытый аудиопоток.
Пока звучит одна фраза, следующая уже синтезируется — между фразами нет тишины.

Движки: fish (fish.audio, облако), piper (офлайн), silero (офлайн, torch), sapi (голос Windows)."""
import hashlib
import io
import os
import queue
import threading
import time
import wave

import numpy as np

from config import BASE, DATA, resolve
from textutil import for_speech


class TTS:
    def __init__(self, cfg, on_state=None, on_error=None):
        self.cfg = cfg
        self.on_state = on_state or (lambda s: None)
        self.on_error = on_error or print
        self.text_q = queue.Queue()
        self.audio_q = queue.Queue()
        self.lock = threading.Lock()
        self.pending = 0            # фраз в работе (от say() до последнего записанного куска)
        self.play_until = 0.0       # когда доиграет уже отправленный в звуковую карту звук
        self.gen = 0                # поколение: stop() увеличивает, старые куски выкидываются
        self.engine_name = None
        self.engine = None
        self.direct = False         # sapi сам воспроизводит звук
        self._muted = False
        threading.Thread(target=self._synth_loop, daemon=True).start()
        threading.Thread(target=self._play_loop, daemon=True).start()

    # ---- публичное ----------------------------------------------------------
    def say(self, text):
        text = for_speech(text)
        if not text or not self.cfg.get("tts_enabled", True) or self._muted:
            return
        with self.lock:
            self.pending += 1
            gen = self.gen
        self.on_state("speaking")
        self.text_q.put((gen, text))

    def stop(self):
        with self.lock:
            self.gen += 1
            self.pending = 0
            self.play_until = 0
        for q in (self.text_q, self.audio_q):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
        self.audio_q.put(("abort", None, None))
        self.on_state("idle")

    def mute(self, on):
        self._muted = on
        if on:
            self.stop()

    def prewarm(self, phrases, on_done=None):
        """Озвучить заранее (без воспроизведения) готовые реплики ХРАЗа — потом они звучат мгновенно."""
        def run():
            n = 0
            while self.engine is None and self.engine_name is None:
                time.sleep(0.2)
            if self.engine_name != "fish":
                return on_done and on_done(0)
            for p in phrases:
                try:
                    for _ in self.engine(for_speech(p)):
                        pass
                    n += 1
                except Exception:
                    pass
            on_done and on_done(n)
        threading.Thread(target=run, daemon=True).start()

    def busy(self):
        return self.pending > 0 or time.time() < self.play_until + 0.25

    # ---- синтез ---------------------------------------------------------------
    def _init_engine(self):
        wanted = self.cfg.get("tts_engine", "fish")
        order = [wanted] + [e for e in ("piper", "silero", "sapi") if e != wanted]
        errors = []
        for name in order:
            try:
                self.engine = getattr(self, f"_engine_{name}")()
                self.engine_name = name
                self.direct = name == "sapi"
                break
            except Exception as e:
                errors.append(f"{name}: {e}")
        if not self.engine:
            self.on_error("⚠ Озвучка не запустилась — " + "; ".join(errors))
        elif self.engine_name != wanted:
            self.on_error(f"⚠ Голос «{wanted}» не запустился ({errors[0]}). Говорю через {self.engine_name}.")

    def _synth_loop(self):
        self._init_engine()
        while True:
            gen, text = self.text_q.get()
            try:
                if gen == self.gen and self.engine:
                    if self.direct:
                        self.engine(text)
                    else:
                        for chunk, sr in self.engine(text):
                            if gen != self.gen:
                                break
                            self.audio_q.put((gen, chunk, sr))
                elif not self.engine:
                    print("[TTS]", text)
            except Exception as e:
                self.on_error(f"⚠ Ошибка озвучки: {e}")
            self.audio_q.put((gen, "end", None))     # фраза закончена

    # ---- воспроизведение --------------------------------------------------------
    def _play_loop(self):
        try:
            import sounddevice as sd
        except Exception as e:
            self.on_error(f"⚠ Нет вывода звука: {e}")
            return
        stream, stream_sr = None, None
        idle_since = None
        while True:
            try:
                gen, chunk, sr = self.audio_q.get(timeout=0.1)
            except queue.Empty:
                if self.pending == 0 and time.time() >= self.play_until:
                    if idle_since is None:
                        idle_since = time.time()
                        self.on_state("idle")
                    elif stream and time.time() - idle_since > 20:   # долго тихо — освобождаем звуковую карту
                        stream.close()
                        stream = None
                continue
            idle_since = None
            if gen == "abort":
                if stream:
                    stream.abort()
                    stream.close()
                    stream = None
                continue
            if gen != self.gen:
                continue
            if isinstance(chunk, str):                  # "end"
                with self.lock:
                    self.pending = max(0, self.pending - 1)
                continue
            if stream is None or stream_sr != sr:
                if stream:
                    stream.close()
                stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32", latency="low")
                stream.start()
                stream_sr = sr
            now = time.time()
            self.play_until = max(now, self.play_until) + len(chunk) / sr
            stream.write(np.ascontiguousarray(chunk, dtype=np.float32).reshape(-1, 1))

    # ---- движки: каждый — функция text -> генератор (кусок float32, частота) ------------
    def _engine_fish(self):
        import requests
        key = self.cfg.get("fish_api_key") or os.environ.get("FISH_API_KEY", "")
        voice = self.cfg.get("fish_voice_id", "").strip()
        if not key or not voice:
            raise RuntimeError("в Настройках не заданы API-ключ и ID голоса Fish Audio")
        cache = os.path.join(DATA, "models", "fish_cache")
        os.makedirs(cache, exist_ok=True)
        session = requests.Session()          # держим соединение открытым — минус сотни мс на каждой фразе
        try:
            backup = self._engine_piper()
        except Exception:
            backup = None
        sr = 44100
        warned = [False]

        def speak(text):
            path = os.path.join(cache, hashlib.sha1(f"{voice}|{text}".encode()).hexdigest() + ".pcm")
            if os.path.exists(path):
                with open(path, "rb") as f:
                    yield _pcm(f.read()), sr
                return
            got, rest = bytearray(), b""
            try:
                r = session.post("https://api.fish.audio/v1/tts", stream=True, timeout=(5, 60), headers={
                    "Authorization": f"Bearer {key}", "model": self.cfg.get("fish_model", "s1")},
                    json={"text": text, "reference_id": voice, "format": "pcm", "sample_rate": sr,
                          "latency": self.cfg.get("fish_latency", "balanced"), "normalize": True})
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")
                for part in r.iter_content(chunk_size=8820):      # ~0.1 c звука
                    data = rest + part
                    cut = len(data) // 2 * 2
                    rest = data[cut:]
                    if cut:
                        got += data[:cut]
                        a = _pcm(data[:cut])
                        yield (a if not self.cfg.get("fish_fx") else jarvis_fx(a, sr)), sr
            except Exception as e:
                if not got:
                    if not warned[0]:
                        self.on_error(f"⚠ Fish Audio недоступен ({e}). Говорю запасным голосом.")
                        warned[0] = True
                    if backup:
                        yield from backup(text)
                    return
                raise
            if len(text) <= 80 and got:
                with open(path, "wb") as f:
                    f.write(bytes(got))
        return speak

    def _engine_piper(self):
        from piper import PiperVoice
        path = self.cfg.get("piper_voice", "models/piper/ru_RU-dmitri-medium.onnx")
        if not os.path.isabs(path):
            path = resolve(path)
        if not os.path.exists(path):
            raise RuntimeError(f"нет файла голоса {path}")
        voice = PiperVoice.load(path)
        try:
            from piper import SynthesisConfig
            syn = SynthesisConfig(length_scale=float(self.cfg.get("speech_slowness", 1.0)))
        except ImportError:
            syn = None

        def speak(text):
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                voice.synthesize_wav(text, wf, syn_config=syn) if syn else voice.synthesize(text, wf)
            buf.seek(0)
            with wave.open(buf) as wf:
                sr = wf.getframerate()
                a = _pcm(wf.readframes(wf.getnframes()))
            if self.cfg.get("jarvis_fx", True):
                a = jarvis_fx(a, sr)
            yield a, int(sr * float(self.cfg.get("voice_pitch", 0.94)))
        return speak

    def _engine_silero(self):
        import torch
        torch.set_num_threads(4)
        model, _ = torch.hub.load("snakers4/silero-models", "silero_tts", language="ru", speaker="v4_ru",
                                  trust_repo=True)
        speaker = self.cfg.get("silero_speaker", "eugene")

        def speak(text):
            a = model.apply_tts(text=text[:900], speaker=speaker, sample_rate=48000).numpy()
            if self.cfg.get("jarvis_fx", True):
                a = jarvis_fx(a, 48000)
            yield a, int(48000 * float(self.cfg.get("voice_pitch", 0.94)))
        return speak

    def _engine_sapi(self):
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()
        v = comtypes.client.CreateObject("SAPI.SpVoice")
        voices = v.GetVoices()
        for i in range(voices.Count):
            d = voices.Item(i).GetDescription().lower()
            if any(x in d for x in ("russian", "irina", "pavel", "ru-ru", "русск")):
                v.Voice = voices.Item(i)
                break
        else:
            raise RuntimeError("в Windows нет русского голоса SAPI")
        v.Rate = int(self.cfg.get("sapi_rate", 0))
        return lambda text: v.Speak(text)


def _pcm(b):
    return np.frombuffer(b, dtype=np.int16).astype(np.float32) / 32768


def jarvis_fx(a, sr):
    """«Голос машины»: лёгкий металлический призвук + короткие отражения. Без хвоста — чтобы не было пауз."""
    a = np.asarray(a, dtype=np.float32)
    out = a.copy()
    for ms, g in ((9, 0.30), (31, 0.16), (47, 0.11), (71, 0.07)):
        k = int(sr * ms / 1000)
        if k < len(a):
            out[k:] += g * a[:-k]
    peak = float(np.abs(out).max()) or 1.0
    return out / max(peak, 1.0) * 0.95 if peak > 1.0 else out
