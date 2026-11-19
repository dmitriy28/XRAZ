"""Вывод данных от самого ХРАЗа: таблица и график прямо в чат (окно и браузер). Модель сначала собирает данные
инструментами (файлы, логи, система…), затем вызывает show_table / show_chart — и не печатает таблицу текстом сама.
График рисуется на месте (Pillow, без внешних библиотек) в стиле интерфейса и сохраняется в папку файлов ХРАЗа."""
import math
import os

from . import REGISTRY, ToolError, tool

PALETTE = ["#d7262e", "#c9a24a", "#9fb3c8", "#3fbf6f", "#ff9d2e", "#8f6bd1", "#c56b9e", "#5aa7a3"]
BG, PANEL, LINE, CREAM, MUTED, BRASS = "#0e0b0a", "#17110f", "#3a2a22", "#eadfc8", "#8f8070", "#c9a24a"
FONT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts", "Oswald.ttf")
MAX_ROWS, MAX_COLS, MAX_POINTS = 200, 12, 24

_TABLE = {"type": "object", "properties": {
    "title": {"type": "string", "maxLength": 100, "description": "заголовок таблицы"},
    "columns": {"type": "array", "maxItems": MAX_COLS, "items": {"type": "string", "maxLength": 60},
                "description": "названия столбцов"},
    "rows": {"type": "array", "maxItems": MAX_ROWS, "items": {"type": "array", "maxItems": MAX_COLS, "items": {}},
             "description": "строки: списки значений в порядке столбцов"}},
    "required": ["columns", "rows"], "additionalProperties": False}

_CHART = {"type": "object", "properties": {
    "title": {"type": "string", "maxLength": 100},
    "kind": {"type": "string", "enum": ["bar", "line", "pie"], "description": "bar — столбцы, line — линия, pie — доли"},
    "labels": {"type": "array", "maxItems": MAX_POINTS, "items": {"type": "string", "maxLength": 40}},
    "values": {"type": "array", "maxItems": MAX_POINTS, "items": {}, "description": "числа, по одному на подпись"},
    "unit": {"type": "string", "maxLength": 20, "description": "единица измерения, например ГБ или ₽"}},
    "required": ["labels", "values"], "additionalProperties": False}


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).replace("|", "¦").replace("\n", " ").strip()[:200]


def markdown_table(title, columns, rows):
    cols = [_cell(c) or "—" for c in columns]
    lines = [f"**{_cell(title)}**\n"] if title else []
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join("---" for _ in cols) + "|")
    for r in rows:
        r = list(r)[:len(cols)] + [""] * max(0, len(cols) - len(r))
        lines.append("| " + " | ".join(_cell(x) for x in r) + " |")
    return "\n".join(lines)


def _show(ctx, md):
    fn = getattr(ctx, "show", None) or getattr(ctx, "notify", None)
    if not fn:
        raise ToolError("в этом интерфейсе нельзя показать таблицу")
    fn(md)


@tool("show_table", "Показать пользователю таблицу в чате (данные уже собраны другими инструментами). Используй, когда "
      "просят таблицу, список с несколькими полями, сравнение или сводку; не печатай таблицу текстом сам.",
      _TABLE, risk="read", summary=lambda a: f"Таблица «{a.get('title', '')}»")
def show_table(ctx, columns, rows, title=""):
    if not columns:
        raise ToolError("нужны названия столбцов")
    if not rows:
        raise ToolError("нет строк для таблицы")
    md = markdown_table(title, columns, rows)
    _show(ctx, md)
    import reports
    reports.save(ctx.cfg, "table", title or "таблица", md)
    return f"Таблица «{title}» показана пользователю: {len(rows)} строк. Не повторяй её содержимое — скажи один вывод."


# ---------------------------------------------------------------- график
def _num(v):
    try:
        x = float(str(v).replace(",", ".").replace(" ", ""))
    except ValueError:
        raise ToolError(f"значение «{v}» — не число")
    if not math.isfinite(x):
        raise ToolError("значения должны быть конечными числами")
    return x


def _fmt(x):
    return f"{x:,.2f}".rstrip("0").rstrip(".").replace(",", " ") if abs(x) < 1e6 else f"{x:.3g}"


def _nice_step(raw):
    raw = max(raw, 1e-9)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def render_chart(path, title, kind, labels, values, unit=""):
    from PIL import Image, ImageDraw, ImageFont
    W, H = 1000, 560
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    def font(sz):
        try:
            return ImageFont.truetype(FONT, sz)
        except OSError:
            return ImageFont.load_default()
    f_t, f_l, f_s = font(30), font(18), font(15)
    d.rectangle([0, 0, W - 1, H - 1], outline=LINE)
    d.text((28, 18), (title or "")[:60], font=f_t, fill=BRASS)
    d.line([28, 62, W - 28, 62], fill=LINE, width=1)
    x0, y0, x1, y1 = 80, 90, W - 40, H - 120
    n = len(values)

    def label_img(text, rot):
        t = text if len(text) <= 14 else text[:13] + "…"
        tmp = Image.new("RGBA", (200, 28), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((0, 0), t, font=f_s, fill=CREAM)
        box = tmp.getbbox() or (0, 0, 1, 1)
        tmp = tmp.crop(box)
        return tmp.rotate(rot, expand=True) if rot else tmp

    if kind == "pie":
        pos = [max(v, 0) for v in values]
        total = sum(pos)
        if total <= 0:
            raise ToolError("для круговой диаграммы нужны положительные значения")
        cx, cy, r = 300, 320, 190
        a = -90.0
        for i, v in enumerate(pos):
            sweep = 360 * v / total
            if sweep > 0:
                d.pieslice([cx - r, cy - r, cx + r, cy + r], a, a + sweep, fill=PALETTE[i % len(PALETTE)], outline=BG, width=2)
            a += sweep
        for i, (lb, v) in enumerate(zip(labels, pos)):
            y = 100 + i * 20
            if y > H - 30:
                break
            d.rectangle([560, y + 3, 574, y + 17], fill=PALETTE[i % len(PALETTE)])
            d.text((584, y), f"{lb[:22]} — {_fmt(values[i])}{(' ' + unit) if unit else ''} ({100 * v / total:.0f}%)", font=f_s, fill=CREAM)
    else:
        lo, hi = min(0, min(values)), max(0, max(values))
        if hi == lo:
            hi = lo + 1
        tick = _nice_step((hi - lo) / 5)                              # «круглые» деления оси: 0, 10, 20…
        lo, hi = math.floor(lo / tick) * tick, math.ceil(hi / tick) * tick
        if hi == lo:
            hi = lo + tick

        def Y(v):
            return y1 - (v - lo) / (hi - lo) * (y1 - y0)
        v = lo
        while v <= hi + tick * 1e-6:                                 # сетка и подписи оси
            d.line([x0, Y(v), x1, Y(v)], fill=LINE, width=1)
            d.text((x0 - 8, Y(v) - 9), _fmt(round(v, 10)), font=f_s, fill=MUTED, anchor="ra")
            v += tick
        if unit:
            d.text((x0, y0 - 28), unit, font=f_s, fill=MUTED)
        step = (x1 - x0) / n
        zero = Y(0)
        pts = []
        for i, v in enumerate(values):
            cx = x0 + step * (i + 0.5)
            if kind == "line":
                pts.append((cx, Y(v)))
            else:
                bw = min(60, step * 0.62)
                d.rectangle([cx - bw / 2, min(Y(v), zero), cx + bw / 2, max(Y(v), zero)], fill=PALETTE[0])
                if n <= 14:
                    d.text((cx, Y(v) - 6 if v >= 0 else Y(v) + 6), _fmt(v), font=f_s, fill=CREAM, anchor="ms" if v >= 0 else "mt")
            lab = label_img(labels[i], 90 if n > 8 else 0)
            img.paste(lab, (int(cx - lab.width / 2), y1 + 10), lab)
        if kind == "line":
            if len(pts) > 1:
                d.line(pts, fill=BRASS, width=4, joint="curve")
            for (px, py), v in zip(pts, values):
                d.ellipse([px - 6, py - 6, px + 6, py + 6], fill=PALETTE[0], outline=BG, width=2)
                if n <= 12:
                    d.text((px, py - 12), _fmt(v), font=f_s, fill=CREAM, anchor="ms")
        d.line([x0, zero, x1, zero], fill=MUTED, width=2)
    d.text((W - 28, H - 24), "ХРАЗ", font=f_s, fill=LINE, anchor="rs")
    img.save(path, "PNG")


@tool("show_chart", "Нарисовать и показать пользователю график (столбцы, линия или доли) по уже собранным числам. "
      "Используй, когда просят график, диаграмму, динамику или сравнение значений.",
      _CHART, risk="create", summary=lambda a: f"График «{a.get('title', '')}»")
def show_chart(ctx, labels, values, title="", kind="bar", unit=""):
    if len(labels) != len(values) or not values:
        raise ToolError("подписей и значений должно быть поровну, и хотя бы одно")
    nums = [_num(v) for v in values]
    from .files_out import unique_path
    path = unique_path(ctx.cfg, f"график {title or kind}", "png")
    render_chart(path, title, kind, [str(x) for x in labels], nums, unit)
    ctx.file_ready(path)
    return f"График «{title}» показан пользователю ({len(nums)} значений). Не пересказывай числа — скажи один вывод."


