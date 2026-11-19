"""Инструменты ХРАЗа без MCP и без shell.

Каждый инструмент — отдельная Python-функция с JSON-схемой аргументов. Реестр:
- отдаёт модели схемы (Ollama tool calling);
- проверяет аргументы по схеме до вызова (типы, диапазоны, перечисления, шаблоны, лишние поля);
- не выполняет изменение и удаление данных без подтверждения (risk change/delete → NeedsConfirm);
- пишет каждый вызов в журнал logs/tools.jsonl (что, с какими аргументами, итог, длительность).
Произвольных команд нет: системные команды — только из белого списка (tools/system.py)."""
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field

from config import DATA

LOG_PATH = os.path.join(DATA, "logs", "tools.jsonl")
RISKS = ("read", "action", "create", "change", "delete")
CONFIRM_RISKS = {"change", "delete"}
_log_lock = threading.Lock()


class ToolError(Exception):
    """Понятная ошибка инструмента — её текст можно показать пользователю и модели."""


class NeedsConfirm(Exception):
    def __init__(self, tool, args, summary):
        super().__init__(summary)
        self.tool, self.params, self.summary = tool, args, summary     # не .args — оно занято у Exception


@dataclass
class Tool:
    name: str
    description: str
    schema: object                     # dict или функция cfg -> dict (например, список разрешённых программ)
    fn: object
    risk: object = "read"              # строка или функция args -> risk
    explicit: object = None            # regex: инструмент доступен только при явной просьбе в реплике
    summary: object = None             # функция args -> строка для карточки подтверждения
    tags: tuple = field(default_factory=tuple)
    when: object = None                # функция cfg -> bool: показывать ли модели (например, панель подключена)

    def schema_for(self, cfg):
        return self.schema(cfg) if callable(self.schema) else self.schema

    def risk_for(self, args):
        return self.risk(args) if callable(self.risk) else self.risk

    def describe(self, args):
        if self.summary:
            try:
                return self.summary(args)
            except Exception:
                pass
        return f"{self.name}: " + ", ".join(f"{k}={v}" for k, v in args.items())


REGISTRY = {}


def tool(name, description, schema, risk="read", explicit=None, summary=None):
    def deco(fn):
        REGISTRY[name] = Tool(name, description, schema, fn, risk,
                              re.compile(explicit) if isinstance(explicit, str) else explicit, summary)
        return fn
    return deco


# ---------------------------------------------------------------- проверка аргументов
def validate(schema, value, path="args"):
    """Минимальный валидатор JSON-схемы. Возвращает значение (с безопасным приведением типов) или ToolError."""
    t = schema.get("type")
    if t == "object":
        if not isinstance(value, dict):
            raise ToolError(f"{path}: ожидался объект")
        props = schema.get("properties", {})
        out = {}
        for k in schema.get("required", []):
            if k not in value or value[k] in (None, ""):
                raise ToolError(f"{path}: не хватает параметра «{k}»")
        for k, v in value.items():
            if k not in props:
                if schema.get("additionalProperties", True) is False:     # наши схемы задают False явно
                    raise ToolError(f"{path}: лишний параметр «{k}»")
                continue
            if v is None and k not in schema.get("required", []):
                continue
            out[k] = validate(props[k], v, f"{path}.{k}")
        return out
    if t == "string":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        if not isinstance(value, str):
            raise ToolError(f"{path}: ожидалась строка")
        value = value.strip()
        if "enum" in schema and value not in schema["enum"]:
            low = {e.lower(): e for e in schema["enum"]}
            if value.lower() in low:
                value = low[value.lower()]
            else:
                raise ToolError(f"{path}: «{value}» нет в списке разрешённых ({', '.join(schema['enum'][:12])})")
        if len(value) < schema.get("minLength", 0):
            raise ToolError(f"{path}: пустое значение")
        if len(value) > schema.get("maxLength", 10_000):
            raise ToolError(f"{path}: слишком длинно (больше {schema['maxLength']} символов)")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ToolError(f"{path}: неверный формат «{value}»")
        return value
    if t in ("integer", "number"):
        if isinstance(value, str) and re.fullmatch(r"-?\d+(\.\d+)?", value.strip()):
            value = float(value) if "." in value else int(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ToolError(f"{path}: ожидалось число")
        if t == "integer":
            if isinstance(value, float) and not value.is_integer():
                raise ToolError(f"{path}: ожидалось целое число")
            value = int(value)
        if "minimum" in schema and value < schema["minimum"]:
            raise ToolError(f"{path}: меньше {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ToolError(f"{path}: больше {schema['maximum']}")
        return value
    if t == "boolean":
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        if not isinstance(value, bool):
            raise ToolError(f"{path}: ожидалось да/нет")
        return value
    if t == "array":
        if not isinstance(value, list):
            raise ToolError(f"{path}: ожидался список")
        if len(value) > schema.get("maxItems", 100):
            raise ToolError(f"{path}: слишком много элементов")
        return [validate(schema.get("items", {}), v, f"{path}[{i}]") for i, v in enumerate(value)]
    return value


# ---------------------------------------------------------------- журнал
def _short(v, n=200):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + "…"


def log_call(name, args, status, ms, via, result=""):
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "tool": name,
           "args": {k: _short(v) for k, v in (args or {}).items()}, "status": status, "ms": ms, "via": via,
           "result": _short(result, 300)}
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with _log_lock, open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_log(limit=200):
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, encoding="utf-8") as f:
        lines = f.readlines()[-limit:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- вызов
def available(cfg, turn_text=""):
    """Инструменты, которые можно показать модели в этой реплике (явные — только при явной просьбе)."""
    _load()
    return [t for t in REGISTRY.values() if (not t.explicit or t.explicit.search(turn_text or ""))
            and (not t.when or t.when(cfg))]


# Группы: модели показывается ядро + группы, чьи слова есть в реплике (cfg["tool_groups"]). Явные инструменты
# (web_search, run_powershell) уже отфильтрованы по фразе. Ничего не совпало → только ядро.
CORE = {"open_app", "close_app", "pc_action", "set_timer", "set_reminder", "create_note"}
GROUPS = [
    (re.compile(r"(файл|документ|pdf|docx|xlsx|excel|таблиц|выгруз|прочитай|найди|сохрани)"),
     lambda n: n in ("find_file", "read_document", "create_file")),
    (re.compile(r"(запомни|памят|просил|конспект|договор|заметк|в базе|в моих)"),
     lambda n: n in ("memory_search", "memory_save", "kb_search")),
    (re.compile(r"(отмени|верни как было|откат|статистик\w* инструмент|что работает плох|разбуди|ноутбук)"),
     lambda n: n in ("undo_last", "tool_stats", "wake_laptop")),
    (re.compile(r"(таблиц|график|диаграмм|столбч|в виде (списка|таблицы)|построй|нарисуй|покажи .*(сравнен|динамик|сводк))"),
     lambda n: n in ("show_table", "show_chart")),
    (re.compile(r"(клод|claude|кодекс|codex|кодер|внешн\w+ агент)"),
     lambda n: n in ("ask_coder", "coder_set")),
    (re.compile(r"(о себе|что ты умеешь|что ты можешь|твои возможности|что за панел|веб|панел\w* храз|виджет|главн\w+ экран|что подключено)"),
     lambda n: n == "khraz_info"),
    (re.compile(r"(лог|ошибк\w* на (сервер|сайт)|laravel|исключени|exception|что с сайтом|сервер упал)"),
     lambda n: n == "read_log"),
    (re.compile(r"(правил|кажд\w+ (день|утро|вечер|недел|час|пятниц|понедельн|вторник|сред|четверг|суббот|воскресен)|"
                r"ежедневн|еженедельн|по расписанию|раз в (день|час|недел)|регулярно)"),
     lambda n: n.startswith("rule_")),
    (re.compile(r"(\bip\b|диск|батаре|процесс|ping|пинг|видеокарт|загрузк|аптайм|сеть|интернет)"),
     lambda n: n == "run_command"),
]


def _grouped(ts, text):
    text = (text or "").lower()
    keep = set(CORE)
    for rx, pred in GROUPS:
        if rx.search(text):
            keep |= {t.name for t in ts if pred(t.name)}
    return [t for t in ts if t.name in keep or t.explicit]


def schemas(cfg, turn_text=""):
    ts = available(cfg, turn_text)
    if cfg.get("tool_groups"):
        ts = _grouped(ts, turn_text)
    return [{"type": "function", "function": {"name": t.name, "description": t.description,
                                              "parameters": t.schema_for(cfg)}} for t in ts]


def call(name, args, ctx, via="model", confirmed=False):
    """Проверить аргументы → (при необходимости) потребовать подтверждение → выполнить → записать в журнал."""
    _load()
    t0 = time.time()
    tool_ = REGISTRY.get(name)
    if not tool_:
        log_call(name, args, "unknown", 0, via)
        raise ToolError(f"инструмента {name} нет")
    try:
        if tool_.explicit and not tool_.explicit.search(getattr(ctx, "turn_text", "") or "") and via == "model":
            raise ToolError("этот инструмент доступен только по явной просьбе пользователя")
        if tool_.when and not tool_.when(ctx.cfg):
            raise ToolError("коннектор для этого инструмента не подключён (вкладка «Коннекторы»)")
        clean = validate(tool_.schema_for(ctx.cfg), args or {})
    except ToolError as e:
        log_call(name, args, "invalid", int((time.time() - t0) * 1000), via, str(e))
        raise
    risk = tool_.risk_for(clean)
    if risk in CONFIRM_RISKS and not confirmed:
        log_call(name, clean, "needs_confirm", 0, via)
        raise NeedsConfirm(name, clean, tool_.describe(clean))
    card = getattr(ctx, "tool_card", None)        # карточка в чате: запрос развёрнут, после ответа сворачивается
    cid = card("start", name, clean) if card else None
    try:
        res = tool_.fn(ctx, **clean)
    except ToolError as e:
        log_call(name, clean, "error", int((time.time() - t0) * 1000), via, str(e))
        card and card("end", cid, False, str(e))
        raise
    except Exception as e:
        log_call(name, clean, "error", int((time.time() - t0) * 1000), via, f"{type(e).__name__}: {e}")
        card and card("end", cid, False, f"{type(e).__name__}: {e}")
        raise ToolError(f"{type(e).__name__}: {e}") from e
    if risk in CONFIRM_RISKS:
        from . import postcheck
        res = postcheck.verify(name, ctx, clean, res)         # перечитать состояние → «Проверка: …»
        if via != "undo":
            postcheck.record(name, clean)                      # запомнить обратное действие для «отмени последнее»
    log_call(name, clean, "ok", int((time.time() - t0) * 1000), "confirmed" if confirmed else via, res)
    card and card("end", cid, True, res)
    return res


_loaded = False


def _load():
    global _loaded
    if _loaded:
        return
    _loaded = True
    from . import apps, coder_tools, desktop, files, files_out, kb_tools, logs, memory_tools, notes, postcheck, present, rules_tools, selfinfo, shell, system, timers, web  # noqa: F401
