"""Поиск и чтение локальных файлов — только в выбранных папках (search_roots) и в файлах, которые пользователь
сам выбрал кнопкой «Прочитать документ…». Запрещённые пути (forbidden_paths, по умолчанию ~/research)
не читаются, не ищутся и не изменяются никогда."""
import os
import time

from . import ToolError, tool

SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "venv", "__pycache__", "$recycle.bin", "appdata", ".cache"}
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".log", ".py", ".php", ".js", ".ts", ".html", ".css", ".xml", ".yml",
            ".yaml", ".ini", ".cfg", ".tex", ".sql", ".bat", ".ps1", ".rtf"}
DOC_EXT = TEXT_EXT | {".pdf", ".docx"}
MAX_CHARS = 12000


def _norm(p):
    return os.path.normcase(os.path.realpath(os.path.expanduser(os.path.expandvars(p))))


def roots(cfg):
    return [r for r in (_norm(x) for x in cfg.get("search_roots") or []) if os.path.isdir(r)]


def forbidden(cfg):
    return [_norm(x) for x in cfg.get("forbidden_paths") or []]


def _under(path, base):
    try:
        return os.path.commonpath([path, base]) == base
    except ValueError:          # разные диски Windows
        return False


def is_forbidden(cfg, path):
    p = _norm(path)
    return any(_under(p, f) for f in forbidden(cfg))


def check_readable(cfg, path, picked=()):
    p = _norm(path)
    if is_forbidden(cfg, p):
        raise ToolError("эта папка закрыта для ХРАЗа (forbidden_paths)")
    if p in {_norm(x) for x in picked}:
        return p
    if not any(_under(p, r) for r in roots(cfg)):
        raise ToolError("файл вне разрешённых папок поиска. Добавьте папку в «Настройки → Папки поиска» "
                        "или выберите файл кнопкой «Прочитать документ…»")
    return p


def check_writable(cfg, path):
    if is_forbidden(cfg, path):
        raise ToolError("запись в эту папку запрещена (forbidden_paths)")
    return _norm(path)


FIND = {"type": "object", "properties": {
    "query": {"type": "string", "minLength": 2, "maxLength": 100, "description": "часть имени файла"},
    "extension": {"type": "string", "pattern": r"\.?[A-Za-z0-9]{1,8}", "description": "расширение, например pdf"}},
    "required": ["query"], "additionalProperties": False}


@tool("find_file", "Найти файл по имени в разрешённых папках (Документы, Рабочий стол, Загрузки и выбранные).",
      FIND, risk="read")
def find_file(ctx, query, extension="", limit=15, time_limit=6.0):
    words = [w for w in query.lower().replace("_", " ").split() if w]
    ext = ("." + extension.lstrip(".").lower()) if extension else ""
    found, t0 = [], time.time()
    ctx.ui_action(f"Ищу файл «{query}»")
    bad = forbidden(ctx.cfg)
    for root in roots(ctx.cfg):
        for d, dirs, files in os.walk(root):
            nd = _norm(d)
            if any(_under(nd, b) for b in bad):
                dirs[:] = []
                continue
            dirs[:] = [x for x in dirs if x.lower() not in SKIP_DIRS and not x.startswith(".")]
            for f in files:
                low = f.lower()
                if ext and not low.endswith(ext):
                    continue
                if all(w in low for w in words):
                    p = os.path.join(d, f)
                    try:
                        st = os.stat(p)
                    except OSError:
                        continue
                    found.append({"path": p, "name": f, "size_kb": round(st.st_size / 1024),
                                  "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))})
            if len(found) >= limit or time.time() - t0 > time_limit:
                break
        if len(found) >= limit or time.time() - t0 > time_limit:
            break
    found.sort(key=lambda x: x["modified"], reverse=True)
    for f in found:                       # выбранные поиском файлы можно читать
        ctx.picked_files.add(f["path"])
    return {"found": found[:limit], "searched": [os.path.basename(r) or r for r in roots(ctx.cfg)]}


READ = {"type": "object", "properties": {
    "path": {"type": "string", "minLength": 3, "maxLength": 400, "description": "полный путь к файлу"}},
    "required": ["path"], "additionalProperties": False}


def extract_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in DOC_EXT:
        raise ToolError(f"формат {ext or 'без расширения'} не поддерживается (txt, md, pdf, docx, код)")
    if os.path.getsize(path) > 30 * 1024 * 1024:
        raise ToolError("файл больше 30 МБ")
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ToolError("для PDF нужен пакет pypdf: pip install pypdf")
        reader = PdfReader(path)
        parts = []
        for page in reader.pages[:200]:
            parts.append(page.extract_text() or "")
            if sum(map(len, parts)) > MAX_CHARS * 2:
                break
        return "\n".join(parts), len(reader.pages)
    if ext == ".docx":
        try:
            import docx
        except ImportError:
            raise ToolError("для DOCX нужен пакет python-docx: pip install python-docx")
        d = docx.Document(path)
        return "\n".join(p.text for p in d.paragraphs), None
    for enc in ("utf-8", "cp1251"):
        try:
            with open(path, encoding=enc) as f:
                return f.read(MAX_CHARS * 2), None
        except UnicodeDecodeError:
            continue
    raise ToolError("не удалось определить кодировку текста")


@tool("read_document", "Прочитать документ (txt, md, pdf, docx, код) из разрешённых папок или выбранный "
      "пользователем. Возвращает текст (до 12 000 символов).", READ, risk="read")
def read_document(ctx, path):
    p = check_readable(ctx.cfg, path, ctx.picked_files)
    if not os.path.isfile(p):
        raise ToolError(f"файл не найден: {path}")
    ctx.ui_action(f"Читаю {os.path.basename(path)}")
    text, pages = extract_text(p)
    text = text.strip()
    cut = len(text) > MAX_CHARS
    return {"name": os.path.basename(path), "pages": pages, "chars": len(text), "truncated": cut,
            "text": text[:MAX_CHARS]}
