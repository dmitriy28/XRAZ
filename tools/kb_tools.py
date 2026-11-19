"""Поиск по базе знаний (папки майора: конспекты, договоры, заметки)."""
from . import ToolError, tool

SCHEMA = {"type": "object", "properties": {
    "query": {"type": "string", "minLength": 2, "maxLength": 300, "description": "что найти, своими словами"}},
    "required": ["query"], "additionalProperties": False}


@tool("kb_search", "Найти в базе знаний майора (его конспекты, договоры, заметки) фрагменты по смыслу; "
      "отвечай по ним и указывай источник (файл, страница).", SCHEMA, risk="read")
def kb_search(ctx, query):
    kb = getattr(ctx, "kb", None)
    if not kb or not kb.items:
        raise ToolError("база знаний пуста: добавьте папки в «Настройки → База знаний» и нажмите «Индексировать»")
    ctx.ui_action(f"База знаний: «{query}»")
    return [{"source": kb.cite(h), "score": h["score"], "text": h["text"]} for h in kb.search(query, k=5, min_score=0.4)]


kb_search_tool = None


def _when(cfg):
    return bool(cfg.get("kb_folders"))


from . import REGISTRY as _R  # noqa: E402
_R["kb_search"].when = _when
