"""Тесты автономного ассистента: выбор моделей и выгрузка, инструменты (схемы, проверка, журнал, белые списки,
подтверждения), память на эмбеддингах, чаты, «продолжи», проверка при запуске, понятные ошибки.
Ollama — поддельный сервер tests/fake_ollama.py. Запуск:  python tests/test_assistant.py"""
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.chdir(ROOT)

import chats  # noqa: E402
import config  # noqa: E402
import memory  # noqa: E402
import tools  # noqa: E402

SANDBOX = tempfile.mkdtemp(prefix="khraz_asst_")
chats.DIR = os.path.join(SANDBOX, "chats")
memory.PATH = os.path.join(SANDBOX, "memory.json")
memory.OLD_ARCHIVE = os.path.join(SANDBOX, "нет.json")
tools.LOG_PATH = os.path.join(SANDBOX, "tools.jsonl")

from fake_ollama import FakeOllama  # noqa: E402

PASSED = []


def check(name, cond, info=""):
    if not cond:
        raise AssertionError(f"✗ {name} {info}")
    PASSED.append(name)
    print("✓", name)


def wait(cond, sec=10):
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def make_cfg(url=None):
    cfg = config.load()
    cfg.update(ollama_url=url or "http://127.0.0.1:9", model="qwen3.5:9b", model_smart="gpt-oss:20b",
               model_code="qwen3.6:27b-coding", embed_model="bge-m3", vision_model="qwen3.5:9b", model_mode="auto",
               search_roots=[os.path.join(SANDBOX, "docs")], forbidden_paths=[os.path.join(SANDBOX, "docs", "research")],
               notes_dir=os.path.join(SANDBOX, "notes"), outputs_dir=os.path.join(SANDBOX, "out"),
               voice_confirm_local=True, text_detail="short")
    return cfg


class UI:
    def __init__(self):
        self.log, self.cards, self.resolved, self.models, self.actions, self.more = [], {}, {}, [], [], 0
        self.tools, self.files = [], []
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
    def model_info(self, m, r): self.models.append((m, r))
    def action(self, t): t and self.actions.append(t)
    def offer_more(self): self.more += 1
    def tool_start(self, cid, name, args): self.tools.append(("start", cid, name, args))
    def tool_end(self, cid, ok, res): self.tools.append(("end", cid, ok, res))
    def file_ready(self, p): self.files.append(p)


class TTS:
    def __init__(self): self.said = []
    def say(self, t): self.said.append(t)
    def stop(self): pass
    def mute(self, on): pass
    def busy(self): return False


class Ctx:
    """Минимальный контекст для прямых вызовов инструментов."""
    def __init__(self, cfg):
        self.cfg, self.picked_files, self.turn_text, self.notes, self.acts = cfg, set(), "", [], []
        self.memory = memory.Memory(None, path=os.path.join(SANDBOX, "ctx_memory.json"))
        self.files, self.cards = [], []
    def notify(self, t): self.notes.append(t)
    def ui_action(self, t): self.acts.append(t)
    def file_ready(self, p): self.files.append(p)
    def tool_card(self, phase, *a):
        self.cards.append((phase,) + a)
        return "c1" if phase == "start" else None


def bot_texts(ui):
    return [t for r, t in ui.log if r == "bot"]


# ------------------------------------------------------------------ тесты
def test_router():
    import router
    cfg = make_cfg()
    c = router.choose("как дела", cfg)
    check("по умолчанию — основная модель", c.model == "qwen3.5:9b" and c.reason)
    c = router.choose("составь план подготовки к егэ по физике на месяц", cfg)
    check("план → gpt-oss:20b с причиной", c.model == "gpt-oss:20b" and "план" in c.reason, c.reason)
    c = router.choose("сначала проанализируй бюджет, потом предложи сокращения", cfg)
    check("многоэтапный вопрос → умная модель", c.role == "smart")
    c = router.choose("напиши функцию на python для сортировки", cfg)
    check("код без явной команды — НЕ кодовая модель, но подсказка", c.role == "fast" and "режим кода" in c.reason)
    c = router.choose("режим кода: напиши функцию сортировки", cfg)
    check("явная команда → qwen3.6:27b-coding", c.model == "qwen3.6:27b-coding")
    check("ручной режим важнее эвристик", router.choose("как дела", cfg, "smart").model == "gpt-oss:20b")
    check("голосом «включи режим кода»", router.mode_command("включи режим кода") == "code")
    check("«обычный режим» возвращает авто", router.mode_command("обычный режим") == "auto")
    check("инструментами кодовая модель не управляет", router.for_actions("открой блокнот", cfg, "code").role == "fast")


def test_model_manager():
    from llm import LLM, ModelMissing
    fo = FakeOllama(installed=("qwen3.5:9b", "gpt-oss:20b", "bge-m3:latest"))
    cfg = make_cfg(fo.url)
    llm = LLM(cfg)
    events = []
    llm.on_model = lambda m, st: events.append((m, st))
    out = llm.chat([{"role": "user", "content": "привет"}], model="qwen3.5:9b")
    check("ответ основной модели получен", out.startswith("Ответ"))
    thought = []
    out = llm.chat([{"role": "user", "content": "план"}], model="gpt-oss:20b", on_thinking=lambda: thought.append(1))
    check("переход на крупную модель выгружает предыдущую", "qwen3.5:9b" in fo.unloaded and fo.loaded == ["gpt-oss:20b"],
          f"{fo.unloaded} {fo.loaded}")
    check("рассуждение gpt-oss не попадает в ответ, только статус", "скрытое" not in out and thought)
    body = fo.chats[-1][1]
    check("gpt-oss: think=low, свой keep_alive", body.get("think") == "low" and body["keep_alive"] == cfg["keep_alive_large"])
    body0 = fo.chats[0][1]
    check("основная: рассуждения выключены, keep_alive длиннее", body0.get("think") is False and body0["keep_alive"] == cfg["keep_alive"])
    check("одинаковый num_ctx — Ollama не перезагружает модель", body0["options"]["num_ctx"] == body["options"]["num_ctx"])
    llm.embed(["тест"])
    check("эмбеддинги bge-m3 не выгружают крупную модель", fo.loaded == ["gpt-oss:20b"])
    try:
        llm.chat([{"role": "user", "content": "x"}], model="qwen3.6:27b-coding")
        ok = False
    except ModelMissing as e:
        ok = e.model == "qwen3.6:27b-coding"
    check("нет модели → ModelMissing с именем", ok)
    check("интерфейс узнаёт о загрузке модели", ("gpt-oss:20b", "loading") in events)
    fo.close()


def test_tools():
    cfg = make_cfg()
    docs = os.path.join(SANDBOX, "docs")
    os.makedirs(os.path.join(docs, "research"), exist_ok=True)
    os.makedirs(os.path.join(docs, "отчёты"), exist_ok=True)
    with open(os.path.join(docs, "отчёты", "Отчёт за октябрь.txt"), "w", encoding="utf-8") as f:
        f.write("Выручка выросла на 12%.")
    with open(os.path.join(docs, "research", "отчёт секретный.txt"), "w", encoding="utf-8") as f:
        f.write("не трогать")
    ctx = Ctx(cfg)
    names = {s["function"]["name"] for s in tools.schemas(cfg, "открой блокнот")}
    check("у модели нет shell/PowerShell", not names & {"shell", "powershell"} and "run_command" in names)
    check("интернет-поиск скрыт без явной просьбы", "web_search" not in names)
    check("…и доступен при явной просьбе", "web_search" in {s["function"]["name"] for s in tools.schemas(cfg, "найди в интернете курс")})

    def err(fn):
        try:
            fn()
            return None
        except tools.ToolError as e:
            return str(e)
    check("лишний параметр отклонён", "лишний" in (err(lambda: tools.call("set_timer", {"seconds": 5, "x": 1}, ctx)) or ""))
    check("диапазон проверяется", "больше" in (err(lambda: tools.call("set_timer", {"seconds": 999999}, ctx)) or ""))
    check("число строкой приводится", tools.call("set_timer", {"seconds": "60"}, ctx).startswith("Таймер"))
    check("программа не из белого списка — отказ",
          "нет в списке" in (err(lambda: tools.call("open_app", {"name": "regedit"}, ctx)) or ""))
    check("произвольная команда невозможна",
          "нет в списке" in (err(lambda: tools.call("run_command", {"name": "del /q c:\\"}, ctx)) or ""))
    check("инъекция в параметр ping отклонена",
          "адрес" in (err(lambda: tools.call("run_command", {"name": "ping", "arg": "ya.ru & del x"}, ctx)) or ""))
    check("белый список: доклад о системе работает", "процессор" in tools.call("run_command", {"name": "system_report"}, ctx))
    check("веб-поиск моделью без явной просьбы запрещён",
          "явной" in (err(lambda: tools.call("web_search", {"query": "x"}, ctx)) or ""))
    for name, args in (("run_command", {"name": "flush_dns"}), ("pc_action", {"action": "shutdown", "param": "0"}),
                       ("close_app", {"name": "блокнот"}), ("memory_save", {"text": "люблю чай"})):
        try:
            tools.call(name, args, ctx)
            ok = False
        except tools.NeedsConfirm as nc:
            ok = bool(nc.summary)
        check(f"изменение без подтверждения не выполняется: {name}", ok)
    res = tools.call("find_file", {"query": "отчёт"}, ctx)
    paths = [f["path"] for f in res["found"]]
    check("поиск файла в разрешённой папке", any("октябрь" in p for p in paths))
    check("запрещённая папка (как ~/research) не ищется", not any("research" in p for p in paths))
    doc = tools.call("read_document", {"path": paths[0]}, ctx)
    check("чтение документа", "Выручка" in doc["text"])
    check("чтение из запрещённой папки — отказ", "закрыта" in (err(lambda: tools.call(
        "read_document", {"path": os.path.join(docs, "research", "отчёт секретный.txt")}, ctx)) or ""))
    check("чтение вне разрешённых папок — отказ", "вне разрешённых" in (err(lambda: tools.call(
        "read_document", {"path": os.path.join(ROOT, "config.py")}, ctx)) or ""))
    a = tools.call("create_note", {"title": "Список", "text": "молоко"}, ctx)
    b = tools.call("create_note", {"title": "Список", "text": "хлеб"}, ctx)
    check("заметка не перезаписывает существующую", a != b and len(os.listdir(cfg["notes_dir"])) == 2)
    log = tools.read_log()
    check("каждый вызов в журнале (ok/invalid/needs_confirm)", {"ok", "invalid", "needs_confirm"} <= {r["status"] for r in log})
    check("в журнале — проверенные аргументы", any(r["tool"] == "set_timer" and r["args"].get("seconds") == "60" for r in log)
          or any(r["tool"] == "set_timer" and r["status"] == "ok" for r in log))


def test_memory():
    fo = FakeOllama()
    from llm import LLM
    llm = LLM(make_cfg(fo.url))
    m = memory.Memory(llm, path=os.path.join(SANDBOX, "mem1.json"))
    m.add("Ученики занимаются по вторникам и четвергам")
    m.add("Любимый язык программирования — PHP, фреймворк Laravel")
    m.add("Отвечай коротко, без вступлений", kind="preference")
    check("эмбеддинги bge-m3 используются", m.embed_ok is True and all(x.get("vec") for x in m.items))
    hits = [x["text"] for x, _ in m.search("в какие дни занимаются ученики")]
    check("поиск по смыслу находит нужное первым", hits and "вторникам" in hits[0], hits)
    rel = [x["text"] for x in m.relevant("фреймворк laravel")]
    check("в разговор — подходящие факты и все предпочтения", any("Laravel" in t for t in rel) and any("коротко" in t for t in rel))
    check("нерелевантное не подмешивается", not any("вторникам" in t for t in rel))
    check("дубликат не создаётся", len(m.items) == 3 and m.add("ученики занимаются по вторникам и четвергам") and len(m.items) == 3)
    i = m.find_one("про вторники")
    check("«забудь про…» находит запись", i and "вторникам" in i["text"])
    check("удаление отдельной записи", m.delete(i["id"]) and len(m.items) == 2)
    m2 = memory.Memory(None, path=os.path.join(SANDBOX, "mem1.json"))
    check("без bge-m3 — поиск по словам", [x["text"] for x, _ in m2.search("laravel фреймворк")] and m2.embed_ok is False)
    m.clear()
    check("полная очистка памяти", not m.items and not memory.Memory(None, path=os.path.join(SANDBOX, "mem1.json")).items)
    # перенос старого archive.json
    old_path, old_arch = memory.PATH, memory.OLD_ARCHIVE
    memory.PATH = os.path.join(SANDBOX, "mig.json")
    memory.OLD_ARCHIVE = os.path.join(SANDBOX, "archive.json")
    with open(memory.OLD_ARCHIVE, "w", encoding="utf-8") as f:
        json.dump(["Кот Барсик"], f, ensure_ascii=False)
    check("старый архив переносится в память", [x["text"] for x in memory.Memory(None).items] == ["Кот Барсик"])
    memory.PATH, memory.OLD_ARCHIVE = old_path, old_arch
    fo.close()


def test_chats():
    c = chats.Chats(folder=os.path.join(SANDBOX, "chats_t"))
    c.add("user", "Как решить квадратное уравнение?")
    c.add("assistant", "Через дискриминант.")
    check("заголовок чата из первой реплики", c.current["title"].startswith("Как решить"))
    first = c.current["id"]
    c.new()
    check("пустой чат не дублируется", c.new()["id"] == c.current["id"] and len(c.list()) == 2)
    c.add("user", "Второй")
    c.open(first)
    check("переключение возвращает историю", c.history()[1]["content"] == "Через дискриминант.")
    c.delete(first)
    check("удаление чата", all(x["id"] != first for x in c.list()))
    c.delete_all()
    check("очистка всех чатов", len(c.list()) == 1 and not c.messages)


def test_brain_flows():
    import brain as B
    from commands import Store
    fo = FakeOllama()
    cfg = make_cfg(fo.url)
    ui, tts = UI(), TTS()
    from llm import LLM
    b = B.Brain(cfg, LLM(cfg), tts, Store(), ui)
    b.chats.delete_all()
    b.memory.clear()

    b.type("запомни, что ученики занимаются по вторникам")
    check("«запомни» — сохраняется сразу (явная просьба)", wait(lambda: len(b.memory.items) == 1))
    n0 = len(ui.cards)
    b.type("я предпочитаю короткие ответы без вступлений")
    check("предпочтение без «запомни» — только предложение", wait(lambda: len(ui.cards) > n0) and len(b.memory.items) == 1)
    b.hear("храз да")
    check("после «да» предпочтение сохранено", wait(lambda: any(m.get("kind") == "preference" for m in b.memory.items)))
    n1 = len(ui.cards)
    b.type("забудь про вторники")
    check("«забудь» спрашивает подтверждение", wait(lambda: len(ui.cards) > n1) and len(b.memory.items) == 2)
    b.hear("храз да")
    check("после «да» запись удалена", wait(lambda: len(b.memory.items) == 1))

    fo.reply = "Квадратное уравнение решается через дискриминант. Это быстро."
    b.type("как решить квадратное уравнение")
    check("ответ основной моделью, причина показана", wait(lambda: any(m == "qwen3.5:9b" for m, _ in ui.models)))
    check("ответ сохранён в чате с моделью", wait(lambda: any(m.get("meta", {}).get("model") == "qwen3.5:9b"
                                                             for m in b.chats.messages)))
    sys_prompt = fo.chats[-1][1]["messages"][0]["content"]
    check("предпочтение подмешано в разговор", "без вступлений" in sys_prompt)
    check("лимит краткого ответа", fo.chats[-1][1]["options"]["num_predict"] == cfg["max_tokens_short"])
    n = len(fo.chats)
    b.type("подробнее")
    check("«подробнее» продолжает ответ развёрнуто", wait(lambda: len(fo.chats) > n)
          and fo.chats[-1][1]["options"]["num_predict"] == cfg["max_tokens_long"]
          and "Продолжи" in fo.chats[-1][1]["messages"][-1]["content"])

    b.type("составь план подготовки к экзамену")
    check("сложное → gpt-oss:20b", wait(lambda: any(m == "gpt-oss:20b" for m, _ in ui.models)))
    check("основная выгружена перед крупной", wait(lambda: "qwen3.5:9b" in fo.unloaded))

    b.type("включи режим кода")
    check("режим кода голосом", wait(lambda: b.mode == "code"))
    b.type("обычный режим")
    check("возврат в авто", wait(lambda: b.mode == "auto"))

    fo.tool_calls = [[("create_note", {"title": "Покупки", "text": "молоко, хлеб"})], []]
    fo.reply = "Заметка создана."
    b.type("создай заметку покупки: молоко и хлеб")
    check("модель вызвала инструмент — заметка создана", wait(lambda: os.path.isdir(cfg["notes_dir"]) and os.listdir(cfg["notes_dir"])))
    check("действие показано в строке состояния", wait(lambda: any("Заметка" in a for a in ui.actions)))
    fo.tool_calls = [[("run_command", {"name": "flush_dns"})], []]
    n2 = len(ui.cards)
    b.type("сбрось кэш днс")
    check("изменение системы — карточка подтверждения", wait(lambda: len(ui.cards) > n2))
    op = list(ui.cards)[-1]
    b.approve(op, via="ui")
    check("после подтверждения инструмент вызван (в Linux — понятный отказ)",
          wait(lambda: op in ui.resolved and ui.resolved[op] in ("ВЫПОЛНЕНО", "НЕ ВЫПОЛНЕНО")))

    n3 = len(ui.cards)
    b.type("очисти всё")
    check("полная очистка — с подтверждением", wait(lambda: len(ui.cards) > n3))
    b.hear("храз да")
    check("чаты и память очищены", wait(lambda: not b.memory.items and not b.chats.messages))

    fo.installed = ["gpt-oss:20b"]                      # основной модели нет
    b.type("привет")
    check("нет модели → точная команда ollama pull", wait(lambda: any("ollama pull qwen3.5:9b" in t for t in bot_texts(ui))))
    fo.close()
    b.type("привет")
    check("Ollama не отвечает → понятный текст без traceback",
          wait(lambda: any("Ollama не отвечает" in t for t in bot_texts(ui))) and
          not any("Traceback" in t for t in bot_texts(ui)))


def test_files_out():
    cfg = make_cfg()
    ctx = Ctx(cfg)
    r = tools.call("create_file", {"name": "Отчёт", "format": "xlsx",
                                   "content": '[["Ученик","Долг"],["Иван","2000"],["Анна","0"]]'}, ctx)
    check("xlsx создан и отдан карточкой", os.path.exists(r["file"]) and ctx.files == [r["file"]] and r["rows"] == 2)
    from openpyxl import load_workbook
    ws = load_workbook(r["file"]).active
    check("в xlsx заголовки и числа", ws["A1"].value == "Ученик" and ws["B2"].value == 2000)
    r2 = tools.call("create_file", {"name": "Отчёт", "format": "xlsx", "content": "a;b\n1;2"}, ctx)
    check("файл с тем же именем не перезаписывается", r2["file"] != r["file"] and r2["file"].endswith("(2).xlsx"))
    r3 = tools.call("create_file", {"name": "План", "format": "docx", "content": "# План\n- пункт один\nТекст"}, ctx)
    import docx
    d = docx.Document(r3["file"])
    check("docx из markdown", d.paragraphs[0].text == "План" and any("пункт" in p.text for p in d.paragraphs))
    r4 = tools.call("create_file", {"name": "../../evil", "format": "txt", "content": "x"}, ctx)
    check("имя файла не выводит из папки", os.path.dirname(r4["file"]) == os.path.join(SANDBOX, "out"))
    check("карточка инструмента: старт и конец", [c[0] for c in ctx.cards[:2]] == ["start", "end"])
    cfg2 = make_cfg()
    cfg2["outputs_dir"] = os.path.join(SANDBOX, "docs", "research", "out")
    try:
        tools.call("create_file", {"name": "x", "format": "txt", "content": "x"}, Ctx(cfg2))
        ok = False
    except tools.ToolError:
        ok = True
    check("в запрещённую папку файлы не пишутся", ok)



def test_mcp_hub():
    import sys as _sys
    import khraz_secrets
    import mcp_hub
    store = {}
    real_get, real_set = khraz_secrets.get, khraz_secrets.set
    khraz_secrets.get = lambda k: store.get(k, "")
    khraz_secrets.set = lambda k, v: store.__setitem__(k, v)
    env, headers = mcp_hub.parse_secrets("DEMO_TOKEN=s3cret\nAuthorization: Bearer x\n# комментарий")
    check("секреты: env и заголовки", env == {"DEMO_TOKEN": "s3cret"} and headers == {"Authorization": "Bearer x"})
    servers, secrets = mcp_hub.import_claude_desktop({"mcpServers": {
        "demo": {"command": _sys.executable, "args": [os.path.join(ROOT, "tests", "mock_thirdparty_mcp.py")],
                 "env": {"DEMO_TOKEN": "s3cret"}},
        "remote": {"url": "https://mcp.example.com/mcp", "headers": {"Authorization": "Bearer y"}}}})
    check("импорт конфига Claude Desktop", servers[0]["type"] == "stdio" and servers[1]["type"] == "http"
          and secrets["demo"]["env"]["DEMO_TOKEN"] == "s3cret" and "env" not in servers[0])
    mcp_hub.save_secrets("demo", **secrets["demo"])
    import brain as B
    from commands import Store
    from llm import LLM
    fo = FakeOllama()
    cfg = make_cfg(fo.url)
    cfg["mcp_servers"] = [dict(servers[0], trust="read_auto", keywords="заметки демо")]
    ui = UI()
    b = B.Brain(cfg, LLM(cfg), TTS(), Store(), ui)
    check("сервер подключился, инструменты в общем реестре",
          wait(lambda: "mcp_demo_list_notes" in tools.REGISTRY, 30), b.hub.status())
    names = {s["function"]["name"] for s in tools.schemas(cfg, "что в заметках демо")}
    check("модели видны mcp_demo_*", {"mcp_demo_list_notes", "mcp_demo_add_note", "mcp_demo_wipe_notes"} <= names)
    r = tools.call("mcp_demo_list_notes", {}, b)
    check("чтение (readOnlyHint) — сразу; секрет дошёл через env", r.get("token_seen") is True and "1" in r["notes"])
    for name, args, risk in (("mcp_demo_add_note", {"text": "x"}, "change"), ("mcp_demo_wipe_notes", {}, "delete")):
        try:
            tools.call(name, args, b)
            ok = False
        except tools.NeedsConfirm:
            ok = tools.REGISTRY[name].risk_for(args) == risk
        check(f"{name}: без подтверждения не выполняется ({risk})", ok)
    check("после подтверждения — выполняется",
          tools.call("mcp_demo_add_note", {"text": "хлеб"}, b, confirmed=True)["count"] == 2)
    fo.tool_calls = [[("mcp_demo_list_notes", {})], []]
    fo.reply = "В заметках: купить молоко, хлеб."
    b.type("что в заметках демо")
    check("реплика с ключевыми словами → модель вызывает сторонний инструмент",
          wait(lambda: any(t[0] == "start" and t[2] == "mcp_demo_list_notes" for t in ui.tools)))
    b.hub.stop()
    check("остановка хаба убирает сторонние MCP-инструменты", not any(n.startswith("mcp_demo_") for n in tools.REGISTRY))
    b.cfg["mcp_servers"] = []
    fo.close()
    khraz_secrets.get, khraz_secrets.set = real_get, real_set


def test_experience():
    """Оценки 👍/👎, база знаний, привычки."""
    import feedback
    import habits
    import kb as kbmod
    from llm import LLM
    fo = FakeOllama()
    llm = LLM(make_cfg(fo.url))
    fb = feedback.Feedback(llm, path=os.path.join(SANDBOX, "fb.json"))
    check("👍 сохраняется", fb.rate("m1", "как продлить клиента впн на месяц", "Скажите: продли ivan на 30 дней.", 1) == 1)
    fb.rate("m2", "как продлить клиента впн на месяц и сразу дать qr", "Длинная лекция о VPN…", -1)
    good, bad = fb.similar("как продлить клиента впн на неделю")
    check("похожий вопрос находит удачный образец", good and good[0]["msg_id"] == "m1")
    block = fb.prompt_block("как продлить клиента впн на неделю")
    check("образец попадает в подсказку", "УДАЧНЫЙ" in block and "продли ivan" in block)
    check("повторное 👍 снимает оценку", fb.rate("m1", "x", "y", 1) == 0 and fb.stats() == (0, 1))

    docs = os.path.join(SANDBOX, "kbdocs")
    os.makedirs(os.path.join(docs, "research"), exist_ok=True)
    with open(os.path.join(docs, "физика конспект.md"), "w", encoding="utf-8") as f:
        f.write("Закон Ома: сила тока на участке цепи прямо пропорциональна напряжению и обратно "
                "пропорциональна сопротивлению. I = U / R. " * 3)
    with open(os.path.join(docs, "договор.txt"), "w", encoding="utf-8") as f:
        f.write("Договор оказания услуг: оплата занятий до пятого числа каждого месяца, отмена за сутки. " * 3)
    with open(os.path.join(docs, "research", "секрет.txt"), "w", encoding="utf-8") as f:
        f.write("закрыто закрыто закрыто")
    cfg = make_cfg(fo.url)
    cfg.update(kb_folders=[docs], forbidden_paths=[os.path.join(docs, "research")])
    kb = kbmod.KB(llm, cfg, path=os.path.join(SANDBOX, "kb.json"))
    files, chunks, errs = kb.reindex()
    check("индексация папок, запрещённое пропущено", files == 2 and chunks >= 2 and errs == 0
          and not any("секрет" in x["file"] for x in kb.items))
    hits = kb.search("закон ома сопротивление напряжение")
    check("поиск по смыслу находит конспект", hits and "физика" in hits[0]["file"])
    block, hs = kb.prompt_block("закон ома сопротивление", min_score=0.3)
    check("в подсказке — фрагмент и источник", "физика конспект.md" in block and hs)
    n_embed = len([1 for c in fo.chats])                    # (эмбеддинги не идут через chat — проверяем по индексу)
    before = len(kb.items)
    kb.reindex()
    check("повторная индексация не дублирует неизменённое", len(kb.items) == before)
    kb2 = kbmod.KB(llm, cfg, path=os.path.join(SANDBOX, "kb.json"))
    check("индекс сохраняется на диск", kb2.stats() == kb.stats())

    h = habits.Habits(path=os.path.join(SANDBOX, "habits.json"))
    r = [h.record("run_command", {"name": "ip"}, "какой у меня ip") for _ in range(3)]
    check("третий повтор → предложение", r[0] is None and r[1] is None and r[2] and r[2]["count"] == 3)
    check("второй раз не предлагает", h.record("run_command", {"name": "ip"}, "какой у меня ip") is None)
    check("разовые инструменты не считаются", h.record("create_note", {"text": "x"}, "x") is None)
    fo.close()




def test_proactive():
    import datetime
    import persona
    import watcher as W
    import brain as B
    from commands import Store
    from llm import LLM
    fo = FakeOllama()
    cfg = make_cfg(fo.url)
    cfg.update(proactive=False, quiet_hours="", morning_time="08:30")
    ui, tts = UI(), TTS()
    b = B.Brain(cfg, LLM(cfg), tts, Store(), ui)
    b.watcher = W.Watcher(b, path=os.path.join(SANDBOX, "watch.json"))
    b.cfg["proactive"] = True
    noon = datetime.datetime(2026, 11, 1, 12, 0)
    check("нечего сообщать → ХРАЗ молчит", b.watcher.tick(now=noon) == [])
    b.cfg["quiet_hours"] = "00:00-23:59"
    check("тихие часы определяются", W.in_quiet(b.cfg))
    b.cfg["quiet_hours"] = ""
    # утренний доклад
    fo.reply = "x"
    sent = b.watcher.check_morning(datetime.datetime(2026, 11, 2, 8, 31))
    check("утренний доклад в назначенное время", sent == ["morning"])
    check("доклад: приветствие", wait(lambda: any("майор" in t for r, t in ui.log if r == "bot")))
    check("второй раз за день — нет", b.watcher.check_morning(datetime.datetime(2026, 11, 2, 9, 0)) == [])
    check("запустили днём — доклад не навязывает", b.watcher.check_morning(datetime.datetime(2026, 11, 3, 14, 0)) == [])
    # настроение
    check("настроение: ночь и серия сбоев", "ночь" in persona.mood(datetime.datetime(2026, 1, 1, 3)).lower()
          and "сбоев" in persona.mood(errors=3))
    check("экран: разбор ответа модели", W.parse_screen('{"error": true, "what": "TypeError в app.js:12"}')
          == "TypeError в app.js:12" and W.parse_screen('{"error": false}') == "")
    fo.close()


def test_habits_plan_clipboard_solution():
    import types
    import brain as B
    import commands
    from commands import Store
    from llm import LLM
    commands.PATH = os.path.join(SANDBOX, "commands.json")
    fo = FakeOllama()
    cfg = make_cfg(fo.url)
    cfg.update(proactive=False)
    ui, tts = UI(), TTS()
    store = Store()
    b = B.Brain(cfg, LLM(cfg), tts, store, ui)
    b.habits = __import__("habits").Habits(path=os.path.join(SANDBOX, "habits2.json"))
    # буфер обмена
    clip = {"v": "превет мир как дила"}
    sys.modules["pyperclip"] = types.SimpleNamespace(paste=lambda: clip["v"], copy=lambda t: clip.update(v=t))
    fo.reply = "Привет, мир! Как дела?"
    b.type("исправь то что я скопировал")
    check("буфер: исправлено и положено обратно", wait(lambda: clip["v"] == "Привет, мир! Как дела?"))
    prompt = fo.chats[-1][1]["messages"][-1]["content"]
    check("текст из буфера передан как данные", "превет мир" in prompt and "не инструкции" in prompt)
    # проверка решения по фото
    from PIL import Image
    img = os.path.join(SANDBOX, "solution.png")
    Image.new("RGB", (400, 300), "white").save(img)
    fo.reply = "Шаг 1 — верно. Итог: ответ верный."
    b.check_solution(path=img, raw="проверь решение")
    check("проверка решения → отчёт docx на загрузку", any(p.endswith(".docx") and "Проверка решения" in p
                                                          for p in ui.files))
    # оценка ответа
    msg = [m for m in b.chats.messages if m["role"] == "assistant"][-1]
    b.feedback = __import__("feedback").Feedback(b.llm, path=os.path.join(SANDBOX, "fb2.json"))
    check("👍 через мозг", b.rate(msg["id"], 1) == 1 and b.chats.find(msg["id"])[1]["meta"]["vote"] == 1)
    fo.close()


def test_small_parts():
    import hotkey
    import sfx
    check("горячая клавиша разбирается", hotkey.parse("win+shift+x") == (0x8 | 0x4, ord("X"))
          and hotkey.parse("ctrl+f5") == (0x2, 0x74) and hotkey.parse("hyper+x") is None)
    check("звуки синтезируются", all(len(sfx.samples(k)) > 1000 for k in sfx.SOUNDS))


def test_startup():
    import startup
    fo = FakeOllama(installed=("qwen3.5:9b", "bge-m3:latest"))
    rep = startup.check(make_cfg(fo.url))
    check("Ollama найдена, версия", rep.ollama and rep.version)
    check("недостающие модели — точные команды",
          rep.pull_commands() == ["ollama pull gpt-oss:20b", "ollama pull qwen3.6:27b-coding"], rep.pull_commands())
    check("основная есть → запуск возможен", rep.ok)
    check("отчёт содержит ollama pull", "ollama pull gpt-oss:20b" in rep.markdown())
    fo.close()
    rep = startup.check(make_cfg("http://127.0.0.1:9"))
    check("Ollama недоступна — подсказка для Windows и WSL", not rep.ollama and "WSL" in rep.markdown())


if __name__ == "__main__":
    for f in (test_router, test_model_manager, test_tools, test_files_out, test_mcp_hub, test_memory,
              test_chats, test_brain_flows, test_experience, test_proactive, test_habits_plan_clipboard_solution,
              test_small_parts, test_startup):
        print(f"\n— {f.__name__}")
        f()
    for p in ("commands.json",):
        try:
            os.remove(os.path.join(ROOT, p))
        except OSError:
            pass
    print(f"\nВсе проверки пройдены: {len(PASSED)}")
