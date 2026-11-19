"""Таймеры и напоминания (живут, пока работает ХРАЗ)."""
import datetime

import actions

from . import ToolError, tool

TIMER = {"type": "object", "properties": {
    "seconds": {"type": "integer", "minimum": 1, "maximum": 86400, "description": "длительность в секундах"},
    "label": {"type": "string", "maxLength": 80, "description": "подпись, необязательно"}},
    "required": ["seconds"], "additionalProperties": False}

REMIND = {"type": "object", "properties": {
    "text": {"type": "string", "minLength": 1, "maxLength": 200, "description": "о чём напомнить"},
    "in_minutes": {"type": "integer", "minimum": 1, "maximum": 10080, "description": "через сколько минут"},
    "at": {"type": "string", "pattern": r"([01]?\d|2[0-3]):[0-5]\d", "description": "или во сколько, ЧЧ:ММ"}},
    "required": ["text"], "additionalProperties": False}


@tool("set_timer", "Поставить таймер.", TIMER, risk="action", summary=lambda a: f"Таймер на {a['seconds']} с")
def set_timer(ctx, seconds, label=""):
    import persona
    msg = f"Таймер «{label}»: время вышло." if label else persona.say("timer_done")
    actions._start_timer(seconds, lambda: ctx.notify(msg), label or "таймер")
    return f"Таймер на {actions._human(seconds)}" + (f" ({label})" if label else "")


@tool("set_reminder", "Поставить напоминание: через N минут (in_minutes) или к времени (at).", REMIND,
      risk="action", summary=lambda a: f"Напомнить «{a['text']}»")
def set_reminder(ctx, text, in_minutes=None, at=None):
    now = datetime.datetime.now()
    if at:
        h, m = map(int, at.split(":"))
        when = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if when <= now:
            when += datetime.timedelta(days=1)
        seconds = int((when - now).total_seconds())
        human = f"в {when:%H:%M}"
    elif in_minutes:
        seconds = in_minutes * 60
        human = f"через {actions._human(seconds)}"
    else:
        raise ToolError("укажите, когда напомнить: через сколько минут или во сколько")
    actions._start_timer(seconds, lambda: ctx.notify(f"Напоминаю: {text}."), text)
    return f"Напомню {human}: {text}"
