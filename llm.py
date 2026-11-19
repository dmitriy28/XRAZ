"""Клиент Ollama: потоковый чат, инструменты, JSON по схеме, эмбеддинги — и управление моделями.

Моделей несколько (router.py выбирает), но в видеопамяти одновременно держится только одна крупная:
перед запросом к другой крупной модели предыдущая выгружается (keep_alive: 0). Эмбеддинги (bge-m3) маленькие
и в счёт не идут. Внутренние рассуждения моделей (think / <think>) никогда не показываются и не озвучиваются."""
import json
import re
import threading
import time

import requests


class Cancelled(Exception):
    """Пользователь нажал «СТОП». partial — то, что модель успела написать."""
    def __init__(self, partial=""):
        super().__init__("остановлено")
        self.partial = partial


class ModelMissing(RuntimeError):
    """В Ollama нет нужной модели — errors.py покажет точную команду ollama pull."""
    def __init__(self, model):
        super().__init__(f"модель {model} не установлена")
        self.model = model


class LLM:
    def __init__(self, cfg):
        self.cfg = cfg
        self._think_ok = True   # поддерживает ли сервер параметр think
        self.cancel = threading.Event()
        self._sessions = set()
        self._streams = set()
        self._lock = threading.Lock()
        self._model_lock = threading.Lock()
        self.current = None          # крупная модель, которую мы держим загруженной
        self.last_done_reason = ""   # "length" — ответ упёрся в лимит, можно «продолжить»
        self.on_model = None         # колбэк интерфейса: (модель, состояние)
        self.on_fallback = False     # основной Ollama (ноутбук с RTX) недоступен — работаем на запасном (слабый ПК)
        self._probe_at = 0.0

    # ---- остановка ------------------------------------------------------------------
    def begin(self):
        """Новый запрос пользователя — сбрасываем прошлый «СТОП»."""
        self.cancel.clear()

    def stop(self):
        """Кнопка «СТОП»: рвём соединения с Ollama — она прекращает генерацию, ожидание прерывается."""
        self.cancel.set()
        with self._lock:
            sessions, streams = list(self._sessions), list(self._streams)
        for r in streams:                       # блокирующее чтение потока — обрываем сокет
            try:
                import socket
                r.raw._connection.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
        for sess in sessions:
            try:
                sess.close()
            except Exception:
                pass

    def _check(self, partial=""):
        if self.cancel.is_set():
            raise Cancelled(partial)

    # ---- сервер и модели ----------------------------------------------------------
    @property
    def url(self):
        main = self.cfg["ollama_url"].rstrip("/")
        fb = (self.cfg.get("ollama_url_fallback") or "").rstrip("/")
        if not fb:
            return main
        now = time.time()
        if now - self._probe_at > 15:           # основной проверяем раз в 15 с, ожидание не дольше 0.8 с
            self._probe_at = now
            try:
                requests.get(main + "/api/version", timeout=0.8)
                down = False
            except Exception:
                down = True
            if down != self.on_fallback:
                self.on_fallback = down
                if self.on_model:
                    self.on_model(self.cfg.get("model_fallback") if down else self.cfg["model"],
                                  "fallback" if down else "ready")
        return fb if self.on_fallback else main

    def version(self, timeout=2):
        """Версия Ollama или None, если сервер не отвечает."""
        try:
            return requests.get(self.url + "/api/version", timeout=timeout).json().get("version") or "?"
        except Exception:
            return None

    def models(self):
        try:
            r = requests.get(self.url + "/api/tags", timeout=3)
            return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []

    def loaded(self):
        """Модели, которые сейчас в памяти Ollama (/api/ps)."""
        try:
            return [m["name"] for m in requests.get(self.url + "/api/ps", timeout=3).json().get("models", [])]
        except Exception:
            return []

    def roles(self):
        c = self.cfg
        return {"fast": c["model"], "smart": c.get("model_smart"), "code": c.get("model_code")}

    def _is_large(self, model):
        return bool(model) and model != self.cfg.get("embed_model")

    def unload(self, model):
        try:
            requests.post(self.url + "/api/generate", json={"model": model, "keep_alive": 0}, timeout=15)
        except Exception:
            pass

    def ensure(self, model):
        """Перед запросом: если загружена другая крупная модель из наших — выгружаем её."""
        if not self._is_large(model):
            return
        with self._model_lock:
            if self.current == model:
                return
            ours = {m for m in self.roles().values() if m} | {self.cfg.get("vision_model")}
            for m in self.loaded():
                if m != model and (m in ours or _same(m, ours)) and self._is_large(m):
                    self.unload(m)
            self.current = model
        if self.on_model:
            self.on_model(model, "loading")

    def keep_alive(self, model):
        return self.cfg.get("keep_alive", "30m") if model == self.cfg["model"] else self.cfg.get("keep_alive_large", "5m")

    def _body(self, messages, **extra):
        model = extra.pop("model", None) or self.cfg["model"]
        self.url                                  # обновляет on_fallback
        if (self.on_fallback and self._is_large(model) and self.cfg.get("model_fallback")
                and not any(m.get("images") for m in messages)):
            model = self.cfg["model_fallback"]    # на слабом ПК любая роль → одна лёгкая модель
        opts = dict(extra.pop("options", {}) or {})
        # личность ~4 тыс. токенов; одинаковый num_ctx для модели — иначе Ollama перезагружает её каждый раз
        opts.setdefault("num_ctx", int(self.cfg.get("num_ctx", 16384)))
        body = {"model": model, "messages": messages, "keep_alive": self.keep_alive(model), "options": opts, **extra}
        if self._think_ok:
            # gpt-oss думает всегда (уровни low/medium/high) — берём минимальный; остальным рассуждения выключаем
            body["think"] = "low" if "gpt-oss" in model else False
        return body

    def _post(self, body, stream):
        self.ensure(body["model"])
        if not stream:
            r = self._post_waiting(body)
            if self.on_model:
                self.on_model(body["model"], "ready")
            return r
        return self._post_raw(body, stream)

    def _post_waiting(self, body):
        """Ответ без потока приходит целиком — ждём его в отдельном потоке, чтобы «СТОП» срабатывал сразу."""
        box = {}
        done = threading.Event()

        def work():
            try:
                box["r"] = self._post_raw(body, False)
            except BaseException as e:      # noqa: BLE001
                box["e"] = e
            done.set()
        threading.Thread(target=work, daemon=True).start()
        while not done.wait(0.1):
            self._check()
        self._check()
        if "e" in box:
            raise box["e"]
        return box["r"]

    def _post_raw(self, body, stream, path="/api/chat"):
        self._check()
        sess = requests.Session()
        with self._lock:
            self._sessions.add(sess)
        try:
            r = sess.post(self.url + path, json=body, stream=stream, timeout=300)
            if r.status_code == 400 and "think" in body:
                self._think_ok = False
                body.pop("think")
                r = sess.post(self.url + path, json=body, stream=stream, timeout=300)
            if r.status_code == 404:
                raise ModelMissing(body.get("model"))
            r.raise_for_status()
            if not stream:
                r.content                       # дочитываем, пока сессия жива
            r.khraz_session = sess              # потоковый ответ закрывает сессию сам (chat)
            return r
        except BaseException:
            if stream:
                self._release(sess)
            self._check()                       # оборвали кнопкой — это не ошибка Ollama
            raise
        finally:
            if not stream:
                self._release(sess)

    def _release(self, sess):
        with self._lock:
            self._sessions.discard(sess)
        try:
            sess.close()
        except Exception:
            pass

    def _no_think(self, messages, model):
        """qwen3*: мягкий переключатель /no_think — работает даже на старой Ollama без параметра think."""
        if "qwen3" not in (model or "").lower():
            return messages
        msgs = [dict(m) for m in messages]
        for m in reversed(msgs):
            if m["role"] == "user":
                m["content"] += " /no_think"
                break
        return msgs

    # ---- запросы ----------------------------------------------------------------------
    def chat(self, messages, on_token=None, max_tokens=None, model=None, on_thinking=None):
        model = model or self.cfg["model"]
        opts = {"num_predict": int(max_tokens or self.cfg.get("max_tokens_short", 400)), "temperature": 0.6}
        r = self._post(self._body(self._no_think(messages, model), model=model, stream=True, options=opts), stream=True)
        if self.on_model:
            self.on_model(model, "ready")
        sess = r.khraz_session
        with self._lock:
            self._streams.add(r)
        raw, sent, thinking_seen = "", 0, False
        self.last_done_reason = ""
        try:
            for line in r.iter_lines(chunk_size=None):   # без буфера 512 байт — токены сразу
                self._check(_visible(raw).strip())
                if not line:
                    continue
                data = json.loads(line)
                msg = data.get("message", {})
                if msg.get("thinking") and not thinking_seen and on_thinking:
                    thinking_seen = True             # само рассуждение не показываем — только статус
                    on_thinking()
                raw += msg.get("content", "")
                visible = _visible(raw)
                if len(visible) > sent:
                    if on_token:
                        on_token(visible[sent:])
                    sent = len(visible)
                if data.get("done"):
                    self.last_done_reason = data.get("done_reason", "")
                    break
        except Cancelled:
            raise
        except Exception:
            self._check(_visible(raw).strip())
            raise
        finally:
            with self._lock:
                self._streams.discard(r)
            self._release(sess)
        return _visible(raw).strip()

    def vision(self, prompt, image_b64, system=None, max_tokens=500):
        """Вопрос по картинке. По умолчанию — основная модель (qwen3.5 понимает изображения)."""
        model = self.cfg.get("vision_model") or self.cfg["model"]
        msgs = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt, "images": [image_b64]}]
        body = self._body(msgs, model=model, stream=False, options={"num_predict": max_tokens, "temperature": 0.2})
        r = self._post(body, stream=False)
        return _visible(r.json().get("message", {}).get("content", "")).strip()

    def chat_tools(self, messages, tools, max_tokens=None, model=None):
        """Один шаг агента: модель отвечает текстом или запросом инструментов (Ollama tool calling).
        Возвращает (text, [(name, args_dict), ...])."""
        model = model or self.cfg["model"]
        opts = {"num_predict": int(max_tokens or 900), "temperature": 0.2}
        body = self._body(self._no_think(messages, model), model=model, stream=False, options=opts)
        if tools:
            body["tools"] = tools
        r = self._post(body, stream=False)
        msg = r.json().get("message", {}) or {}
        calls = []
        for c in msg.get("tool_calls") or []:
            f = c.get("function", {})
            args = f.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {"_raw": args}
            calls.append((f.get("name", ""), args))
        return _visible(msg.get("content", "") or "").strip(), calls

    def json(self, messages, schema, model=None):
        model = model or self.cfg["model"]
        r = self._post(self._body(self._no_think(messages, model), model=model, stream=False, format=schema,
                                  options={"temperature": 0}), stream=False)
        text = r.json().get("message", {}).get("content", "")
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        try:
            return json.loads(text)
        except Exception:
            m = re.search(r"\{.*\}", text, re.S)
            return json.loads(m.group()) if m else {}

    def embed(self, texts, timeout=60):
        """Векторы bge-m3 для поиска по памяти. Модель маленькая — крупную не выгружаем."""
        model = self.cfg.get("embed_model", "bge-m3")
        t0 = time.time()
        r = requests.post(self.url + "/api/embed", json={"model": model, "input": list(texts),
                                                         "keep_alive": self.cfg.get("keep_alive", "30m")},
                          timeout=timeout)
        if r.status_code == 404:
            raise ModelMissing(model)
        r.raise_for_status()
        self.last_embed_ms = int((time.time() - t0) * 1000)
        return r.json().get("embeddings") or []


def _same(name, names):
    """qwen3.5:9b и qwen3.5:9b-q4_K_M — одна и та же модель для целей выгрузки."""
    base = name.split(":")[0]
    return any(n and n.split(":")[0] == base and name.startswith(n) for n in names)


def _visible(raw):
    """Текст без блоков <think>…</think>; незакрытый <think> прячет всё после себя.
    Пока тег может быть недописан (токены приходят кусками) — придерживаем хвост."""
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
    i = text.find("<think>")
    if i != -1:
        text = text[:i]
    if text.lstrip() == "" and "</think>" in raw and "<think>" not in raw:
        text = raw.split("</think>", 1)[1]           # шаблон без открывающего тега
    elif "</think>" in text:
        text = text.split("</think>", 1)[1]
    for k in range(1, 8):                            # «<thi» в конце — ждём следующий токен
        if text.endswith("<think>"[:k]):
            return text[:-k].lstrip()
    return text.lstrip()
