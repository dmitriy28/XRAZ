"""Сторонний MCP-сервер для тестов: чтение (readOnlyHint), запись и разрушительное действие.
Проверяет, что секреты из хранилища дошли через переменные окружения."""
import os

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

mcp = MCPServer("notes-demo")
NOTES = {"1": "купить молоко"}


@mcp.tool(name="list_notes", description="Список заметок", annotations=ToolAnnotations(readOnlyHint=True))
def list_notes() -> dict:
    return {"notes": NOTES, "token_seen": os.environ.get("DEMO_TOKEN") == "s3cret"}


@mcp.tool(name="add_note", description="Добавить заметку")
def add_note(text: str) -> dict:
    NOTES[str(len(NOTES) + 1)] = text
    return {"ok": True, "count": len(NOTES)}


@mcp.tool(name="wipe_notes", description="Удалить все заметки", annotations=ToolAnnotations(destructiveHint=True))
def wipe_notes() -> dict:
    NOTES.clear()
    return {"ok": True}


if __name__ == "__main__":
    mcp.run("stdio")
