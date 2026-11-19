"""Создание файлов для пользователя: текст, таблицы, документы. Файл появляется в чате карточкой
с кнопками «Открыть», «Показать в папке», «Сохранить как…». Существующие файлы не перезаписываются."""
import csv
import datetime
import io
import json
import os
import re

from . import ToolError, tool

FORMATS = ["txt", "md", "csv", "json", "html", "py", "docx", "xlsx"]


def out_dir(cfg):
    from tools.files import check_writable
    d = os.path.expanduser(cfg.get("outputs_dir") or "~/Documents/ХРАЗ файлы")
    check_writable(cfg, d)
    os.makedirs(d, exist_ok=True)
    return d


def unique_path(cfg, name, ext):
    safe = re.sub(r'[\\/:*?"<>|\n\r\t]+', " ", name).strip().strip(".") or "файл"
    safe = safe[:80]
    d = out_dir(cfg)
    path = os.path.join(d, f"{safe}.{ext}")
    n = 2
    while os.path.exists(path):
        path = os.path.join(d, f"{safe} ({n}).{ext}")
        n += 1
    return path


def _rows_from(content):
    """Содержимое таблицы: JSON-массив строк (первая — заголовки) или CSV-текст."""
    s = content.strip()
    if s.startswith("["):
        try:
            data = json.loads(s)
            if isinstance(data, list) and all(isinstance(r, list) for r in data):
                return [[("" if c is None else c) for c in r] for r in data]
            if isinstance(data, list) and all(isinstance(r, dict) for r in data):
                head = list(dict.fromkeys(k for r in data for k in r))
                return [head] + [[r.get(k, "") for k in head] for r in data]
        except ValueError:
            pass
    sample = s[:2000]
    delim = ";" if sample.count(";") > sample.count(",") else ("\t" if "\t" in sample else ",")
    return list(csv.reader(io.StringIO(s), delimiter=delim))


def write_table(ctx, name, head, rows, fmt="xlsx"):
    path = unique_path(ctx.cfg, name, fmt)
    if fmt == "csv":
        with open(path, "x", encoding="utf-8-sig", newline="") as f:      # BOM — Excel откроет кириллицу
            w = csv.writer(f, delimiter=";")
            if head:
                w.writerow(head)
            w.writerows(rows)
    else:
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill
        except ImportError:
            raise ToolError("для xlsx нужен пакет openpyxl: pip install openpyxl")
        wb = Workbook()
        ws = wb.active
        ws.title = "Данные"
        if head:
            ws.append(head)
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor="7D1A1E")
            ws.freeze_panes = "A2"
        for r in rows:
            ws.append([_num(x) for x in r])
        for col in ws.columns:
            width = max((len(str(c.value or "")) for c in col), default=8)
            ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
        wb.save(path)
    ctx.file_ready(path)
    return path


def _num(x):
    if isinstance(x, str) and re.fullmatch(r"-?\d+([.,]\d+)?", x.strip()):
        return float(x.replace(",", ".")) if re.search(r"[.,]", x) else int(x)
    return x


SCHEMA = {"type": "object", "properties": {
    "name": {"type": "string", "minLength": 1, "maxLength": 80, "description": "имя файла без расширения"},
    "format": {"type": "string", "enum": FORMATS},
    "content": {"type": "string", "minLength": 1, "maxLength": 400000,
                "description": "текст; для csv/xlsx — CSV или JSON-массив строк (первая строка — заголовки); "
                               "для docx — markdown (# заголовки, - списки)"}},
    "required": ["name", "format", "content"], "additionalProperties": False}


@tool("create_file", "Создать файл (txt, md, csv, json, html, py, docx, xlsx) и отдать пользователю на загрузку. "
      "Используй, когда просят сделать файл, таблицу, документ, выгрузку, отчёт.", SCHEMA, risk="create",
      summary=lambda a: f"Файл «{a['name']}.{a['format']}»")
def create_file(ctx, name, format, content):
    ctx.ui_action(f"Создаю файл {name}.{format}")
    if format in ("csv", "xlsx"):
        rows = _rows_from(content)
        if not rows:
            raise ToolError("пустая таблица")
        path = write_table(ctx, name, rows[0], rows[1:], format)
        return {"file": path, "rows": len(rows) - 1}
    path = unique_path(ctx.cfg, name, format)
    if format == "docx":
        try:
            import docx
        except ImportError:
            raise ToolError("для docx нужен пакет python-docx: pip install python-docx")
        doc = docx.Document()
        for line in content.splitlines():
            m = re.match(r"^(#{1,3})\s+(.*)", line)
            if m:
                doc.add_heading(m.group(2), level=len(m.group(1)))
            elif re.match(r"^\s*[-*]\s+", line):
                doc.add_paragraph(re.sub(r"^\s*[-*]\s+", "", line), style="List Bullet")
            elif line.strip():
                doc.add_paragraph(line)
        doc.core_properties.author = "ХРАЗ"
        doc.save(path)
    elif format == "json":
        try:
            content = json.dumps(json.loads(content), ensure_ascii=False, indent=2)
        except ValueError:
            pass
        with open(path, "x", encoding="utf-8") as f:
            f.write(content)
    else:
        with open(path, "x", encoding="utf-8") as f:
            f.write(content)
    ctx.file_ready(path)
    return {"file": path, "size_kb": round(os.path.getsize(path) / 1024, 1),
            "created": datetime.datetime.now().strftime("%H:%M")}
