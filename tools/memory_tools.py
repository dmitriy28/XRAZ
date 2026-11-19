"""Долговременная память для модели: искать можно свободно, а сохранить — только предложить
(пользователь подтверждает карточкой или голосом «да»). Ничего не сохраняется автоматически."""
from . import tool

SEARCH = {"type": "object", "properties": {
    "query": {"type": "string", "minLength": 2, "maxLength": 200}}, "required": ["query"],
    "additionalProperties": False}
SAVE = {"type": "object", "properties": {
    "text": {"type": "string", "minLength": 3, "maxLength": 300, "description": "одна короткая запись"},
    "kind": {"type": "string", "enum": ["fact", "preference"], "description": "факт или предпочтение"}},
    "required": ["text"], "additionalProperties": False}


@tool("memory_search", "Найти в долговременной памяти то, что пользователь просил запомнить.", SEARCH, risk="read")
def memory_search(ctx, query):
    return [{"id": m["id"], "text": m["text"], "kind": m.get("kind", "fact")}
            for m, _ in ctx.memory.search(query, k=6)]


@tool("memory_save", "Предложить сохранить запись в долговременную память. Сохранится только после "
      "подтверждения пользователя. Используй, только если пользователь сам сообщил важный факт или предпочтение.",
      SAVE, risk="change", summary=lambda a: f"Запомнить: «{a['text']}»")
def memory_save(ctx, text, kind="fact"):
    m = ctx.memory.add(text, kind=kind, source="подтверждено")
    return f"Сохранено в памяти: {m['text']}"
