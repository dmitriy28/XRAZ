"""Первая настройка без setup.bat (для установленного exe): скачать модель речи Vosk и голос Piper
в папку данных пользователя. Вызывается из окна, если моделей нет."""
import os
import shutil
import tempfile
import zipfile

import requests

from config import DATA

VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
PIPER_URL = ("https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/dmitri/medium/"
             "ru_RU-dmitri-medium.onnx")


def _download(url, dest, progress=None):
    tmp = dest + ".part"
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, -10
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
                pct = int(done * 100 / total) if total else 0
                if progress and pct >= last + 10:
                    last = pct
                    progress(pct)
    os.replace(tmp, dest)


def ensure_vosk(progress=None):
    target = os.path.join(DATA, "models", "vosk-model-small-ru-0.22")
    if os.path.isdir(target):
        return target
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="khraz_vosk_")
    try:
        z = os.path.join(tmpdir, "vosk.zip")
        _download(VOSK_URL, z, progress)
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():                       # без выхода за пределы папки
                if n.startswith("/") or ".." in n.split("/"):
                    raise RuntimeError("подозрительный архив модели")
            zf.extractall(os.path.dirname(target))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return target


def ensure_piper(progress=None):
    d = os.path.join(DATA, "models", "piper")
    os.makedirs(d, exist_ok=True)
    onnx = os.path.join(d, "ru_RU-dmitri-medium.onnx")
    if not os.path.exists(onnx):
        _download(PIPER_URL, onnx, progress)
    if not os.path.exists(onnx + ".json"):
        _download(PIPER_URL + ".json", onnx + ".json")
    return onnx
