"""Правила по расписанию (scheduler.py): создать, показать, удалить. Создание и удаление — с подтверждением."""
import json

import scheduler

from . import REGISTRY, ToolError, tool, validate

SKIP = {"rule_add", "rule_list", "rule_delete", "run_powershell", "close_app"}


def _add_schema(cfg):
    names = sorted(n for n in REGISTRY if n not in SKIP)
    return {"type": "object", "properties": {
        "title": {"type": "string", "maxLength": 80, "description": "короткое название правила"},
        "schedule": {"type": "string", "pattern": scheduler.SCHEDULE_RE,
                     "description": "daily 20:00 | weekly sun 20:00 (mon…sun) | every 120m"},
        "tool": {"type": "string", "enum": names, "description": "инструмент, который запускать (можно не указывать)"},
        "args_json": {"type": "string", "maxLength": 1000, "description": "аргументы инструмента как JSON-объект"},
        "say": {"type": "string", "maxLength": 300, "description": "текст напоминания, если инструмент не нужен"}},
        "required": ["title", "schedule"], "additionalProperties": False}


def _parse_args(cfg, name, raw):
    try:
        args = json.loads(raw) if raw else {}
    except ValueError:
        raise ToolError("args_json — не JSON-объект")
    if not isinstance(args, dict):
        raise ToolError("args_json — не JSON-объект")
    t = REGISTRY.get(name)
    if not t:
        raise ToolError(f"инструмента {name} нет")
    return validate(t.schema_for(cfg), args)


@tool("rule_add", "Создать правило по расписанию: регулярно запускать инструмент (чтение — сразу, изменения — с "
      "карточкой подтверждения) или напоминать текстом. Для разовых напоминаний есть set_reminder.",
      _add_schema, risk="change",
      summary=lambda a: f"Правило «{a['title']}»: {scheduler.describe_schedule(a['schedule'])} → "
                        f"{a.get('tool') or 'напоминание: ' + a.get('say', '')}")
def rule_add(ctx, title, schedule, tool=None, args_json="", say=None):
    args = _parse_args(ctx.cfg, tool, args_json) if tool else {}
    try:
        r = scheduler.add(title, schedule, tool, args, say)
    except ValueError as e:
        raise ToolError(str(e))
    return f"Правило создано: {r['id']} «{r['title']}», {scheduler.describe_schedule(r['schedule'])}"


@tool("rule_list", "Показать правила по расписанию.", {"type": "object", "properties": {},
                                                          "additionalProperties": False}, risk="read")
def rule_list(ctx):
    rules = scheduler.load()
    if not rules:
        return "Правил нет."
    return "\n".join(f"{r['id']} · «{r['title']}» · {scheduler.describe_schedule(r['schedule'])} · "
                     f"{r['tool'] or 'напоминание'}" for r in rules)


@tool("rule_delete", "Удалить правило по расписанию (id или часть названия).",
      {"type": "object", "properties": {"rule": {"type": "string", "maxLength": 80}}, "required": ["rule"],
       "additionalProperties": False}, risk="change", summary=lambda a: f"Удалить правило «{a['rule']}»")
def rule_delete(ctx, rule):
    try:
        r = scheduler.delete(rule)
    except ValueError as e:
        raise ToolError(str(e))
    return f"Удалено: «{r['title']}»"
