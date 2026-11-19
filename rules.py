"""Быстрый офлайн-разбор типовых фраз без модели. Возвращает список шагов или None."""
import re

from actions import SITES

UNIT = r"(секунд\w*|сек|минут\w*|мин|час\w*)"


def _sec(n, unit):
    n = int(n)
    if unit.startswith("сек"):
        return n
    if unit.startswith("час"):
        return n * 3600
    return n * 60


def _dur(text):
    """'5 минут' / 'минуту' / 'полчаса' / 'час' -> секунды или None"""
    if "полчаса" in text:
        return 1800
    if re.search(r"полтора час", text):
        return 5400
    m = re.search(r"(\d+)\s*" + UNIT, text)
    if m:
        return _sec(m.group(1), m.group(2))
    m = re.search(r"\b(минуту|секунду|час)\b", text)
    if m:
        return _sec(1, m.group(1))
    return None


def S(t, p=""):
    return {"type": t, "param": str(p)}


def parse(t):
    t = t.strip()
    if not t:
        return None

    # время / дата
    if re.search(r"(который час|сколько времени|сколько сейчас времени)", t):
        return [S("tell_time")]
    if re.search(r"(какое сегодня число|какой сегодня день|какое число)", t):
        return [S("tell_date")]

    # погода / курс
    if re.search(r"погод|дожд|зонт|снег будет|холодно ли|тепло ли|сколько градусов|какая температура", t) \
            and not re.match(r"(открой|покажи сайт)", t):
        day = "2" if "послезавтра" in t else ("1" if "завтра" in t else "0")
        m = re.search(r"\b(?:в|во)\s+([а-яa-z\-]+(?:\s+[а-яa-z\-]+)?)", t)
        city = ""
        if m:
            city = re.sub(r"\s+(сегодня|завтра|послезавтра|сейчас|будет)\b.*$", "", m.group(1)).strip()
        return [S("weather", f"{city}|{day}")]
    if re.search(r"курс|сколько стоит (доллар|евро|юань)", t):
        code = "EUR" if "евро" in t else ("CNY" if "юан" in t else "USD")
        return [S("currency", code)]

    # ютуб / поиск
    m = re.match(r"(?:найди|включи|поставь|покажи|открой)\s+(?:на|в)\s+(?:ютуб\w*|youtube)\s+(.+)", t) \
        or re.match(r"(?:ютуб|youtube)\s+(.+)", t)
    if m:
        return [S("youtube_search", m.group(1))]
    m = re.match(r"(?:найди в интернете|загугли|погугли|найди в гугле|поищи|найди(?! на странице))\s+(.+)", t)
    if m:
        return [S("web_search", m.group(1))]

    # громкость / яркость
    m = re.search(r"громкость\s*(?:на\s*)?(\d+)", t)
    if m:
        return [S("volume", m.group(1))]
    if re.search(r"(выключи звук|без звука|включи звук|замолчи звук)", t):
        return [S("mute")]
    if re.search(r"(громче|прибавь звук|увеличь громкость)", t):
        return [S("volume_up", "10")]
    if re.search(r"(тише|убавь звук|уменьши громкость)", t):
        return [S("volume_down", "10")]
    m = re.search(r"яркость\s*(?:на\s*)?(\d+)", t)
    if m:
        return [S("brightness", m.group(1))]

    # медиа
    if re.fullmatch(r"(пауза|стоп музыка|продолжи|играй)", t):
        return [S("media", "pause")]
    if re.search(r"следующ\w* (трек|песн\w*|видео)", t):
        return [S("media", "next")]
    if re.search(r"предыдущ\w* (трек|песн\w*|видео)", t):
        return [S("media", "prev")]

    # питание
    if re.search(r"отмени\w* выключени", t):
        return [S("cancel_shutdown")]
    m = re.search(r"выключи\w*\s+(?:компьютер|комп|пк)(.*)", t)
    if m:
        d = _dur(m.group(1))
        return [S("shutdown", (d or 0) // 60)]
    if re.search(r"перезагру\w*", t):
        return [S("restart")]
    if re.search(r"(спящий режим|усыпи)", t):
        return [S("sleep_pc")]
    if re.search(r"(заблокируй|блокировка)", t):
        return [S("lock")]

    # окна / экран
    if re.fullmatch(r"сверни( это| текущее)? окно", t):
        return [S("window", "minimize")]
    if re.fullmatch(r"(разверни|раскрой)( это| текущее)?( окно)?( на весь экран)?", t):
        return [S("window", "maximize")]
    if re.search(r"(на весь экран|полноэкранный)", t):
        return [S("window", "fullscreen")]
    if re.fullmatch(r"окно (влево|налево)", t):
        return [S("window", "left")]
    if re.fullmatch(r"окно (вправо|направо)", t):
        return [S("window", "right")]
    if re.fullmatch(r"(переключи окно|следующее окно|другое окно)", t):
        return [S("window", "switch")]
    if re.fullmatch(r"(покажи )?рабочий стол", t):
        return [S("window", "desktop")]
    m = re.match(r"(?:переключись|перейди|переключи)\s+(?:на|в)\s+(.+)", t)
    if m:
        return [S("focus_window", m.group(1))]
    if re.search(r"свер\w+\s+(все|всё|окна)", t):
        return [S("minimize_all")]
    if re.search(r"(закрой|закрыть|убери)\s+(все|всё)\b", t) or re.search(r"закрой\w*\s+(окна|программы|приложения)", t):
        return [S("close_all_windows")]
    if re.fullmatch(r"закрой (это )?(окно|это)", t):
        return [S("close_window")]
    if re.fullmatch(r"закрой (эту )?вкладку", t):
        return [S("close_tab")]
    if re.search(r"скрин", t):
        return [S("screenshot")]

    # таймер / напоминание
    if re.search(r"таймер", t):
        d = _dur(t)
        if d:
            return [S("timer", d)]
    m = re.match(r"напомни\s+(?:мне\s+)?(?:через\s+)?(.*)", t)
    if m:
        rest = m.group(1)
        d = _dur(rest) or 600
        text = re.sub(r"^(\d+\s*" + UNIT + r"|полчаса|минуту|час)\s*", "", rest).strip()
        return [S("remind", f"{d}|{text}")]

    # клавиши, правка, мышь
    m = re.match(r"нажми\s+(?:на\s+)?(?:клавиш\w+\s+|кнопк\w+\s+)?(.+)", t)
    if m and not re.search(r"мыш", t):
        return [S("press_key", m.group(1))]
    for pat, op in ((r"сохрани( файл| документ| это)?", "save"), (r"выдели (все|всё|весь текст)", "select_all"),
                    (r"(скопируй|копируй)( это| текст)?", "copy"), (r"вставь( текст| это)?", "paste"),
                    (r"вырежи( это)?", "cut"), (r"(отмени действие|отмени последнее|верни как было)", "undo"),
                    (r"повтори действие", "redo"), (r"(открой )?новую? вкладку", "new_tab"),
                    (r"(верни|восстанови) вкладку", "reopen_tab"), (r"(новая строка|с новой строки|абзац)", "newline"),
                    (r"обнови( страницу)?", "refresh"), (r"(назад|вернись назад)", "back"), (r"вперед", "forward"),
                    (r"(крупнее|увеличь масштаб|приблизь)", "zoom_in"), (r"(мельче|уменьши масштаб|отдали)", "zoom_out"),
                    (r"(найди на странице|поиск по странице)", "find")):
        if re.fullmatch(pat, t):
            return [S("edit", op)]
    if re.search(r"(прокрути|листай|пролистай|скролл)\w*\s*(вниз|ниже)?$", t) and "вверх" not in t:
        return [S("mouse", "scroll_down")]
    if re.search(r"(прокрути|листай|пролистай)\w*\s*(вверх|выше)", t):
        return [S("mouse", "scroll_up")]
    if re.search(r"двойной клик", t):
        return [S("mouse", "double_click")]
    if re.search(r"(правый клик|правой кнопкой)", t):
        return [S("mouse", "right_click")]
    if re.fullmatch(r"(кликни|клик|нажми мышкой|щелкни)", t):
        return [S("mouse", "click")]

    # печать / сочинение
    m = re.match(r"напиши\s+в\s+(блокнот\w*|ворд\w*|word)\s+(.+)", t)
    if m:
        app = "notepad" if m.group(1).startswith("блокнот") else "winword"
        return [S("open_app", app), compose("напиши", m.group(2))]
    m = re.match(r"(?:напечатай|введи|набери)\s+(.+)", t)
    if m:
        return [compose("введи", m.group(1))]

    # папки, параметры Windows, корзина
    if re.search(r"очисти\w*\s+корзин", t):
        return [S("empty_bin")]
    m = re.match(r"(?:открой|покажи)\s+(?:настройки|параметры)\s+(.+)", t)
    if m:
        return [S("open_settings", m.group(1))]
    m = re.match(r"(?:открой|покажи)\s+(папку\s+.+|загрузки|документы|рабочий стол|изображения|картинки|музыку|"
                 r"видео|скриншоты|диск \w|этот компьютер|корзину|автозагрузку)$", t)
    if m:
        return [S("open_folder", m.group(1))]

    # открыть / закрыть
    m = re.match(r"(?:открой|запусти|включи)\s+(.+)", t)
    if m:
        target = m.group(1).strip()
        if target in SITES:
            return [S("open_url", SITES[target])]
        return [S("open_app", target)]
    m = re.match(r"(?:закрой|выключи|вырубай)\s+(.+)", t)
    if m:
        return [S("close_app", m.group(1))]

    return None


SPLIT = re.compile(r"\s*(?:,|;|\bи потом\b|\bпотом\b|\bзатем\b|\bа также\b|\bи\b)\s*")


VERB_SPLIT = re.compile(r"\s+(?=(?:открой|запусти|закрой|включи|выключи|громкость|яркость|найди|сверни|"
                        r"поставь|напомни|скриншот|сделай скриншот|заблокируй|напечатай|отмени|нажми|сохрани|"
                        r"переключись|прокрути|разверни)\b)")


def _segment(part):
    """Vosk не ставит запятых: 'открой ютуб громкость 20' -> ['открой ютуб', 'громкость 20']."""
    pieces = VERB_SPLIT.split(part)
    out, cur = [], pieces[0]
    for nxt in pieces[1:]:
        if parse(cur) is None:
            cur = f"{cur} {nxt}"
        else:
            out.append(cur)
            cur = nxt
    out.append(cur)
    return out


COMPOSE = re.compile(r"^(стих|письмо|рассказ|сочинение|эссе|список|поздравлени|код|программ|истори|анекдот|"
                     r"стать|план|резюме|заметку про|текст про|текст о|текст на тему|пост|сообщение для|отзыв|"
                     r"шутк|сказк|песн|инструкци|объявлени|ответ на|пару строк)")


def compose(verb, body):
    """«напиши стих про осень» -> модель сочиняет; «напиши привет мир» / «введи …» -> печатаем как сказано."""
    body = re.sub(r"^(текст|фразу|слова|следующее)\s+(?!про|о\b|на тему)", "", body.strip())
    if verb == "напиши" and COMPOSE.match(body):
        return S("write_ai", body)
    return S("type_text", body[:1].upper() + body[1:])


TYPE_TAIL = re.compile(r"^(.*?)\s*(?:,|\bи\b|\bпотом\b|\bзатем\b)?\s*\b(напиши|введи|напечатай|набери)\s+(.+)$")
END_TAIL = re.compile(r"\s+(?:и\s+|потом\s+)?(нажми (?:энтер|ввод|enter|интер)|сохрани(?: файл| документ)?)$")


def parse_many(t):
    """Цепочка с вводом текста: всё после «напиши/введи» — это текст, его не режем по «и»."""
    m = TYPE_TAIL.match(t)
    if m and m.group(1).strip():
        head = _parse_many(m.group(1))
        if head is None:
            return None
        body, tail = m.group(3), []
        e = END_TAIL.search(body)
        if e:
            tail = parse(e.group(1)) or []
            body = body[:e.start()]
        return head + [compose(m.group(2), body)] + tail
    return _parse_many(t)


def _parse_many(t):
    """'открой стим и дискорд, потом громкость 30' -> шаги. None, если хоть кусок не понят."""
    parts = [s for p in SPLIT.split(t) if p for s in _segment(p)]
    steps, last_verb = [], None
    for p in parts:
        r = parse(p)
        if r is None and last_verb:          # «открой стим и дискорд» — глагол переносится
            r = parse(f"{last_verb} {p}")
        if r is None:
            return None
        verb = p.split()[0]
        if verb in ("открой", "запусти", "закрой", "включи"):
            last_verb = verb
        steps += r
    return steps or None
