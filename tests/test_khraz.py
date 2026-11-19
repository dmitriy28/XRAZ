"""Тесты клиента ХРАЗа без микрофона, звука и Ollama (модель — сценарная заглушка).
Запуск из папки проекта:  python tests/test_khraz.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import tempfile  # noqa: E402

import chats  # noqa: E402
import config  # noqa: E402
import memory  # noqa: E402
import persona  # noqa: E402
import tools  # noqa: E402
from confirmations import Confirmations  # noqa: E402

# всё, что тесты пишут на диск, — во временную папку (чаты, память, журнал инструментов)
SANDBOX = tempfile.mkdtemp(prefix="khraz_test_")
chats.DIR = os.path.join(SANDBOX, "chats")
memory.PATH = os.path.join(SANDBOX, "memory.json")
memory.OLD_ARCHIVE = os.path.join(SANDBOX, "нет.json")
tools.LOG_PATH = os.path.join(SANDBOX, "tools.jsonl")

PASSED = []


def check(name, cond, info=""):
    if not cond:
        raise AssertionError(f"✗ {name} {info}")
    PASSED.append(name)
    print("✓", name)


class UI:
    def __init__(self):
        self.log, self.cards, self.resolved, self.cab = [], {}, {}, []
    def status(self, s): pass
    def partial(self, t): pass
    def user(self, t): self.log.append(("user", t))
    def assistant(self, t): self.log.append(("bot", t))
    def assistant_start(self): pass
    def assistant_token(self, t): pass
    def assistant_done(self, t): self.log.append(("bot", t))
    def commands_changed(self): pass
    def confirm(self, op_id, title, md, voice_ok): self.cards[op_id] = (title, md, voice_ok)
    def resolve(self, op_id, text): self.resolved[op_id] = text


class TTS:
    def __init__(self): self.said = []
    def say(self, t): self.said.append(t)
    def stop(self): pass
    def mute(self, on): pass
    def busy(self): return False


class ScriptLLM:
    """Отвечает на шаги агента по сценарию: список (text, [(tool, args)])."""
    def __init__(self):
        self.script, self.seen = [], []
    last_done_reason = ""
    def chat_tools(self, msgs, tools, model=None, max_tokens=None):
        self.seen.append(msgs)
        return self.script.pop(0) if self.script else ("Готово.", [])
    def chat(self, msgs, on_token=None, max_tokens=None, model=None, on_thinking=None):
        self.seen.append(msgs)
        on_token and on_token("Ответ.")
        return "Ответ."
    def json(self, msgs, schema):
        return {"intent": "action", "steps": [{"type": "powershell", "param": "New-Item x"}]}


def wait(cond, sec=10):
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_persona():
    cfg = config.load()
    sp = persona.system_prompt(cfg, ["Ученики занимаются по вторникам"])
    check("личность из KHRAZ_PERSONA.md подключена", "Я помню, кем был" in sp)
    check("правила голосового клиента добавлены", "LaTeX" in sp and "1–4" in sp)
    check("архив подмешан как подтверждённые данные", "по вторникам" in sp)
    check("пользователь — майор Нечаев", "майор Сергей Нечаев" in sp and any("майор" in p for p in persona.all_phrases()))
    cfg["personality"] = False
    check("personality=false → нейтральный режим", "Я помню, кем был" not in persona.system_prompt(cfg, []))


def test_confirmations():
    c = Confirmations(ttl=1)
    op = c.create("mcp", {"tool": "invoice.create", "args": {"approved_operation_id": "op1"}}, "t", "p", voice_ok=True)
    check("запись через MCP голосом не подтверждается", c.take(op.id, "voice")[0] is None)
    check("кнопкой — подтверждается", c.take(op.id, "ui")[0] is not None)
    check("повторное подтверждение отклоняется", c.take(op.id, "ui")[0] is None)
    op2 = c.create("local", {"steps": []}, "t", "p", voice_ok=True)
    check("действие на ПК голосом — можно (настройка)", c.take(op2.id, "voice")[0] is not None)
    op3 = c.create("local", {"steps": []}, "t", "p", voice_ok=True)
    time.sleep(1.1)
    check("просроченное подтверждение не выполняется", c.take(op3.id, "ui")[0] is None)



def test_stop():
    """«СТОП» рвёт потоковый ответ Ollama: возвращается то, что успели написать."""
    import json as _j
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from llm import LLM, Cancelled

    class Slow(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        protocol_version = "HTTP/1.1"          # как Ollama: chunked-поток

        def do_POST(self):
            body = _j.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            if not body.get("stream"):           # долгий ответ без потока (как chat_tools)
                time.sleep(3)
                data = _j.dumps({"message": {"content": "поздно"}}).encode()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except OSError:
                    pass
                return
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                time.sleep(0.15)
                for i in range(100):
                    line = (_j.dumps({"message": {"content": f"слово{i} "}}) + "\n").encode()
                    self.wfile.write(f"{len(line):x}\r\n".encode() + line + b"\r\n")
                    self.wfile.flush()
                    time.sleep(0.05 if i < 3 else 2)    # дальше модель «задумалась»
                self.wfile.write(b"0\r\n\r\n")
            except OSError:
                pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    llm = LLM({"ollama_url": f"http://127.0.0.1:{srv.server_port}", "model": "m"})
    threading.Timer(0.4, llm.stop).start()
    t0, got = time.time(), None
    try:
        llm.chat([{"role": "user", "content": "x"}])
    except Cancelled as c:
        got = c.partial
    check("СТОП прерывает генерацию быстро", got is not None and time.time() - t0 < 2, f"{time.time() - t0:.1f}s")
    check("частичный ответ сохраняется", got and got.startswith("слово0"))
    llm.begin()
    threading.Timer(0.2, llm.stop).start()
    try:
        llm.chat([{"role": "user", "content": "x"}])
        ok = False
    except Cancelled:
        ok = True
    check("после begin() новый запрос снова можно остановить", ok)
    llm.begin()
    threading.Timer(0.3, llm.stop).start()
    t0 = time.time()
    try:
        llm.chat_tools([{"role": "user", "content": "x"}], [])
        ok = False
    except Cancelled:
        ok = time.time() - t0 < 1.5
    check("СТОП прерывает и ожидание ответа с инструментами", ok)
    srv.shutdown()



def test_local_confirm():
    import brain as B
    from commands import Store
    cfg = config.load()
    ui, tts, llm = UI(), TTS(), ScriptLLM()
    b = B.Brain(cfg, llm, tts, Store(), ui)
    llm.script = [("", [("pc_action", {"action": "shutdown", "param": "0"})]), ("На экране.", [])]
    b.type("выключи компьютер через полчаса, а сначала закрой всё")
    check("опасное действие от модели — через карточку", wait(lambda: len(ui.cards) == 1))
    op = list(ui.cards)[0]
    b.hear("храз нет")
    check("«нет» отклоняет", wait(lambda: ui.resolved.get(op) == "ОТКЛОНЕНО"))


if __name__ == "__main__":
    for f in (test_persona, test_confirmations, test_stop, test_local_confirm):
        print(f"\n— {f.__name__}")
        f()
    for p in ("commands.json", "archive.json"):
        try:
            os.remove(os.path.join(ROOT, p))
        except OSError:
            pass
    print(f"\nВсе проверки пройдены: {len(PASSED)}")
