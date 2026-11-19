"""Автосохранение результатов ХРАЗа заметками .md (папка заметок → «Отчёты ХРАЗ»), в формате Obsidian:
у каждой заметки frontmatter (тип, дата, источник, теги) и заголовок. Если указать папку заметок как хранилище Obsidian, отчёты
сразу видны там; чтобы ХРАЗ искал по ним, добавьте эту папку в «Базу знаний» (Настройки → kb_folders).

Что сохраняется: результаты правил по расписанию, утренняя сводка, ответы Клода/Кодекса, таблицы (show_table). Чаты и обычные ответы — нет.
Безопасность: ссылки подключений (vless:// и т. п.) и UUID заменяются заглушкой; запрещённые папки уважаются;
файл никогда не перезаписывается; любая ошибка записи молча пропускается и не ломает ответ. Выключение — notes_autosave: false."""
import datetime
import hashlib
import os
import re
import time

SUBDIR = "Отчёты ХРАЗ"
KINDS = {"rule": "Правило", "morning": "Утренняя сводка", "coder": "Кодер", "table": "Таблица"}
LINK = re.compile(r"\b(?:vless|vmess|trojan|ss|ssr|hysteria2?|tuic|wireguard)://\S+", re.I)
UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
MAX = 200_000
_recent = {}                                  # (вид, хеш текста) → время: одну и ту же таблицу за полчаса дважды не пишем
DEDUP_SEC = 1800


def enabled(cfg):
    return bool(cfg.get("notes_autosave", True))


def redact(text):
    t = LINK.sub("[ссылка скрыта]", text or "")
    t = re.sub(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b", "[токен скрыт]", t)          # токен Telegram-бота
    return UUID.sub("[id скрыт]", t)


def _safe(title):
    t = re.sub(r'[\\/:*?"<>|\n\r\t#\[\]^]+', " ", str(title or "")).strip(" .")
    return re.sub(r"\s+", " ", t)[:60] or "без названия"


def folder(cfg):
    return os.path.join(os.path.expanduser(cfg.get("notes_dir") or "~/Documents/ХРАЗ заметки"), SUBDIR)


def save(cfg, kind, title, body, now=None):
    """Сохраняет отчёт; возвращает путь или None (выключено, дубль, запрещено, ошибка)."""
    try:
        if kind not in KINDS or not enabled(cfg) or not str(body or "").strip():
            return None
        text = redact(str(body))[:MAX].strip()
        key = (kind, hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest())
        t = time.time()
        for k in [k for k, v in _recent.items() if t - v > DEDUP_SEC]:
            del _recent[k]
        if key in _recent:
            return None
        from tools.files import check_writable
        d = folder(cfg)
        check_writable(cfg, d)
        os.makedirs(d, exist_ok=True)
        now = now or datetime.datetime.now()
        head = _safe(title)
        path = os.path.join(d, f"{now.strftime('%Y-%m-%d %H-%M')} {KINDS[kind]} — {head}.md")
        n = 2
        while os.path.exists(path):
            path = os.path.join(d, f"{now.strftime('%Y-%m-%d %H-%M')} {KINDS[kind]} — {head} ({n}).md")
            n += 1
        front = f"---\ntype: {kind}\ncreated: {now.strftime('%Y-%m-%dT%H:%M:%S')}\nsource: ХРАЗ\ntags: [храз, отчёт, {kind}]\n---\n"
        with open(path, "x", encoding="utf-8") as f:           # "x" — никогда не перезаписывать
            f.write(f"{front}\n# {KINDS[kind]} — {head}\n\n{text}\n")
        _recent[key] = t
        return path
    except Exception:                                          # noqa: BLE001 — отчёт не должен ломать работу
        return None
