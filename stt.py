"""Офлайн-распознавание Vosk. Выключенный микрофон не читается вовсе: поток закрыт, очередь звука очищена.
Пока ХРАЗ говорит, обычное распознавание не работает (чтобы он не слушал сам себя), но маленький
распознаватель стоп-слов («стоп», «хватит», «замолчи») продолжает слушать — им можно перебить речь.

Слово «ХРАЗ» в словаре Vosk нет — обычный распознаватель слышит «раз», «краз», «образ». Поэтому параллельно
работает второй распознаватель с грамматикой ТОЛЬКО из слов активации: он надёжно ловит «храз / хранитель /
харитон / захаров», и фраза помечается как обращённая к ХРАЗу.

Необязательный Whisper (stt_engine = "whisper", пакет faster-whisper): Vosk по-прежнему слушает постоянно — он ловит слово активации,
стоп-слова и определяет, где кончилась фраза, — а текст готовой фразы перераспознаёт Whisper (точнее, с пунктуацией и цифрами).
Если Whisper не установлен, ещё грузится, ошибся или выдал «галлюцинацию» на шуме — берётся текст Vosk, ничего не теряется."""
import collections
import json
import math
import os
import queue
import re
import struct
import threading
import time

SPOT_WORDS = ["храз", "хранитель", "харитон", "захаров", "раз", "краз"]   # «раз/краз» — так Vosk пишет «храз»
STOP_WORDS = ["стоп", "хватит", "замолчи", "храз стоп", "тихо"]


# ---------------------------------------------------------------- Whisper (необязательно)
CHUNK_SEC = 0.25                    # блок звука в цикле: 4000 отсчётов при 16 кГц
MAX_CHUNKS = 120                    # хранится не больше 30 секунд последней фразы
HALLU = re.compile(r"субтитр|продолжение следует|спасибо за просмотр|подписывайтесь|редактор субтитров|корректор|dimatorzok|"
                   r"thanks for watching", re.I)


def rms(data):
    """Громкость блока int16 (0…32768)."""
    n = len(data) // 2
    if n == 0:
        return 0.0
    vals = struct.unpack(f"<{n}h", data[:n * 2])
    return math.sqrt(sum(v * v for v in vals) / n)


def trim_utterance(chunks, pre=2):
    """chunks — [(байты, громкость)] с конца прошлой фразы. Отбрасывает тишину в начале (оставляя `pre` блоков до первого голоса)
    и возвращает байты фразы либо b"", если голоса не было."""
    if not chunks:
        return b""
    loud = sorted(r for _, r in chunks)
    floor = loud[len(loud) // 5]                                  # шумовой пол — 20-й процентиль
    thr = max(120.0, floor * 3)
    first = next((i for i, (_, r) in enumerate(chunks) if r > thr), None)
    if first is None:
        if loud[-1] > 120.0:                                      # весь буфер ровно громкий (фон/сплошная речь) — отдаём как есть
            return b"".join(d for d, _ in chunks)
        return b""
    return b"".join(d for d, _ in chunks[max(0, first - pre):])


def looks_hallucinated(whisper, vosk):
    """Whisper на шуме и коротких обрывках выдаёт «субтитры» и повторы; сверяем с тем, что услышал Vosk."""
    t = whisper.strip()
    if not t or HALLU.search(t):
        return True
    if len(t) > 3 * len(vosk) + 40:                               # намного длиннее, чем слышал Vosk
        return True
    words = t.lower().split()
    return len(words) >= 6 and len(set(words)) <= 2               # «да да да да да да»


class WhisperEngine:
    """Обёртка над faster-whisper. Модель грузится в фоне (первый запуск скачивает её); пока не готова — работает Vosk.
    Видеокарта (device=auto → cuda, при ошибке — процессор); модель по умолчанию «small» (~0,5 ГБ), чтобы не мешать Ollama."""

    def __init__(self, cfg, note=None):
        self.cfg, self.note = cfg, note or (lambda t: None)
        self.model, self.device, self.failed = None, "", ""
        self._lock = threading.Lock()
        self.loading = False

    @property
    def ready(self):
        return self.model is not None

    def _fail(self, why):
        self.failed = why
        self.note(f"⚠ Whisper недоступен: {why}. Распознаю через Vosk.")

    def load(self):
        with self._lock:
            if self.model or self.failed:
                return
            self.loading = True
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                self.loading = False
                return self._fail("не установлен пакет faster-whisper (pip install faster-whisper)")
            import config
            name = self.cfg.get("whisper_model") or "small"
            dev = self.cfg.get("whisper_device") or "auto"
            comp = self.cfg.get("whisper_compute") or "auto"
            tries = [("cuda", "float16"), ("cpu", "int8")] if dev == "auto" else [(dev, "float16" if dev == "cuda" else "int8")]
            if comp != "auto":
                tries = [(d, comp) for d, _ in tries]
            err = None
            for d, c in tries:
                try:
                    self.model = WhisperModel(name, device=d, compute_type=c,
                                              download_root=config.resolve(self.cfg.get("whisper_dir") or "models/whisper"))
                    self.device = d
                    break
                except Exception as e:                           # noqa: BLE001
                    err = e
            self.loading = False
            if not self.model:
                return self._fail(f"модель «{name}» не загрузилась ({err})")
            self.note(f"Whisper «{name}» готов ({'видеокарта' if self.device == 'cuda' else 'процессор'}): распознавание речи точнее.")

    def transcribe(self, pcm):
        import numpy as np
        return self._guarded(np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0)

    def transcribe_file(self, path):
        """Файл любого формата (.oga/.ogg и др.): faster-whisper сам декодирует его через PyAV."""
        return self._guarded(path)

    def _guarded(self, audio):
        try:
            return self._run(audio)
        except Exception as e:                                   # noqa: BLE001
            msg = (str(e) + type(e).__name__).lower()
            if self.device == "cuda" and any(k in msg for k in ("cuda", "cublas", "cudnn")):
                self.model, self.failed = None, ""               # библиотек CUDA нет — переходим на процессор
                self.cfg = dict(self.cfg, whisper_device="cpu")
                self.load()
                if self.model:
                    return self._run(audio)
            raise

    def _run(self, audio):
        segs, _ = self.model.transcribe(audio, language="ru", beam_size=int(self.cfg.get("whisper_beam", 1)), vad_filter=False,
                                        condition_on_previous_text=False, temperature=0.0, no_speech_threshold=0.6,
                                        initial_prompt=self.cfg.get("whisper_prompt") or None)
        out = []
        for sg in segs:
            if getattr(sg, "no_speech_prob", 0) > 0.6 and getattr(sg, "avg_logprob", 0) < -1.0:
                continue
            out.append(sg.text.strip())
        return re.sub(r"\s+", " ", " ".join(out)).strip()


class STT:
    def __init__(self, cfg, on_final, on_partial=None, is_muted=lambda: False, on_stop=None):
        self.cfg = cfg
        self.on_stop = on_stop              # перебивание речи голосом
        self.on_final = on_final            # on_final(text, spotted: bool)
        self.on_partial = on_partial or (lambda t: None)
        self.is_muted = is_muted
        self.enabled = threading.Event()
        self.enabled.set()
        self.error = None
        self._spot_time = 0.0
        self.on_note = None                 # сообщение пользователю (например, «Whisper готов»); ставит интерфейс
        self.whisper = None
        self.last_engine = "vosk"           # чем распознана последняя фраза: vosk / whisper

    def _note(self, text):
        print(text)
        if self.on_note:
            self.on_note(text)

    def start(self):
        path = self.cfg["vosk_model_abs"]
        if not os.path.isdir(path):
            self.error = f"Нет модели Vosk: {path}. Скачиваю автоматически…"
            return False
        if self.cfg.get("stt_engine") == "whisper" and self.whisper is None:
            self.whisper = WhisperEngine(self.cfg, note=self._note)
            threading.Thread(target=self.whisper.load, daemon=True, name="khraz-whisper").start()
        threading.Thread(target=self._loop, daemon=True).start()
        return True

    def refine(self, vosk_text, chunks):
        """Текст готовой фразы: Whisper, если он готов и не «галлюцинирует», иначе Vosk (ничего не теряется)."""
        self.last_engine = "vosk"
        w = self.whisper
        if not w or not w.ready or not chunks:
            return vosk_text
        pcm = trim_utterance(chunks)
        if len(pcm) < 16000 * 2 * 0.4:                                   # короче 0,4 с — это не фраза
            return vosk_text
        try:
            text = w.transcribe(pcm)
        except Exception as e:                                           # noqa: BLE001
            print("Whisper:", e)
            return vosk_text
        if looks_hallucinated(text, vosk_text):
            return vosk_text
        self.last_engine = "whisper"
        return text

    def _make_spotter(self, model, rate):
        if not self.cfg.get("wake_spotter", True):
            return None
        from vosk import KaldiRecognizer
        try:
            return KaldiRecognizer(model, rate, json.dumps(SPOT_WORDS + ["[unk]"], ensure_ascii=False))
        except Exception as e:
            print("wake-споттер недоступен:", e)
            return None

    def _check_spot(self, text):
        words = text.split()
        if words and words[0] in ("храз", "хранитель", "харитон", "захаров"):
            self._spot_time = time.time()

    def _loop(self):
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model, SetLogLevel
            SetLogLevel(-1)
            model = Model(self.cfg["vosk_model_abs"])
            rate = 16000
            rec = KaldiRecognizer(model, rate)
            spot = self._make_spotter(model, rate)
            stopper = None
            if self.on_stop and self.cfg.get("barge_in", True):
                try:
                    stopper = KaldiRecognizer(model, rate, json.dumps(STOP_WORDS + ["[unk]"], ensure_ascii=False))
                except Exception:
                    stopper = None
            q = queue.Queue()

            def cb(indata, frames, t, status):
                q.put(bytes(indata))

            stream = None
            chunks = collections.deque(maxlen=MAX_CHUNKS)        # звук текущей фразы (для Whisper)
            while True:
                if not self.enabled.is_set():          # микрофон выключен — поток закрыт, звук не читается
                    if stream:
                        stream.stop(); stream.close(); stream = None
                        rec.Reset()
                        spot and spot.Reset()
                        chunks.clear()
                        while not q.empty():           # старый звук после включения не распознаётся
                            q.get_nowait()
                    self.enabled.wait()
                    continue
                if stream is None:
                    stream = sd.RawInputStream(samplerate=rate, blocksize=4000, dtype="int16", channels=1,
                                               device=self.cfg.get("mic_device"), callback=cb)
                    stream.start()
                try:
                    data = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if self.is_muted():
                    chunks.clear()
                    rec.Reset()
                    spot and spot.Reset()
                    if stopper and stopper.AcceptWaveform(data):
                        heard = json.loads(stopper.Result()).get("text", "")
                        if any(w in heard.split() for w in ("стоп", "хватит", "замолчи", "тихо")):
                            self.on_stop()
                    continue
                stopper and stopper.Reset()
                if self.whisper:
                    chunks.append((data, rms(data)))
                if spot:
                    if spot.AcceptWaveform(data):
                        self._check_spot(json.loads(spot.Result()).get("text", ""))
                    else:
                        self._check_spot(json.loads(spot.PartialResult()).get("partial", ""))
                if rec.AcceptWaveform(data):
                    text = json.loads(rec.Result()).get("text", "").strip()
                    if text:
                        text = self.refine(text, list(chunks))
                        spotted = time.time() - self._spot_time < 6
                        self._spot_time = 0.0
                        chunks.clear()
                        self.on_final(text, spotted)
                    else:
                        chunks.clear()
                else:
                    p = json.loads(rec.PartialResult()).get("partial", "")
                    if p:
                        self.on_partial(p)
        except Exception as e:
            self.error = f"Микрофон/Vosk: {e}"
            print(self.error)
