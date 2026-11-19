"""Умения ХРАЗа сверх базовых команд: доклад о состоянии машины и взгляд на экран."""
import base64
import io
import shutil
import subprocess
import sys

IS_WIN = sys.platform == "win32"


def _gb(b):
    return round(b / 1024 ** 3)


def system_report():
    """«ХРАЗ, доклад» — состояние машины одной фразой для озвучки."""
    import psutil
    parts = [f"процессор загружен на {round(psutil.cpu_percent(interval=0.5))} процентов"]
    m = psutil.virtual_memory()
    parts.append(f"память: занято {_gb(m.used)} из {_gb(m.total)} гигабайт")
    gpu = _gpu()
    if gpu:
        parts.append(gpu)
    try:
        d = shutil.disk_usage("C:\\" if IS_WIN else "/")
        parts.append(f"на системном диске свободно {_gb(d.free)} гигабайт")
    except Exception:
        pass
    b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if b:
        parts.append(f"батарея {round(b.percent)} процентов" + (", на зарядке" if b.power_plugged else ""))
    return "Докладываю: " + ", ".join(parts) + "."


def _gpu():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                             creationflags=0x08000000 if IS_WIN else 0).stdout.strip().splitlines()
        if not out:
            return None
        name, temp, util, used, total = [x.strip() for x in out[0].split(",")]
        name = name.replace("NVIDIA", "").replace("Laptop GPU", "").replace("Generation", "").strip()
        return (f"видеокарта {name}: {temp} градусов, загрузка {util} процентов, "
                f"видеопамять {round(int(used) / 1024)} из {round(int(total) / 1024)} гигабайт")
    except Exception:
        return None


def screenshot_b64(max_side=1600):
    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=False).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


SEE_PROMPT = ("Это снимок экрана компьютера пользователя. {q}\nОтвечай по-русски, коротко, по существу: что открыто, "
              "что важно. Не выдумывай того, чего не видно.")
TRANSCRIBE = ("На снимке экрана — задача. Перепиши её условие дословно, формулы в LaTeX ($...$). "
              "Только условие, без решения и комментариев. Если задач несколько — перепиши все.")
