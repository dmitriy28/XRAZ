"""ask_coder — передать задачу Claude Code или Codex (coder.py); coder_set — переключить агента, модель, режим, проект."""
import os

import coder

from . import REGISTRY, ToolError, tool

EXPLICIT = (r"(клод\w*|claude|кодекс\w*|codex|кодер\w*|кодов\w+ агент\w*|внешн\w+ агент\w*|"
            r"спроси\s+(у\s+)?(клод|кодекс|кодер)|отдай\s+(клод|кодекс|кодер)|переключи\s+(кодер|агент))")


def _enabled(cfg):
    return bool(coder.projects(cfg))


def _ask_schema(cfg):
    ags = list(coder.agents(cfg))
    pj = list(coder.projects(cfg)) or ["—"]
    return {"type": "object", "properties": {
        "task": {"type": "string", "minLength": 3, "maxLength": 4000, "description": "что нужно сделать: сформулируй полно и самодостаточно"},
        "agent": {"type": "string", "enum": ags, "description": "claude — Claude Code, codex — Codex; не указывай, если пользователь не назвал"},
        "model": {"type": "string", "pattern": r"[\w.\-:/]{1,60}", "description": "модель агента (sonnet, opus, haiku…); не указывай без просьбы"},
        "project": {"type": "string", "enum": pj, "description": "проект из настроек"},
        "mode": {"type": "string", "enum": list(coder.MODES), "description": "plan — только чтение и анализ (по умолчанию); edit — правки файлов, только если просили изменить код"},
        "context": {"type": "string", "enum": list(coder.CONTEXTS), "description": "none — без контекста; chat — недавний разговор (по умолчанию); full — ещё и память"}},
        "required": ["task"], "additionalProperties": False}


def _ask_summary(a):
    mode = "ПРАВКИ ФАЙЛОВ РАЗРЕШЕНЫ" if coder.effective_mode(a) == "edit" else "только чтение"
    return (f"Передать задачу внешнему агенту ({a.get('agent') or 'выбранный'}"
            f"{' / ' + a['model'] if a.get('model') else ''}), проект «{a.get('project') or 'по умолчанию'}», {mode}, "
            f"контекст: {a.get('context') or 'chat'}. Текст и контекст уйдут в облако.\nЗадача: {a['task'][:300]}")


@tool("ask_coder", "Передать задачу кодовому агенту Claude Code или Codex (с контекстом разговора) и показать его ответ. "
      "Только по явной просьбе пользователя («спроси Клода…», «отдай Кодексу…»).", _ask_schema, risk="change",
      explicit=EXPLICIT, summary=_ask_summary)
def ask_coder(ctx, task, agent=None, model=None, project=None, mode=None, context=None):
    try:
        res = coder.run(ctx, task, agent, model, project, mode, context, on_line=lambda s: ctx.ui_action(f"Кодер: {s}"))
    except (ValueError, FileNotFoundError) as e:
        raise ToolError(str(e))
    ags = coder.agents(ctx.cfg)
    title = ags.get(res["agent"], {}).get("title", res["agent"])
    head = f"**{title} · {res['model'] or 'модель по умолчанию'} · {res['project']}** ({res['secs']:.0f} с" + \
           (", продолжение сессии" if res["continued"] else "") + ")"
    if res["cancelled"]:
        ctx.show(head + "\n\n*— остановлено —*")
        return "Работа кодера остановлена пользователем."
    out = res["output"] or "(пустой ответ)"
    shown = out if len(out) <= 12000 else out[:12000] + "\n\n*… ответ длинный, полный текст — в файле ниже.*"
    ctx.show(head + "\n\n" + shown)
    import reports
    reports.save(ctx.cfg, "coder", f"{title}: {task.strip()[:45]}", f"{head}\n\n**Задача:** {task.strip()}\n\n{out}")
    if len(out) > 12000:
        from .files_out import unique_path
        path = unique_path(ctx.cfg, f"кодер {res['agent']} {res['project']}", "md")
        with open(path, "x", encoding="utf-8") as f:
            f.write(out)
        ctx.file_ready(path)
    if not res["ok"]:
        raise ToolError(f"{title} завершился с ошибкой (код {res['code']}); вывод показан в чате")
    first = next((ln for ln in out.splitlines() if ln.strip()), "")
    return f"Ответ {title} показан пользователю. Итог: {first[:300]}"


def _set_schema(cfg):
    ags = coder.agents(cfg)
    return {"type": "object", "properties": {
        "agent": {"type": "string", "enum": list(ags)}, "model": {"type": "string", "pattern": r"[\w.\-:/]{1,60}"},
        "mode": {"type": "string", "enum": list(coder.MODES)}, "context": {"type": "string", "enum": list(coder.CONTEXTS)},
        "project": {"type": "string", "enum": list(coder.projects(cfg)) or ["—"]}}, "additionalProperties": False}


@tool("coder_set", "Переключить кодового агента (Claude Code / Codex), его модель, режим (plan/edit), уровень контекста или "
      "проект. Только настройка, сам агент не запускается.", _set_schema, risk="action", explicit=EXPLICIT,
      summary=lambda a: "Кодер: " + ", ".join(f"{k}={v}" for k, v in a.items()))
def coder_set(ctx, **kw):
    if not kw:
        raise ToolError("что переключить: агент, модель, режим, контекст или проект")
    try:
        st = coder.set_state(ctx.cfg, **kw)
    except ValueError as e:
        raise ToolError(str(e))
    return f"Кодер: {st['agent']} · {st['model'] or 'модель по умолчанию'} · режим {st['mode']} · контекст {st['context']} · проект {st['project']}"


REGISTRY["ask_coder"].when = _enabled
REGISTRY["coder_set"].when = _enabled
