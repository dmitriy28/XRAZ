"""Управление рабочим столом: звук, окна, клавиши, папки, питание… — обёртка над actions.py/pc.py.
Модель выбирает действие из перечня (без PowerShell и cmd). Опасное (выключение, закрытие всех окон,
очистка корзины) — только после подтверждения."""
import actions

from . import tool

# не отдаём модели: shell/powershell (произвольные команды), программы и таймеры — у них свои инструменты
EXCLUDED = {"shell", "powershell", "open_app", "close_app", "timer", "remind", "say", "wait"}


def _allowed():
    return [k for k in actions.ACTIONS if k not in EXCLUDED]


def _schema(cfg):
    doc = "; ".join(f"{k}: {actions.ACTIONS[k][1]}" for k in _allowed())
    return {"type": "object", "properties": {
        "action": {"type": "string", "enum": _allowed(), "description": doc},
        "param": {"type": "string", "maxLength": 2000, "description": "параметр действия (см. описание)"}},
        "required": ["action"], "additionalProperties": False}


def _risk(a):
    return "change" if a["action"] in actions.CONFIRM else "action"


@tool("pc_action", "Действие на компьютере: громкость, яркость, медиа, окна, клавиши, мышь, папки, параметры "
      "Windows, сайты, поиск на YouTube, печать текста, скриншот, время, погода, курс валют, питание.",
      _schema, risk=_risk, summary=lambda a: actions.describe({"type": a["action"], "param": a.get("param", "")}))
def pc_action(ctx, action, param=""):
    ctx.ui_action(actions.describe({"type": action, "param": param}).capitalize())
    said = actions.run_steps([{"type": action, "param": param}], ctx)
    return ". ".join(said) if said else "Готово"
