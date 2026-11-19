"""Правила по расписанию: «каждое воскресенье в 20:00 пришли отчёт о системе», «каждые 2 часа проверяй диск».

Правило = расписание + (инструмент с аргументами | текст напоминания). Хранятся в rules.json.
Выполняет watcher.check_rules:
- инструмент только чтения — выполняется сразу, результат ХРАЗ сообщает сам;
- любой другой (изменение, удаление, действие) — НЕ выполняется молча: приходит карточка подтверждения, как у
  предложений ХРАЗа. Без человека изменения не происходят никогда.
Форматы расписания: `daily 20:00` · `weekly sun 20:00` · `every 120m`."""
import datetime
import json
import os
import re
import threading
import time

from config import DATA

PATH = os.path.join(DATA, "rules.json")
SCHEDULE_RE = r"(daily \d{1,2}:\d\d|weekly (mon|tue|wed|thu|fri|sat|sun) \d{1,2}:\d\d|every \d{1,4}m)"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAYS_RU = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
CATCH_UP_MIN = 180          # приложение запущено позже срока больше чем на 3 часа — пропускаем до следующего раза
MAX_RULES = 30
_lock = threading.Lock()


def load(path=None):
    try:
        with open(path or PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save(rules, path=None):
    p = path or PATH
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def parse(schedule):
    """('daily', минуты) | ('weekly', день, минуты) | ('every', минуты) или ValueError."""
    s = (schedule or "").strip().lower()
    if not re.fullmatch(SCHEDULE_RE, s):
        raise ValueError("расписание: `daily 20:00`, `weekly sun 20:00` или `every 120m`")
    parts = s.split()
    if parts[0] == "every":
        n = int(parts[1][:-1])
        if n < 5:
            raise ValueError("чаще чем раз в 5 минут нельзя")
        return ("every", n)
    h, m = map(int, parts[-1].split(":"))
    if h > 23 or m > 59:
        raise ValueError("время вида 20:00")
    if parts[0] == "daily":
        return ("daily", h * 60 + m)
    return ("weekly", DAYS.index(parts[1]), h * 60 + m)


def describe_schedule(schedule):
    p = parse(schedule)
    if p[0] == "every":
        return f"каждые {p[1]} мин" if p[1] < 120 or p[1] % 60 else f"каждые {p[1] // 60} ч"
    hm = f"{p[-1] // 60:02d}:{p[-1] % 60:02d}"
    return f"каждый день в {hm}" if p[0] == "daily" else f"каждую неделю, {DAYS_RU[p[1]]}, в {hm}"


def is_due(rule, now):
    """Пора ли запускать правило. last — метка последнего запуска (ISO) или созданное время."""
    p = parse(rule["schedule"])
    last = datetime.datetime.fromisoformat(rule.get("last") or rule["created"])
    if p[0] == "every":
        return (now - last).total_seconds() >= p[1] * 60
    minutes = now.hour * 60 + now.minute
    if p[0] == "weekly" and now.weekday() != p[1]:
        return False
    if minutes < p[-1] or minutes > p[-1] + CATCH_UP_MIN:
        return False
    return rule.get("last_day") != now.strftime("%Y-%m-%d")


def due(now=None, path=None):
    now = now or datetime.datetime.now()
    out = []
    with _lock:
        rules = load(path)
        for r in rules:
            if not r.get("enabled", True):
                continue
            try:
                if is_due(r, now):
                    r["last"] = now.isoformat(timespec="seconds")
                    r["last_day"] = now.strftime("%Y-%m-%d")
                    out.append(dict(r))
            except (ValueError, KeyError):
                continue
        if out:
            save(rules, path)
    return out


def add(title, schedule, tool=None, args=None, say=None, path=None):
    parse(schedule)
    if not tool and not say:
        raise ValueError("нужен инструмент или текст напоминания")
    with _lock:
        rules = load(path)
        if len(rules) >= MAX_RULES:
            raise ValueError(f"правил уже {MAX_RULES} — удалите ненужные")
        rid = "r" + str(int(time.time() * 1000))[-8:]
        rule = {"id": rid, "title": title.strip()[:80], "schedule": schedule.strip().lower(), "tool": tool or "",
                "args": args or {}, "say": (say or "").strip()[:300], "enabled": True,
                "created": datetime.datetime.now().isoformat(timespec="seconds"), "last": "", "last_day": ""}
        rules.append(rule)
        save(rules, path)
    return rule


def delete(key, path=None):
    """Удалить по id или по части названия (только если подходит ровно одно правило)."""
    with _lock:
        rules = load(path)
        k = (key or "").strip().lower()
        hit = [r for r in rules if r["id"] == k] or [r for r in rules if k and k in r["title"].lower()]
        if len(hit) != 1:
            raise ValueError("правило не найдено" if not hit else
                             "подходит несколько правил: " + ", ".join(f"{r['id']} «{r['title']}»" for r in hit))
        rules.remove(hit[0])
        save(rules, path)
    return hit[0]
