"""ХРАЗ начинает разговор сам: следит за делами в фоне и сообщает о важном.

- утренний доклад в заданное время (раз в день);
- наблюдение за экраном по просьбе («наблюдай за экраном»): заметил ошибку — говорит.
Одинаковое не повторяет (память событий в watch_state.json). Ночью (тихие часы) — только текстом, без голоса.
"""
import datetime
import hashlib
import json
import os
import re
import threading
import time

from config import DATA

STATE = os.path.join(DATA, "watch_state.json")


def _hm(s):
    h, m = map(int, s.split(":"))
    return h * 60 + m


def in_quiet(cfg, now=None):
    rng = (cfg.get("quiet_hours") or "").strip()
    if not re.fullmatch(r"\d{1,2}:\d\d-\d{1,2}:\d\d", rng):
        return False
    a, b = map(_hm, rng.split("-"))
    now = now or datetime.datetime.now()
    m = now.hour * 60 + now.minute
    return (a <= m < b) if a < b else (m >= a or m < b)


class Watcher:
    def __init__(self, brain, path=None):
        self.b = brain
        self.path = path or STATE
        self.lock = threading.Lock()
        self.state = {"seen": {}, "morning": ""}
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.state.update(json.load(f))
            except Exception:
                pass
        self._stop = threading.Event()
        self._thread = None
        self.screen_until = 0.0
        self._screen_thread = None

    @property
    def cfg(self):
        return self.b.cfg

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def once(self, key, ttl_hours=24):
        """True — событие новое (и запоминаем его), False — уже сообщали."""
        now = time.time()
        with self.lock:
            seen = {k: v for k, v in self.state["seen"].items() if now - v < 7 * 86400}
            if key in seen and now - seen[key] < ttl_hours * 3600:
                self.state["seen"] = seen
                return False
            seen[key] = now
            self.state["seen"] = seen
            self._save()
        return True

    def forget(self, prefix):
        with self.lock:
            self.state["seen"] = {k: v for k, v in self.state["seen"].items() if not k.startswith(prefix)}
            self._save()

    # ---- цикл ---------------------------------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.screen_until = 0.0

    def _loop(self):
        self._stop.wait(20)                         # дать приложению подняться
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:
                import errors
                errors.log.warning("watcher: %s", e)
            self._stop.wait(max(60, int(self.cfg.get("watch_interval_min", 5)) * 60))

    def tick(self, now=None):
        """Одна проверка всего (вызывается и тестами). Возвращает список отправленных сообщений."""
        if not self.cfg.get("proactive", True):
            return []
        now = now or datetime.datetime.now()
        sent = []
        sent += self.check_morning(now)
        sent += self.check_rules(now)
        return sent

    # ---- правила по расписанию (scheduler.py) ------------------------------------------------
    def check_rules(self, now):
        import scheduler
        import tools
        sent = []
        for r in scheduler.due(now):
            title = r["title"]
            if not r.get("tool"):
                sent.append(self.alert(f"Напоминание по правилу «{title}»: {r.get('say') or title}"))
                continue
            try:
                t = tools.REGISTRY[r["tool"]]
                risk = t.risk_for(r.get("args") or {})
            except (KeyError, Exception):
                sent.append(self.alert(f"Правило «{title}»: инструмента {r['tool']} больше нет."))
                continue
            if risk != "read":      # без человека ничего не меняем: карточка подтверждения
                sent.append(self.alert(f"По правилу «{title}» предлагаю: {t.describe(r.get('args') or {})}",
                                       spoken=f"По правилу «{title}» есть предложение. Подтвердите в окне.",
                                       offer=(r["tool"], r.get("args") or {})))
                continue
            try:
                res = tools.call(r["tool"], r.get("args") or {}, self.b, via="rule")
                text = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False, default=str)
                import reports
                reports.save(self.cfg, "rule", title, text)
                sent.append(self.alert(f"По правилу «{title}»:\n{text[:1500]}", spoken=f"Правило «{title}» выполнено, "
                                                                                        "результат в окне."))
            except tools.NeedsConfirm:
                sent.append(self.alert(f"Правило «{title}» требует подтверждения: {r['tool']}"))
            except Exception as e:          # noqa: BLE001
                sent.append(self.alert(f"Правило «{title}» не выполнено: {e}"))
        return sent

    # ---- утренний доклад ----------------------------------------------------------------
    def check_morning(self, now):
        t = (self.cfg.get("morning_time") or "").strip()
        if not re.fullmatch(r"\d{1,2}:\d\d", t):
            return []
        today = now.strftime("%Y-%m-%d")
        if self.state.get("morning") == today or now.hour * 60 + now.minute < _hm(t):
            return []
        if now.hour * 60 + now.minute > _hm(t) + 180:     # ХРАЗ запустили днём — доклад не навязываем
            self.state["morning"] = today
            self._save()
            return []
        self.state["morning"] = today
        self._save()
        self.b.q.put(("__morning__", None, None))
        return ["morning"]

    # ---- экран ------------------------------------------------------------------------------
    def watch_screen(self, minutes=30):
        self.screen_until = time.time() + minutes * 60
        if self._screen_thread and self._screen_thread.is_alive():
            return
        self._screen_thread = threading.Thread(target=self._screen_loop, daemon=True)
        self._screen_thread.start()

    def stop_screen(self):
        self.screen_until = 0.0

    @property
    def screen_on(self):
        return time.time() < self.screen_until

    def _screen_loop(self):
        import khraz_tools
        last = ""
        while self.screen_on:
            try:
                img = khraz_tools.screenshot_b64(max_side=1100)
                ans = self.b.llm.vision(SCREEN_PROMPT, img, max_tokens=160)
                found = parse_screen(ans)
                if found and found != last:
                    last = found
                    self.alert(f"На экране вижу проблему: {found}", spoken="Майор, на экране ошибка. Подробности в окне.",
                               offer=None)
            except Exception:
                pass
            for _ in range(int(self.cfg.get("screen_watch_sec", 20))):
                if not self.screen_on:
                    break
                time.sleep(1)
        self.b._emit("action", "")

    # ---- вывод ---------------------------------------------------------------------------------
    def alert(self, text, spoken=None, offer=None):
        quiet = in_quiet(self.cfg)
        self.b.proactive(text, spoken=None if quiet else (spoken or text), offer=offer)
        return text


SCREEN_PROMPT = ("Это снимок экрана программиста. Есть ли на нём явная ошибка: сообщение об ошибке, traceback, "
                 "исключение, красный текст ошибки в терминале или IDE, окно «не удалось»? Ответь строго JSON: "
                 '{"error": true/false, "what": "кратко по-русски: что за ошибка и где"}')


def parse_screen(ans):
    m = re.search(r"\{.*\}", ans or "", re.S)
    if not m:
        return ""
    try:
        d = json.loads(m.group())
    except ValueError:
        return ""
    return (d.get("what") or "ошибка").strip()[:300] if d.get("error") is True else ""


def digest(text):
    return hashlib.sha1(text.encode()).hexdigest()[:10]
