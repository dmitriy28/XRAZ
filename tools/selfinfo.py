"""khraz_info — ХРАЗ рассказывает о себе: модели, коннекторы, кодер."""
import datetime

from . import tool

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


@tool("khraz_info", "Сведения о самом ХРАЗе: модели, подключённые коннекторы, кодовые "
      "агенты. Для вопросов «что это за панель», «что ты умеешь», «что подключено». Токен не выдаёт.", SCHEMA, risk="read")
def khraz_info(ctx):
    import coder
    cfg = ctx.cfg
    cs = coder.status(cfg)
    info = {
        "дата": datetime.date.today().isoformat(),
        "модели": {"основная": cfg.get("model"), "умная": cfg.get("model_smart"), "кодовая": cfg.get("model_code"),
                   "режим": getattr(ctx, "mode", "auto"), "запасной режим": bool(getattr(getattr(ctx, "llm", None), "on_fallback", False))},
        "коннекторы": {"сторонних MCP": len([s for s in cfg.get("mcp_servers") or [] if s.get("enabled", True)])},
        "кодер": {"настроен": cs["configured"], "проекты": cs["projects"], "выбрано": cs["state"]["agent"] + " / " + (cs["state"]["model"] or "по умолчанию"),
                  "установлены": [a["title"] for a in cs["agents"] if a["installed"]],
                  "как включить": "добавить проекты в config.json → coder_projects; запуск фразой «спроси Клода …»"},
        "возможности": ["компактный режим (Win+Shift+X)", "правила по расписанию", "таблицы и графики в чате", "чтение логов", "откат последнего изменения"],
    }
    return info
