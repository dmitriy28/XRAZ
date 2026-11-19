"""Программы: открыть и закрыть — только из списка разрешённых (Настройки → «Разрешённые программы»)."""
import os

import actions

from . import ToolError, tool


def _names(cfg):
    return sorted((cfg.get("allowed_apps") or {}).keys())


def _schema(cfg):
    return {"type": "object", "properties": {
        "name": {"type": "string", "enum": _names(cfg) or ["—"], "description": "программа из списка разрешённых"}},
        "required": ["name"], "additionalProperties": False}


def resolve(cfg, name):
    apps = cfg.get("allowed_apps") or {}
    if name not in apps:
        raise ToolError(f"программы «{name}» нет в списке разрешённых")
    return apps[name]


@tool("open_app", "Открыть разрешённую программу.", _schema, risk="action",
      summary=lambda a: f"Открыть {a['name']}")
def open_app(ctx, name):
    target = os.path.expandvars(os.path.expanduser(resolve(ctx.cfg, name)))
    ctx.ui_action(f"Открываю {name}")
    said = actions.open_app(target, ctx)
    if said and said.startswith("Не нашёл"):
        raise ToolError(f"{name} не найден на компьютере ({target}). Укажите путь в списке разрешённых программ.")
    return f"Открыто: {name}"


@tool("close_app", "Закрыть разрешённую программу (несохранённые данные будут потеряны — нужно подтверждение).",
      _schema, risk="change", summary=lambda a: f"Закрыть {a['name']} (несохранённое пропадёт)")
def close_app(ctx, name):
    target = resolve(ctx.cfg, name)
    ctx.ui_action(f"Закрываю {name}")
    actions.close_app(os.path.splitext(os.path.basename(target))[0], ctx)
    return f"Закрыто: {name}"
