"""Понятные сообщения об ошибках вместо traceback. Полный traceback пишется в logs/khraz.log."""
import logging
import os
import traceback
from logging.handlers import RotatingFileHandler

from config import DATA

LOG_DIR = os.path.join(DATA, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
log = logging.getLogger("khraz")
if not log.handlers:
    h = RotatingFileHandler(os.path.join(LOG_DIR, "khraz.log"), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)


def human(e, cfg=None):
    """Исключение → одна-две фразы, что случилось и что сделать. Технические детали — в лог."""
    log.error("%s: %s\n%s", type(e).__name__, e, "".join(traceback.format_exception(type(e), e, e.__traceback__)))
    try:
        import requests
        from llm import ModelMissing
    except Exception:          # pragma: no cover
        requests = ModelMissing = None
    url = (cfg or {}).get("ollama_url", "http://localhost:11434")
    if ModelMissing and isinstance(e, ModelMissing):
        return f"Модель {e.model} не установлена. Выполните в терминале: `ollama pull {e.model}`"
    if requests and isinstance(e, requests.ConnectionError):
        return (f"Ollama не отвечает по адресу {url}. Запустите Ollama (значок в трее или `ollama serve`) "
                "или исправьте адрес в «Настройках».")
    if requests and isinstance(e, requests.Timeout):
        return "Модель отвечает слишком долго. Возможно, она ещё загружается в видеопамять — повторите через минуту."
    if requests and isinstance(e, requests.HTTPError):
        code = getattr(e.response, "status_code", "?")
        if code == 500:
            return ("Ollama не смогла выполнить запрос (ошибка 500). Часто это нехватка видеопамяти — "
                    "закройте другие модели или выберите модель поменьше.")
        return f"Ollama вернула ошибку {code}."
    if isinstance(e, FileNotFoundError):
        return f"Файл не найден: {getattr(e, 'filename', '') or e}."
    if isinstance(e, PermissionError):
        return f"Нет доступа: {getattr(e, 'filename', '') or e}."
    if isinstance(e, (ValueError, KeyError, TypeError)) and str(e):
        return f"Не получилось: {str(e)[:200]}"
    return f"Что-то пошло не так ({type(e).__name__}). Подробности записаны в logs/khraz.log."
