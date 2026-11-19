"""Секреты (токены MCP-серверов и др.) — в хранилище Windows (keyring → Диспетчер учётных данных), не в config.json.

Если пакета keyring нет, значения берутся только из переменных окружения."""
import os

SERVICE = "KHRAZ"


def _kr():
    try:
        import keyring
        return keyring
    except Exception:
        return None


def available():
    return _kr() is not None


def get(name):
    kr = _kr()
    if kr:
        try:
            v = kr.get_password(SERVICE, name)
            if v:
                return v
        except Exception:
            pass
    return os.environ.get(name, "")


def set(name, value):  # noqa: A001 — имя как у keyring
    kr = _kr()
    if not kr:
        raise RuntimeError("пакет keyring не установлен: pip install keyring")
    if value:
        kr.set_password(SERVICE, name, value)
    else:
        try:
            kr.delete_password(SERVICE, name)
        except Exception:
            pass


def mask(v):
    return (v[:8] + "…" + v[-4:]) if v and len(v) > 16 else ("задан" if v else "не задан")
