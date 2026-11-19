"""Выбор модели под запрос — и понятная причина выбора для интерфейса.

- основная (qwen3.5:9b): разговор, голос, изображения, простые инструменты — по умолчанию;
- умная (gpt-oss:20b): сложные многоэтапные вопросы, планирование, анализ, несколько действий подряд;
- кодовая (qwen3.6:27b-coding): программирование — ТОЛЬКО по явной команде («режим кода», «кодовой моделью»).
  Если вопрос похож на программирование, но команды не было, — отвечает основная/умная, а в причине подсказка.
Ручной режим (Настройки или голосом) важнее эвристик."""
import re
from dataclasses import dataclass

ROLE_NAMES = {"fast": "основная", "smart": "для сложных задач", "code": "для кода"}

# явная команда на кодовую модель (в начале фразы или отдельным оборотом)
CODE_EXPLICIT = re.compile(r"(режим кода|режим программиста|кодов\w+ модел\w*|кодер\w*|через кодер|"
                           r"модел\w+ для кода|^код\s*[:,]|^программист\s*[:,])")
CODE_HINT = re.compile(r"(код\b|кода\b|функци\w|скрипт|программ\w|python|питон|php|laravel|javascript|sql|"
                       r"класс\w*\b|баг|ошибк\w+ в коде|рефактор|регулярк|алгоритм|компил|traceback)")
SMART_EXPLICIT = re.compile(r"(подумай (хорошенько|как следует|глубже|серьёзно)|глубок\w+ анализ|"
                            r"умн\w+ модел\w*|сложн\w+ модел\w*)")
FAST_EXPLICIT = re.compile(r"(быстро ответь|коротко ответь|кратко ответь|быстрой модел\w*)")
SMART_HINT = re.compile(r"(составь план|спланируй|план (работ|действий|подготовки|проекта)|пошагов|по шагам|"
                        r"проанализируй|анализ|сравни|сопостав|разработай|спроектируй|стратеги|обоснуй|"
                        r"докажи|выведи формулу|оптимизируй|многоэтап|распиши подробно|исследуй|"
                        r"плюсы и минусы|за и против|архитектур|"
                        r"разбер(и|ись)\w* |помоги разобраться|что (лучше|выбрать)|как лучше|посоветуй|"
                        r"оцени|рассужд|почему так|в чём разница|чем отличается .+ от|"
                        r"составь (расписание|договор|смету|программу|чек-?лист|таблицу)|распиши|разложи)")
MULTI_STEP = re.compile(r"(сначала .+ (потом|затем|после))|(\bзатем\b.+\bпотом\b)|(во-первых.+во-вторых)")


@dataclass
class Choice:
    role: str          # fast | smart | code
    model: str
    reason: str
    long: bool = False  # разрешить развёрнутый ответ

    @property
    def label(self):
        return f"{self.model} — {self.reason}"


def choose(text, cfg, mode="auto"):
    """text — нормализованная фраза пользователя. mode — ручной режим (auto|fast|smart|code)."""
    t = (text or "").lower()
    m = {"fast": cfg["model"], "smart": cfg.get("model_smart") or cfg["model"],
         "code": cfg.get("model_code") or cfg["model"]}
    if mode in ("fast", "smart", "code"):
        return Choice(mode, m[mode], f"выбрано вручную ({ROLE_NAMES[mode]})", long=mode != "fast")
    if CODE_EXPLICIT.search(t):
        return Choice("code", m["code"], "явная команда: программирование", long=True)
    if FAST_EXPLICIT.search(t):
        return Choice("fast", m["fast"], "просили ответить быстро")
    if SMART_EXPLICIT.search(t):
        return Choice("smart", m["smart"], "просили подумать глубже", long=True)
    words = len(t.split())
    hits = [h.group(0) for h in SMART_HINT.finditer(t)]
    if hits:
        return Choice("smart", m["smart"], f"сложный вопрос: «{hits[0]}»", long=True)
    if MULTI_STEP.search(t):
        return Choice("smart", m["smart"], "несколько шагов подряд", long=True)
    if words > 45 or t.count("?") >= 3:
        return Choice("smart", m["smart"], "длинный многочастный вопрос", long=True)
    if CODE_HINT.search(t):
        return Choice("fast", m["fast"], "похоже на программирование — для кодовой модели скажите «режим кода»")
    return Choice("fast", m["fast"], "обычный вопрос")


_LLM_CACHE = {}
LLM_SCHEMA = {"type": "object", "properties": {"level": {"type": "string", "enum": ["simple", "complex"]}},
              "required": ["level"]}
LLM_PROMPT = ("Определи сложность запроса пользователя. simple — приветствие, короткий вопрос, один факт, команда, "
              "бытовая просьба. complex — нужно рассуждение, анализ, сравнение, план, несколько шагов, развёрнутый "
              "или точный ответ (математика, право, архитектура). Ответь JSON: {\"level\": \"simple\" | \"complex\"}.")


def pick(text, cfg, mode="auto", llm=None):
    """choose() + (по желанию, cfg["router_llm"]) уточнение моделью: только когда правила ничего не нашли, а фраза
    длинная. Классификатор — основная модель, ждём не дольше 5 с; не ответила → остаёмся на основной."""
    c = choose(text, cfg, mode)
    t = (text or "").strip().lower()
    if not (cfg.get("router_llm") and llm and mode == "auto" and c.reason == "обычный вопрос" and len(t.split()) >= 10):
        return c
    if t not in _LLM_CACHE:
        import threading
        box = {}

        def work():
            try:
                box["r"] = llm.json([{"role": "system", "content": LLM_PROMPT}, {"role": "user", "content": t[:600]}],
                                    LLM_SCHEMA, model=cfg["model"])
            except Exception:       # noqa: BLE001
                box["r"] = {}
        th = threading.Thread(target=work, daemon=True)
        th.start()
        th.join(5)
        if len(_LLM_CACHE) > 200:
            _LLM_CACHE.clear()
        _LLM_CACHE[t] = (box.get("r") or {}).get("level", "simple")
    if _LLM_CACHE[t] == "complex":
        return Choice("smart", cfg.get("model_smart") or cfg["model"], "модель сочла вопрос сложным", long=True)
    return c


def for_actions(text, cfg, mode="auto"):
    """Выбор модели для инструментов: несколько действий / план — умная, иначе основная.
    Кодовая модель инструментами не управляет."""
    c = choose(text, cfg, "fast" if mode == "code" else mode)
    if c.role == "code":
        return Choice("fast", cfg["model"], "действия выполняет основная модель")
    if c.role == "fast" and len(re.findall(r"\b(и|потом|затем|а также)\b", text or "")) >= 2:
        return Choice("smart", cfg.get("model_smart") or cfg["model"], "многоэтапное действие")
    if c.role == "smart" and "вручную" not in c.reason:
        c.reason = "многоэтапное действие" if MULTI_STEP.search(text or "") else c.reason
    return c


MODE_ON = {
    "code": re.compile(r"(включи|перейди в|переключись в|давай) (режим кода|режим программиста)"),
    "smart": re.compile(r"(включи|перейди в|переключись в) (умный режим|режим размышлений|сложный режим)"),
    "fast": re.compile(r"(включи|перейди в|переключись в) (быстрый режим)"),
    "auto": re.compile(r"(обычный режим|автоматический (выбор|режим)|выключи режим (кода|программиста)|"
                       r"верни (обычный|авто) режим)"),
}


def mode_command(text):
    """Голосовое переключение режима: возвращает auto|fast|smart|code или None."""
    for mode, rx in MODE_ON.items():
        if rx.search(text or ""):
            return mode
    return None
