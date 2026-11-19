"""Проверка при запуске: доступна ли Ollama, установлены ли модели. Для недостающих — точная команда ollama pull.

Windows + WSL: если Ollama не отвечает по адресу из настроек, пробуем localhost/127.0.0.1, а изнутри WSL —
адрес Windows-хоста (шлюз по умолчанию). Рабочий адрес предлагается, но в настройки сам не записывается."""
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

import requests

ROLE_TEXT = {"model": "основная (диалог, голос, изображения)", "model_smart": "сложные вопросы и планирование",
             "model_code": "программирование (по команде)", "embed_model": "поиск по памяти",
             "vision_model": "что на экране"}


@dataclass
class Report:
    ollama: bool = False
    version: str = ""
    url: str = ""
    suggested_url: str = ""
    present: dict = field(default_factory=dict)      # ключ настройки → модель
    missing: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    @property
    def ok(self):
        return self.ollama and "model" not in self.missing

    def pull_commands(self):
        return [f"ollama pull {m}" for m in dict.fromkeys(self.missing.values())]

    def markdown(self):
        if not self.ollama:
            md = (f"**Ollama не отвечает** по адресу `{self.url}`.\n\n"
                  "- Windows: запустите Ollama (значок в трее) или выполните `ollama serve`.\n"
                  "- WSL: в Ubuntu выполните `ollama serve`; ХРАЗ на Windows подключится к `http://localhost:11434`.\n")
            if self.suggested_url:
                md += f"\nOllama нашлась по адресу `{self.suggested_url}` — укажите его в «Настройках»."
            return md
        md = f"**Ollama {self.version}** · `{self.url}`\n\n"
        for k, m in self.present.items():
            md += f"- ✅ {ROLE_TEXT.get(k, k)}: `{m}`\n"
        for k, m in self.missing.items():
            md += f"- ❌ {ROLE_TEXT.get(k, k)}: `{m}` не установлена\n"
        if self.missing:
            md += "\nВыполните в терминале:\n```\n" + "\n".join(self.pull_commands()) + "\n```"
        for n in self.notes:
            md += f"\n\n{n}"
        return md


def _alive(url, timeout=2):
    try:
        return requests.get(url.rstrip("/") + "/api/version", timeout=timeout).json().get("version") or "?"
    except Exception:
        return None


def in_wsl():
    try:
        with open("/proc/version", encoding="utf-8") as f:
            return "microsoft" in f.read().lower()
    except Exception:
        return False


def wsl_host_ip():
    """IP Windows-хоста изнутри WSL2: шлюз по умолчанию (или nameserver из resolv.conf)."""
    try:
        out = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=3).stdout
        m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", out)
        if m:
            return m.group(1)
    except Exception:
        pass
    try:
        with open("/etc/resolv.conf", encoding="utf-8") as f:
            m = re.search(r"nameserver\s+(\d+\.\d+\.\d+\.\d+)", f.read())
            return m.group(1) if m else None
    except Exception:
        return None


def candidates(url):
    out = [url, "http://localhost:11434", "http://127.0.0.1:11434"]
    if in_wsl():
        ip = wsl_host_ip()
        if ip:
            out.append(f"http://{ip}:11434")
    return list(dict.fromkeys(u.rstrip("/") for u in out if u))


def _installed(url):
    try:
        return [m["name"] for m in requests.get(url + "/api/tags", timeout=4).json().get("models", [])]
    except Exception:
        return []


def has_model(name, installed):
    if not name:
        return True
    base = name if ":" in name else name + ":latest"
    return any(m == name or m == base or m.split(":")[0] == name for m in installed)


def check(cfg):
    url = cfg["ollama_url"].rstrip("/")
    r = Report(url=url)
    v = _alive(url)
    if not v:
        for alt in candidates(url)[1:]:
            if _alive(alt):
                r.suggested_url = alt
                break
        return r
    r.ollama, r.version = True, v
    installed = _installed(url)
    for key in ("model", "model_smart", "model_code", "embed_model", "vision_model"):
        m = cfg.get(key)
        if not m or (key == "vision_model" and m == cfg.get("model")):
            continue
        (r.present if has_model(m, installed) else r.missing)[key] = m
    if "model_code" in r.present or "model_code" in r.missing:
        r.notes.append("Кодовая модель 27b больше 16 ГБ видеопамяти: часть слоёв уйдёт на процессор, "
                       "ответы будут медленнее. Включается только по команде «режим кода».")
    if sys.platform != "win32" and not in_wsl():
        r.notes.append("Управление окнами и программами работает только в Windows.")
    elif in_wsl():
        r.notes.append("ХРАЗ запущен внутри WSL: управление окнами Windows недоступно. Для полного управления "
                       "запускайте ХРАЗ в Windows (run.bat), а Ollama может оставаться в WSL.")
    return r


if __name__ == "__main__":       # python startup.py — проверка из консоли
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import config
    rep = check(config.load())
    print(re.sub(r"[*`]", "", rep.markdown()))
    sys.exit(0 if rep.ok else 1)
