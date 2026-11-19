"""Запуск: python main.py        — окно ХРАЗа
          python main.py --cli  — консоль (ввод текстом + микрофон)
          KHRAZ.exe --run-py script.py — служебно: выполнить встроенный скрипт (MCP-шлюз) внутри exe"""
import sys

if len(sys.argv) > 2 and sys.argv[1] == "--run-py":          # до импорта Qt и прочего — быстро и без окна
    import os
    import runpy
    _script = sys.argv[2]
    sys.argv = [_script] + sys.argv[3:]
    sys.path.insert(0, os.path.dirname(os.path.abspath(_script)))
    runpy.run_path(_script, run_name="__main__")
    sys.exit(0)

import config  # noqa: E402
from brain import Brain  # noqa: E402
from commands import Store  # noqa: E402
from llm import LLM  # noqa: E402
from stt import STT  # noqa: E402
from tts import TTS  # noqa: E402


class ConsoleUI:
    def status(self, s): pass
    def partial(self, t): pass
    def user(self, t): print(f"\n> {t}")
    def assistant(self, t): print(f"ХРАЗ: {t}")
    def assistant_start(self): print("ХРАЗ: ", end="", flush=True)
    def assistant_token(self, tok): print(tok, end="", flush=True)
    def assistant_done(self, text): print()
    def commands_changed(self): pass
    def confirm(self, op_id, title, md, voice_ok):
        print(f"\n=== ТРЕБУЕТСЯ РЕШЕНИЕ: {title} ===\n{md}\n/ok {op_id}  — подтвердить,  /no {op_id} — отклонить")
    def resolve(self, op_id, text): print(f"[{op_id}] {text}")
    def model_info(self, model, reason): print(f"[модель] {model} — {reason}")
    def action(self, text): text and print(f"[действие] {text}")
    def offer_more(self): print("[скажите «подробнее», чтобы продолжить]")
    def tool_start(self, cid, name, args): print(f"[запрос] {name} {args[:300]}")
    def tool_end(self, cid, ok, result): print(f"[{'готово' if ok else 'ошибка'}] {result[:300]}")
    def file_ready(self, path): print(f"[файл] {path}")


def build(ui):
    cfg = config.load()
    llm = LLM(cfg)
    tts = TTS(cfg, on_state=lambda s: ui.status(s), on_error=ui.assistant)
    store = Store()
    brain = Brain(cfg, llm, tts, store, ui)
    stt = STT(cfg, on_final=brain.hear, on_partial=ui.partial, is_muted=tts.busy, on_stop=brain.stop)
    stt.on_note = ui.assistant          # «Whisper готов» / «Whisper недоступен» — текстом, без озвучки
    return cfg, llm, tts, store, brain, stt


def cli():
    ui = ConsoleUI()
    cfg, llm, tts, store, brain, stt = build(ui)
    if not stt.start():
        print(stt.error, "— работаю только с текстом")
    import re
    import startup
    print(re.sub(r"[*`]", "", startup.check(cfg).markdown()))
    print("Пиши фразы (без «ХРАЗ») или говори «ХРАЗ, ...». Ctrl+C — выход.")
    brain.greet()
    try:
        while True:
            line = input()
            if line.startswith(("/ok ", "/no ")):        # консольный аналог кнопок
                (brain.approve if line.startswith("/ok") else brain.reject)(line.split()[1])
            elif line.strip():
                brain.type(line)
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    if "--cli" in sys.argv:
        cli()
    else:
        from ui import run_gui
        run_gui(build)
