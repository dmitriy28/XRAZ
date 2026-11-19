"""Заметки — файлы .md в папке notes_dir. Новая заметка никогда не перезаписывает существующую."""
import datetime
import os
import re

from . import tool

SCHEMA = {"type": "object", "properties": {
    "text": {"type": "string", "minLength": 1, "maxLength": 20000, "description": "текст заметки"},
    "title": {"type": "string", "maxLength": 80, "description": "заголовок, необязательно"}},
    "required": ["text"], "additionalProperties": False}


def notes_dir(cfg):
    d = os.path.expanduser(cfg.get("notes_dir") or "~/Documents/ХРАЗ заметки")
    os.makedirs(d, exist_ok=True)
    return d


@tool("create_note", "Создать заметку (новый файл в папке заметок).", SCHEMA, risk="create",
      summary=lambda a: f"Заметка «{a.get('title') or a['text'][:40]}»")
def create_note(ctx, text, title=""):
    from tools.files import check_writable
    d = notes_dir(ctx.cfg)
    check_writable(ctx.cfg, d)
    title = title or text.strip().split("\n")[0][:40]
    safe = re.sub(r'[\\/:*?"<>|\n\r\t]+', " ", title).strip() or "заметка"
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H-%M")
    path = os.path.join(d, f"{stamp} {safe}.md")
    n = 2
    while os.path.exists(path):
        path = os.path.join(d, f"{stamp} {safe} ({n}).md")
        n += 1
    with open(path, "x", encoding="utf-8") as f:       # "x" — никогда не перезаписывать
        f.write(f"# {title}\n\n{text.strip()}\n")
    ctx.ui_action(f"Заметка сохранена: {os.path.basename(path)}")
    return f"Заметка сохранена: {path}"
