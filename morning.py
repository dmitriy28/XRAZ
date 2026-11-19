"""Утренний доклад: погода и напоминания. Каждая часть необязательна:
что не подключено или не ответило — пропускается. Возвращает (markdown для экрана, короткий текст для голоса)."""
import datetime

import actions

DAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря"]


def greeting(now):
    h = now.hour
    return ("Доброй ночи" if h < 5 else "Доброе утро" if h < 12 else "Добрый день" if h < 18 else "Добрый вечер")


def build(brain, now=None):
    now = now or datetime.datetime.now()
    cfg = brain.cfg
    md = [f"## {greeting(now)}, майор. {DAYS[now.weekday()].capitalize()}, {now.day} {MONTHS[now.month - 1]}"]
    spoken = [f"{greeting(now)}, майор."]

    # погода
    try:
        import weather
        w = weather.weather(cfg.get("city", "Москва"), 0)
        md.append(f"**Погода.** {w}")
        spoken.append(w.split(".")[0] + ".")
    except Exception:
        pass

    # напоминания
    pend = actions.pending_timers()
    if pend:
        md.append("**Напоминания:**\n" + "\n".join(
            f"- {datetime.datetime.fromtimestamp(t):%H:%M} — {label}" for t, label in pend[:10]))
        spoken.append(f"Напоминаний на сегодня: {len(pend)}.")
    if len(md) == 1:
        md.append("Источников нет — доклад короткий. Город для погоды — в настройках.")
    return "\n\n".join(md), " ".join(spoken)
