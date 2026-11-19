import json
import os

import sys

BASE = os.path.dirname(os.path.abspath(__file__))       # код и ресурсы (в exe — папка _internal)
FROZEN = bool(getattr(sys, "frozen", False))


def _data_dir():
    """Данные пользователя: рядом с кодом при запуске из исходников; в установленном exe — %APPDATA%\\KHRAZ
    (Program Files только для чтения). KHRAZ_DATA переопределяет."""
    d = os.environ.get("KHRAZ_DATA")
    if not d and FROZEN:
        d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "KHRAZ")
    d = d or BASE
    os.makedirs(d, exist_ok=True)
    return d


DATA = _data_dir()
CONFIG_PATH = os.path.join(DATA, "config.json")


def resolve(path):
    """Относительный путь к моделям/кэшу: сначала в данных пользователя, затем рядом с кодом."""
    if os.path.isabs(path):
        return path
    for root in (DATA, BASE):
        cand = os.path.join(root, path)
        if os.path.exists(cand):
            return cand
    return os.path.join(DATA, path)

CONFIG_VERSION = 2

DEFAULTS = {
    "config_version": CONFIG_VERSION,
    "ollama_url": "http://localhost:11434",
    # Запасной Ollama: когда основной (ноутбук с RTX 5000 Ada, http://<IP-ноутбука>:11434) выключен или недоступен,
    # ХРАЗ сам переходит на него и на model_fallback. Пусто — запасного нет.
    "ollama_url_fallback": "",
    "model_fallback": "qwen3:4b",
    # Модели (выбор и причина — router.py). Одновременно в видеопамяти держится только одна крупная.
    "model": "qwen3.5:9b",           # основная: диалог, голос, изображения, простые инструменты
    "model_smart": "gpt-oss:20b",    # сложные вопросы, планирование, многоэтапные действия
    "model_code": "qwen3.6:27b-coding",  # программирование — ТОЛЬКО по явной команде («режим кода»)
    "embed_model": "bge-m3",         # поиск по долговременной памяти
    "vision_model": "qwen3.5:9b",    # «что на экране» — та же основная модель: вторая не загружается
    "model_mode": "auto",            # auto | fast | smart | code — ручной выбор во вкладке «Настройки»
    "keep_alive": "30m",             # основная модель остаётся в памяти — без задержки на загрузку
    "keep_alive_large": "5m",        # крупные модели выгружаются быстро и сразу при переключении
    "text_detail": "full",           # full — на экране полный оформленный ответ, вслух только итог; short — как 26.10 (1–4 предложения)
    "short_answers": True,           # по умолчанию 1–4 предложения, «продолжи» — подробнее
    "max_tokens_short": 400,
    "max_tokens_long": 1600,
    "personality": True,             # false — без характера ХРАЗа (нейтральный ассистент)
    # слова активации: первые четыре — основные, остальные — как их иногда слышит Vosk
    "wake_words": ["храз", "хранитель знаний", "хранитель", "харитон", "захаров",
                   "хряз", "хараз", "храс", "краз", "хрaз", "фраз", "харитона"],
    "wake_spotter": True,
    "barge_in": True,                # пока ХРАЗ говорит, «стоп / хватит / замолчи» обрывают речь            # второй распознаватель Vosk со словарём только из слов активации
    "vosk_model": "models/vosk-model-small-ru-0.22",
    "stt_engine": "vosk",            # "whisper" — Vosk слушает и ловит «ХРАЗ», а текст фразы перераспознаёт Whisper (pip install faster-whisper)
    "whisper_model": "small",        # small (~0,5 ГБ) · medium · large-v3-turbo (точнее, но занимает видеопамять рядом с Ollama)
    "whisper_device": "auto",        # auto (видеокарта, иначе процессор) · cuda · cpu
    "whisper_compute": "auto",       # auto · float16 · int8
    "whisper_dir": "models/whisper",
    "whisper_beam": 1,
    "whisper_prompt": "ХРАЗ. Хранитель знаний. Ollama, Claude Code, Codex.",
    "mic_device": None,
    "awake_seconds": 12,
    "city": "Балашиха",
    "tts_engine": "fish",            # fish (голос ХРАЗа с fish.audio) | piper (офлайн) | sapi | silero
    "fish_api_key": "",
    "fish_voice_id": "",
    "fish_model": "s1",              # s1 | s2-pro | s2.1-pro | s2.1-pro-free
    "fish_latency": "balanced",      # low | balanced | normal — ниже задержка / выше качество
    "fish_fx": False,
    "piper_voice": "models/piper/ru_RU-dmitri-medium.onnx",
    "speech_slowness": 1.0,
    "voice_pitch": 0.94,
    "jarvis_fx": True,               # «металл» для Piper
    "silero_speaker": "eugene",
    "sapi_rate": 0,
    "max_tokens": 700,
    "num_ctx": 16384,                # окно контекста: личность + архив + история; на RTX 5000 Ada с 14b хватает
    "voice_confirm_local": True,     # опасные ДЕЙСТВИЯ НА ПК можно подтвердить голосом «да» (кнопкой — всегда).
    "speak_long_answers": False,     # длинные ответы (решения, код): вслух только первые фразы, остальное — на экране
    "tts_enabled": True,
    "llm_router": True,
    "router_llm": False,             # уточнять выбор модели для длинных фраз без ключевых слов (+1 быстрый вызов)
    "history_len": 16,
    # Инструменты (tools/): модель не получает shell — только эти функции.
    "allowed_apps": {                # «открой …» из модели — только отсюда (имя → команда/путь)
        "блокнот": "notepad", "калькулятор": "calc", "проводник": "explorer", "браузер": "chrome",
        "chrome": "chrome", "telegram": "telegram", "discord": "discord", "steam": "steam",
        "vs code": "code", "word": "winword", "excel": "excel", "spotify": "spotify", "obs": "obs",
        "диспетчер задач": "taskmgr", "paint": "mspaint", "параметры": "ms-settings:",
        # игры: ссылки Steam / Microsoft Store (проверьте свои: Steam → ПКМ по игре → Свойства; PowerShell: Get-StartApps)
        "atomic heart": "steam://rungameid/668580",
        "minecraft": "shell:AppsFolder\\Microsoft.4297127D64EC6_8wekyb3d8bbwe!Minecraft"},
    # Произвольный PowerShell для модели. Выключен. Каждая команда — только после подтверждения КНОПКОЙ (голос не принимается)
    # и только когда в реплике прямо сказано «powershell / выполни команду / терминал».
    "allow_shell": False,
    # Показывать модели не все инструменты сразу, а ядро + нужную группу (файлы, память, система).
    # Включайте после замера: python tests/eval_tools.py --model <модель> и то же с --grouped.
    "tool_groups": False,
    # Кодовые агенты Claude Code и Codex (coder.py): без проектов инструменты не показываются.
    "coder_projects": {},            # {"myproject": "C:/Projects/myproject"} — только отсюда агент получает рабочую папку
    "coder_default": "claude",
    "coder_allow_edit": True,        # режим edit (правки файлов); подтверждается только в окне ХРАЗа
    "coder_continue": True,          # Claude Code: продолжать недавнюю сессию проекта (контекст сохраняется)
    "coder_timeout": 900,
    "coder_paths": {},               # {"claude": "C:/Users/me/AppData/Roaming/npm/claude.cmd"}, если не находится в PATH
    "coder_agents": {},              # переопределение шаблонов команд, если у вас другая версия CLI (см. coder.py)
    "wol_mac": "",                   # MAC ноутбука с RTX (AA:BB:CC:DD:EE:FF) → инструмент «разбуди ноутбук» (Wake-on-LAN)
    "wol_broadcast": "255.255.255.255",
    # Источники логов для read_log (только чтение): файл или ssh по ключу. Модель выбирает только имя.
    "log_sources": [],               # [{"name": "app", "type": "file", "path": "C:/.../app.log"},
                                     #  {"name": "prod", "type": "ssh", "host": "deploy@1.2.3.4", "port": 22, "path": "/var/log/app.log"}]
    "search_roots": ["~/Documents", "~/Desktop", "~/Downloads"],   # где искать и читать файлы
    "forbidden_paths": ["~/research"],                              # сюда ХРАЗ не заглядывает и не пишет
    "notes_dir": "~/Documents/ХРАЗ заметки",
    "notes_autosave": True,          # результаты правил, утренняя сводка, ответы Клода и таблицы — заметками .md в «Отчёты ХРАЗ»
    "outputs_dir": "~/Documents/ХРАЗ файлы",   # файлы, которые ХРАЗ создаёт для скачивания
    # Сторонние MCP-серверы (как в Claude Desktop): секреты — в хранилище Windows (Коннекторы → «Секреты…»)
    "mcp_servers": [],               # [{"name": "github", "type": "stdio", "command": "npx", "args": [...],
                                     #   "url": "", "keywords": "github, гитхаб", "trust": "ask", "enabled": true}]
    "memory_top_k": 6,               # сколько записей памяти подмешивать в разговор
    # ХРАЗ начинает сам (watcher.py)
    "proactive": True,               # следить за делами и сообщать о важном
    "watch_interval_min": 5,
    "morning_time": "08:30",         # утренний доклад (пусто — выключен)
    "quiet_hours": "23:00-08:00",    # тихие часы: сообщения только текстом
    "screen_watch_sec": 20,          # «наблюдай за экраном»: как часто смотреть
    "screen_watch_min": 30,          # …и сколько минут
    # Опыт и знания
    "suggest_commands": True,        # «вы третий раз делаете X — сделать командой?»
    "kb_folders": [],                # база знаний: папки с конспектами, договорами, заметками
    "kb_auto": True,                 # подмешивать найденное в базе знаний в ответы
    # Интерфейс
    "sfx": True,                     # звуки интерфейса
    "hotkey": "win+shift+x",         # компактное окно поверх всех окон
}


def load():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            print("config.json не прочитан:", e)
    if cfg.get("config_version", 1) < CONFIG_VERSION:
        # старый config.json (qwen3:14b + gemma3:12b): переходим на новый набор моделей
        for k in ("model", "vision_model", "keep_alive", "config_version"):
            cfg[k] = DEFAULTS[k]
        cfg["_migrated"] = True
    p = cfg["vosk_model"]
    cfg["vosk_model_abs"] = resolve(p)
    return cfg


def save(cfg):
    data = {k: v for k, v in cfg.items() if k in DEFAULTS}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
