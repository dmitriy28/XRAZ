"""Тесты дополнений 03.11.2026: запасной Ollama, запуск игр, PowerShell, группы инструментов, правила по расписанию,
чтение логов, роутер, проверка после записи и откат, статистика, Wake-on-LAN.  python tests/test_extras.py"""
import datetime
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_assistant as T  # noqa: E402  (песочница: чаты, память, журнал инструментов — во временной папке)

check, wait, make_cfg, UI, TTS, Ctx = T.check, T.wait, T.make_cfg, T.UI, T.TTS, T.Ctx
FakeOllama, SANDBOX = T.FakeOllama, T.SANDBOX

import scheduler  # noqa: E402
import tools  # noqa: E402

scheduler.PATH = os.path.join(SANDBOX, "rules.json")


def test_fallback_and_games():
    import actions
    import llm as L
    fo = FakeOllama()
    cfg = make_cfg("http://127.0.0.1:9")
    cfg.update(ollama_url_fallback=fo.url, model_fallback="qwen3:4b")
    ll, seen = L.LLM(cfg), []
    ll.on_model = lambda m, s: seen.append((m, s))
    check("основной недоступен → запасной адрес", ll.url == fo.url and ll.on_fallback)
    check("любая роль → лёгкая модель", ll._body([{"role": "user", "content": "x"}], model="gpt-oss:20b")["model"] == "qwen3:4b")
    check("изображения не подменяются", ll._body([{"role": "user", "content": "x", "images": ["a"]}],
                                                  model="qwen3.5:9b")["model"] == "qwen3.5:9b")
    check("эмбеддинги не подменяются", ll._body([], model="bge-m3")["model"] == "bge-m3")
    check("интерфейс узнаёт о запасном режиме", ("qwen3:4b", "fallback") in seen)
    cfg2 = make_cfg(fo.url)
    cfg2.update(ollama_url_fallback="http://127.0.0.1:9")
    ll2 = L.LLM(cfg2)
    check("основной жив → работаем на нём", ll2.url == fo.url and not ll2.on_fallback)
    fo.close()
    started = []
    real = getattr(os, "startfile", None)
    actions.IS_WIN, os.startfile = True, (lambda p: started.append(p))
    try:
        for p in ("steam://rungameid/668580", "shell:AppsFolder\\Microsoft.4297127D64EC6_8wekyb3d8bbwe!Minecraft"):
            actions.open_app(p, None)
        actions.open_app("steam://rungameid/1 & calc", None)
    finally:
        actions.IS_WIN = sys.platform == "win32"
        if real is None:
            del os.startfile
    check("игры по ссылкам Steam/Store запускаются", len(started) == 2 and "668580" in started[0])
    check("ссылка со спецсимволами не запускается", all("calc" not in s for s in started))


def test_powershell_gate():
    cfg = make_cfg()
    names = lambda text: [t.name for t in tools.available(cfg, text)]    # noqa: E731
    check("PowerShell выключен по умолчанию", "run_powershell" not in names("выполни команду powershell dir"))
    cfg["allow_shell"] = True
    check("включён, но только по явной фразе", "run_powershell" in names("выполни команду powershell dir")
          and "run_powershell" not in names("открой блокнот"))
    ctx = Ctx(cfg)
    ctx.turn_text = "выполни команду powershell dir"
    try:
        tools.call("run_powershell", {"script": "dir"}, ctx)
        ok = False
    except tools.NeedsConfirm as e:
        ok = "dir" in e.summary
    check("выполнение — только после подтверждения (карточка с текстом)", ok)


def test_groups():
    cfg = make_cfg()
    cfg.update(tool_groups=True,
               log_sources=[{"name": "app", "type": "file", "path": "x"}], wol_mac="AA:BB:CC:DD:EE:FF")
    n = lambda text: {t["function"]["name"] for t in tools.schemas(cfg, text)}   # noqa: E731
    all_n = len(tools.available(cfg, ""))
    check("обычная фраза — только ядро", n("открой калькулятор") >= {"open_app", "pc_action"}
          and "read_log" not in n("открой калькулятор"))
    check("группы уменьшают набор", len(n("открой калькулятор")) < all_n // 2)
    check("про лог — read_log", "read_log" in n("что в логе приложения"))
    check("про правила — rule_*", {"rule_add", "rule_list"} <= n("каждый день в 9 утра проверяй диск"))
    check("«отмени» — undo_last, «разбуди» — wake_laptop", "undo_last" in n("отмени последнее") and "wake_laptop" in n("разбуди ноутбук"))
    cfg["tool_groups"] = False
    check("флаг выключен — все инструменты", len(n("открой калькулятор")) == all_n)


def test_scheduler():
    import watcher as W
    check("расписание разбирается", scheduler.parse("daily 20:00") == ("daily", 1200)
          and scheduler.parse("weekly sun 20:00") == ("weekly", 6, 1200) and scheduler.parse("every 120m") == ("every", 120))
    for bad in ("hourly", "every 1m", "daily 25:00", "weekly xxx 10:00"):
        try:
            scheduler.parse(bad)
            ok = False
        except ValueError:
            ok = True
        check(f"плохое расписание отклонено: {bad}", ok)
    p = os.path.join(SANDBOX, "rules_unit.json")
    r = scheduler.add("сводка", "weekly sun 20:00", "tool_stats", {}, None, path=p)
    sun = datetime.datetime(2026, 11, 1, 20, 5)       # воскресенье
    check("не в тот день — не запускается", scheduler.due(datetime.datetime(2026, 11, 2, 20, 5), p) == [])
    check("в срок — запускается один раз", len(scheduler.due(sun, p)) == 1 and scheduler.due(sun, p) == [])
    check("запоздавший больше чем на 3 часа — пропуск", scheduler.due(datetime.datetime(2026, 11, 8, 23, 30), p) == [])
    scheduler.add("пинг", "every 30m", None, {}, "проверь печь", path=p)
    base = datetime.datetime.now()
    check("every: пока рано — нет", all(x["title"] != "пинг" for x in scheduler.due(base, p)))
    check("every: через 31 минуту — да", any(x["title"] == "пинг" for x in scheduler.due(base + datetime.timedelta(minutes=31), p)))
    check("удаление по части названия", scheduler.delete("свод", path=p)["id"] == r["id"])

    # через инструменты и watcher
    import brain as B
    from commands import Store
    from llm import LLM
    fo = FakeOllama()
    cfg = make_cfg(fo.url)
    cfg.update(proactive=True, quiet_hours="")
    ui, tts = UI(), TTS()
    b = B.Brain(cfg, LLM(cfg), tts, Store(), ui)
    b.watcher = W.Watcher(b, path=os.path.join(SANDBOX, "w_rules.json"))
    scheduler.PATH = os.path.join(SANDBOX, "rules_flow.json")
    ctx = Ctx(cfg)
    try:
        tools.call("rule_add", {"title": "x", "schedule": "daily 20:00", "tool": "tool_stats"}, ctx)
        ok = False
    except tools.NeedsConfirm as e:
        ok = "tool_stats" in e.summary
    check("создание правила — с подтверждением", ok)
    res = tools.call("rule_add", {"title": "статистика", "schedule": "daily 09:00", "tool": "tool_stats"}, ctx, confirmed=True)
    check("правило создано", "Правило создано" in res and len(scheduler.load()) == 1)
    try:
        tools.call("rule_add", {"title": "плохо", "schedule": "daily 09:00", "tool": "no_such_tool"}, ctx, confirmed=True)
        ok = False
    except tools.ToolError:
        ok = True
    check("неизвестный инструмент в правиле отклоняется", ok)
    sent = b.watcher.check_rules(datetime.datetime.now().replace(hour=9, minute=10))
    check("чтение выполняется сразу и сообщается", len(sent) == 1, sent)
    check("повторно в тот же день — тишина", b.watcher.check_rules(datetime.datetime.now().replace(hour=9, minute=40)) == [])
    check("rule_list показывает правила", "статистика" in tools.call("rule_list", {}, ctx))
    fo.close()


def test_read_log():
    log = os.path.join(SANDBOX, "laravel.log")
    with open(log, "w", encoding="utf-8") as f:
        for i in range(500):
            f.write(f"[2026-11-03] local.{'ERROR' if i % 100 == 0 else 'INFO'}: line {i} password=SuperSecret123\n")
    cfg = make_cfg()
    cfg["log_sources"] = [{"name": "laravel", "type": "file", "path": log},
                          {"name": "prod", "type": "ssh", "host": "bad host;rm -rf", "path": "/var/log/x"}]
    ctx = Ctx(cfg)
    out = tools.call("read_log", {"source": "laravel", "lines": 5}, ctx)
    check("последние строки лога", out.count("\n") == 4 and "line 499" in out)
    check("секреты в выводе замаскированы", "SuperSecret123" not in out and "***" in out)
    out = tools.call("read_log", {"source": "laravel", "grep": "error", "lines": 10}, ctx)
    check("фильтр по тексту", out.count("ERROR") == 5 and "INFO" not in out)
    try:
        tools.call("read_log", {"source": "/etc/passwd"}, ctx)
        ok = False
    except tools.ToolError:
        ok = True
    check("источник — только из настроек (путь модель не задаёт)", ok)
    try:
        tools.call("read_log", {"source": "prod"}, ctx)
        ok = False
    except tools.ToolError as e:
        ok = "host" in str(e)
    check("ssh: неверный host отклонён до запуска", ok)
    cfg["log_sources"] = []
    check("без источников инструмент не показывается", "read_log" not in [t.name for t in tools.available(cfg, "")])


def test_router_extras():
    import router
    from llm import LLM
    cfg = make_cfg()
    for s in ("разберись почему падает деплой", "что лучше выбрать для сервера", "в чём разница между vless и vmess",
              "составь расписание на неделю"):
        check(f"перефразировка → умная модель: {s}", router.choose(s, cfg).role == "smart")
    check("обычное остаётся быстрым", router.choose("включи свет", cfg).role == "fast")
    fo = FakeOllama()
    cfg = make_cfg(fo.url)
    ll = LLM(cfg)
    long_q = "у меня есть странная ситуация с одним из учеников и я не знаю что мне делать сегодня вечером после работы"
    check("без router_llm — правила как раньше", router.pick(long_q, cfg, "auto", ll).role == "fast")
    cfg["router_llm"] = True
    fo.reply = '{"level": "complex"}'
    check("router_llm: модель сочла сложным → умная", router.pick(long_q, cfg, "auto", ll).role == "smart")
    router._LLM_CACHE.clear()
    fo.reply = '{"level": "simple"}'
    check("router_llm: простое → основная", router.pick(long_q, cfg, "auto", ll).role == "fast")
    check("короткие фразы модель не дёргают", (lambda n0: (router.pick("как дела", cfg, "auto", ll), len(fo.chats) == n0)[1])(len(fo.chats)))
    fo.close()


def test_verify_undo_stats_wol():
    from tools import postcheck
    postcheck.UNDO_PATH = os.path.join(SANDBOX, "undo.json")
    if os.path.exists(postcheck.UNDO_PATH):
        os.remove(postcheck.UNDO_PATH)
    ctx = Ctx(make_cfg())
    try:
        tools.call("undo_last", {}, ctx, confirmed=True)
        ok = False
    except tools.ToolError as e:
        ok = "нечего" in str(e)
    check("журнал отката пуст — понятная ошибка", ok)
    tools.call("tool_stats", {}, ctx)
    st = tools.call("tool_stats", {}, ctx)
    check("статистика инструментов из журнала", "tool_stats" in st, st)
    check("magic packet: 6×FF + 16×MAC", postcheck.magic_packet("AA:BB:CC:DD:EE:FF") == bytes.fromhex("FF" * 6 + "AABBCCDDEEFF" * 16))
    try:
        postcheck.magic_packet("zz")
        ok = False
    except tools.ToolError:
        ok = True
    check("неверный MAC отклонён", ok)


def test_present_and_text():
    import brain as B
    import persona
    from commands import Store
    from llm import LLM
    from PIL import Image
    cfg = make_cfg()
    ctx = Ctx(cfg)
    r = tools.call("show_table", {"title": "Клиенты", "columns": ["Клиент", "Срок", "ГБ"],
                                  "rows": [["ivan", "30.11.2026", 12.0], ["ol|ga", None, 3.5]]}, ctx)
    md = ctx.notes[-1]
    check("таблица показана в чате markdown-ом", "| Клиент | Срок | ГБ |" in md and "|---|---|---|" in md and "| ivan | 30.11.2026 | 12 |" in md
          and "ol¦ga" in md and "показана" in r)
    try:
        tools.call("show_table", {"columns": ["a"], "rows": []}, ctx)
        ok = False
    except tools.ToolError:
        ok = True
    check("пустая таблица — понятная ошибка", ok)
    for kind in ("bar", "line", "pie"):
        before = len(ctx.files)
        tools.call("show_chart", {"title": f"Трафик {kind}", "kind": kind, "unit": "ГБ",
                                  "labels": ["Янв", "Фев", "Мар", "Апр"], "values": [10, 15.5, "12", 8]}, ctx)
        p = ctx.files[-1]
        im = Image.open(p)
        check(f"график {kind}: настоящий PNG, показан в чате", len(ctx.files) == before + 1 and im.size == (1000, 560)
              and len(im.convert("RGB").resize((50, 28)).getcolors(5000)) > 8)
    tools.call("show_chart", {"title": "Много точек", "kind": "bar", "labels": [f"клиент{i}" for i in range(20)],
                              "values": [i - 5 for i in range(20)]}, ctx)
    check("20 столбцов с отрицательными значениями рисуются", os.path.getsize(ctx.files[-1]) > 2000)
    for bad in ({"labels": ["a", "b"], "values": [1]}, {"labels": ["a"], "values": ["много"]}, {"labels": ["a"], "values": [-1], "kind": "pie"}):
        try:
            tools.call("show_chart", bad, ctx)
            ok = False
        except tools.ToolError:
            ok = True
        check(f"плохие данные графика отклоняются: {bad}", ok)
    names = {t["function"]["name"] for t in tools.schemas(dict(cfg, tool_groups=True), "построй график трафика")}
    check("про график — show_chart/show_table в группе", {"show_chart", "show_table"} <= names)
    # полный текст на экране, голос — итог
    full, short = dict(cfg, text_detail="full"), dict(cfg, text_detail="short")
    check("text_detail=full: в подсказке правила вывода", "ПЕРВАЯ фраза — короткий итог" in persona.system_prompt(full, []))
    check("text_detail=short: как 26.10", "ПЕРВАЯ фраза" not in persona.system_prompt(short, []))
    fo = FakeOllama()
    for mode, expect in (("full", cfg.get("max_tokens_long")), ("short", cfg.get("max_tokens_short"))):
        c = make_cfg(fo.url)
        c["text_detail"] = mode
        ui, tts = UI(), TTS()
        b = B.Brain(c, LLM(c), tts, Store(), ui)
        fo.reply = "Ответ модели."
        b.type("как решить квадратное уравнение")
        check(f"{mode}: лимит токенов {expect}", wait(lambda: fo.chats and fo.chats[-1][1]["options"]["num_predict"] == expect, 10))
        check(f"{mode}: правила вывода в запросе", ("ПЕРВАЯ фраза" in fo.chats[-1][1]["messages"][0]["content"]) == (mode == "full"))
    fo.close()


def test_coder():
    import brain as B
    import coder
    import confirmations as CF
    from commands import Store
    from llm import LLM
    coder.STATE_PATH = os.path.join(SANDBOX, "coder.json")
    if os.path.exists(coder.STATE_PATH):
        os.remove(coder.STATE_PATH)
    proj = os.path.join(SANDBOX, "proj")
    os.makedirs(proj, exist_ok=True)
    fake = os.path.join(SANDBOX, "fakecli.py")
    open(fake, "w", encoding="utf-8").write(
        "import sys, time\n"
        "a = sys.argv[1:]\n"
        "p = sys.stdin.read()\n"
        "if 'SLOW' in p:\n    time.sleep(30)\n"
        "print('Итог: готово'); print('args=' + ' '.join(a)); print('cwd-ok'); print('PROMPT>>' + p.replace(chr(10), ' | '))\n"
        "sys.exit(1 if 'FAIL' in p else 0)\n")
    cfg = make_cfg()
    cfg.update(coder_projects={"demo": proj}, coder_timeout=20,
               coder_agents={"claude": {"exe": sys.executable, "default_model": "sonnet",
                                        "cmd": ["{exe}", fake, "--model", "{model}", "--perm", "{perm}", "--sys", "{sysfile}", "{continue}"]},
                             "codex": {"exe": sys.executable, "default_model": "",
                                       "cmd": ["{exe}", fake, "exec", "--model", "{model}", "--sandbox", "{perm}", "-"]}})
    fo = FakeOllama()
    cfg["ollama_url"] = fo.url
    ui = UI()
    b = B.Brain(cfg, LLM(cfg), TTS(), Store(), ui)
    b.chats.delete_all()
    b.chats.add("user", "почему падает деплой на сервере")
    b.chats.add("assistant", "Смотрите логи nginx и php-fpm.")
    b.memory.clear()
    b.memory.add("проект chabandmitriy — Laravel 12", kind="fact")
    names = lambda c, text: [t.name for t in tools.available(c, text)]    # noqa: E731
    check("без проектов инструменты кодера скрыты", "ask_coder" not in names(make_cfg(), "спроси клода как поправить"))
    check("с проектом — только по явной просьбе", "ask_coder" in names(cfg, "спроси клода как поправить")
          and "ask_coder" not in names(cfg, "как поправить код"))
    b.turn_text = "спроси клода разбери ошибку деплоя"
    try:
        tools.call("ask_coder", {"task": "разбери ошибку деплоя"}, b)
        ok = False
    except tools.NeedsConfirm as e:
        ok = "в облако" in e.summary and "только чтение" in e.summary and "разбери ошибку" in e.summary
    check("запуск агента — только через карточку подтверждения (с пометкой про облако)", ok)
    r = tools.call("ask_coder", {"task": "разбери ошибку деплоя проекта chabandmitriy на Laravel 12", "context": "full", "model": "opus"}, b, confirmed=True)
    out = "\n".join(t for rr, t in ui.log if rr == "bot")
    check("ответ агента показан в чате, итог вернулся модели", "Итог: готово" in out and "Итог: готово" in r)
    check("модель и режим дошли до команды (plan → plan)", "--model opus" in out and "--perm plan" in out)
    check("контекст разговора и память переданы агенту", "Недавний разговор" in out and "почему падает деплой" in out
          and "Из памяти" not in out and "Laravel 12" in out and "ЗАДАЧА" in out and "разбери ошибку деплоя" in out)
    check("системная подсказка — файлом, не в командной строке", "--sys " in out and "khraz_sys_" in out)
    import reports as _rp
    rep = [f for f in os.listdir(_rp.folder(cfg)) if " Кодер — " in f] if os.path.isdir(_rp.folder(cfg)) else []
    check("ответ Клода сохранён заметкой: задача и ответ внутри", rep and "Итог: готово" in open(os.path.join(_rp.folder(cfg), rep[0]), encoding="utf-8").read()
          and "**Задача:** разбери ошибку деплоя" in open(os.path.join(_rp.folder(cfg), rep[0]), encoding="utf-8").read(), rep)
    ui.log.clear()
    tools.call("ask_coder", {"task": "ещё вопрос", "context": "none"}, b, confirmed=True)
    out2 = "\n".join(t for rr, t in ui.log if rr == "bot")
    check("context=none: разговор не передаётся", "Недавний разговор" not in out2 and "ЗАДАЧА" in out2)
    check("повторный запуск продолжает сессию (--continue)", "--continue" in out2)
    ui.log.clear()
    tools.call("ask_coder", {"task": "проверь модель по умолчанию", "agent": "codex"}, b, confirmed=True)
    out3 = "\n".join(t for rr, t in ui.log if rr == "bot")
    check("codex: шаблон, режим plan → песочница read-only, пустая модель отбрасывается", "exec" in out3 and "--sandbox read-only" in out3
          and "--model" not in out3)
    ui.log.clear()
    tools.call("ask_coder", {"task": "поправь файл", "mode": "edit"}, b, confirmed=True)
    check("режим edit → acceptEdits", "--perm acceptEdits" in "\n".join(t for rr, t in ui.log if rr == "bot"))
    coder.set_state(cfg, mode="plan")
    for bad in ({"task": "x", "project": "../etc"}, {"task": "x", "agent": "rm -rf"}, {"task": "x", "model": "a b;c"}):
        try:
            tools.call("ask_coder", bad, b, confirmed=True)
            ok = False
        except tools.ToolError:
            ok = True
        check(f"проверка аргументов: {list(bad.values())[1]}", ok)
    try:
        tools.call("ask_coder", {"task": "это FAIL"}, b, confirmed=True)
        ok = False
    except tools.ToolError as e:
        ok = "код 1" in str(e)
    check("ошибка агента — понятная, вывод всё равно показан", ok)
    # переключение
    r = tools.call("coder_set", {"agent": "codex", "model": "gpt-5"}, b)
    st = coder.get_state(cfg)
    check("переключение агента и модели", st["agent"] == "codex" and st["model"] == "gpt-5" and "codex" in r)
    st = coder.set_state(cfg, agent="claude")
    check("смена агента → его модель по умолчанию", st["agent"] == "claude" and st["model"] == "sonnet")
    try:
        coder.set_state(cfg, project="nope")
        ok = False
    except ValueError:
        ok = True
    check("проект вне списка выбрать нельзя", ok)
    s = coder.status(cfg)
    check("статус для главного экрана: агенты, проекты", s["configured"] and {a["id"] for a in s["agents"]} == {"claude", "codex"}
          and s["projects"] == ["demo"] and all(a["installed"] for a in s["agents"]))
    # СТОП и лимит времени
    res = {}
    th = threading.Thread(target=lambda: res.update(r=coder.run(b, "SLOW задача", context="none")), daemon=True)
    t0 = time.time()
    th.start()
    time.sleep(1.2)
    b.llm.cancel.set()
    th.join(15)
    check("«СТОП» завершает процесс агента", not th.is_alive() and res["r"]["cancelled"] and time.time() - t0 < 12)
    b.llm.cancel.clear()
    cfg["coder_timeout"] = 1
    r2 = coder.run(b, "SLOW задача", context="none")
    check("лимит времени останавливает агента", not r2["ok"] and "лимиту времени" in r2["output"] and r2["secs"] < 10)
    fo.close()


def test_khraz_info():
    import persona
    cfg = make_cfg()
    ctx = Ctx(cfg)
    info = tools.call("khraz_info", {}, ctx)
    check("khraz_info: модели, коннекторы, кодер", set(info) >= {"модели", "коннекторы", "кодер"})
    sp = persona.system_prompt(cfg, [])
    check("подсказка модели не упоминает убранные веб-панель и Telegram", "dashboard" not in sp and "Telegram" not in sp)


def test_reports():
    import shutil
    import brain as B
    import reports
    import watcher as W
    from commands import Store
    from llm import LLM
    cfg = make_cfg()
    d = reports.folder(cfg)
    shutil.rmtree(d, ignore_errors=True)
    reports._recent.clear()
    secret = "vless://abcd@host:443?security=reality#ivan"
    uid = "123e4567-e89b-12d3-a456-426614174000"
    p1 = reports.save(cfg, "rule", "Сводка: VPN/клиенты?", f"Онлайн 3\n{secret}\nклиент {uid}")
    txt = open(p1, encoding="utf-8").read()
    base = os.path.basename(p1)
    check("отчёт — .md в «Отчёты ХРАЗ»: дата, вид, безопасное имя", os.path.dirname(p1) == d and base.endswith(".md") and " Правило — Сводка VPN клиенты" in base
          and not any(c in base for c in '\\/:*?"<>|'), base)
    check("формат Obsidian: frontmatter (type, created, tags) и заголовок", txt.startswith("---\ntype: rule\ncreated: ") and "tags: [храз, отчёт, rule]" in txt
          and "\n# Правило — Сводка VPN клиенты\n" in txt)
    check("ссылки подписок и UUID клиентов скрыты", secret not in txt and uid not in txt and "[ссылка скрыта]" in txt and "[id скрыт]" in txt and "Онлайн 3" in txt)
    p2 = reports.save(cfg, "rule", "Сводка: VPN/клиенты?", "другой текст")
    check("тот же заголовок в ту же минуту — новый файл, старый не тронут", p2 != p1 and "(2)" in p2 and open(p1, encoding="utf-8").read() == txt)
    check("один и тот же текст дважды за полчаса — не дублируется", reports.save(cfg, "rule", "Сводка: VPN/клиенты?", "другой текст") is None)
    check("выключено в настройках — ничего не пишется", reports.save(dict(cfg, notes_autosave=False), "table", "x", "строка") is None)
    check("пустой текст и неизвестный вид — пропуск", reports.save(cfg, "table", "x", "  ") is None and reports.save(cfg, "чат", "x", "текст") is None)
    check("запрещённая папка — тихо None, без исключения", reports.save(dict(cfg, forbidden_paths=[os.path.dirname(d)]), "table", "запрет", "текст") is None)
    fo = FakeOllama()
    cfg["ollama_url"] = fo.url
    ui = UI()
    b = B.Brain(cfg, LLM(cfg), TTS(), Store(), ui)
    r = tools.call("show_table", {"columns": ["Ученик", "Долг"], "rows": [["Иван", "1500"]], "title": "Долги за ноябрь"}, b)
    got = [f for f in os.listdir(d) if "Таблица — Долги за ноябрь" in f]
    check("таблица от ХРАЗа сохранена заметкой", got and "| Иван | 1500 |" in open(os.path.join(d, got[0]), encoding="utf-8").read(), os.listdir(d))
    b.watcher = W.Watcher(b, path=os.path.join(SANDBOX, "w_rep.json"))
    real_due = scheduler.due
    scheduler.due = lambda now: [{"title": "Дежурная проверка", "tool": "show_table",
                                  "args": {"columns": ["a"], "rows": [["правило-результат"]], "title": "из правила"}}]
    b.watcher.check_rules(datetime.datetime.now())
    scheduler.due = real_due
    check("результат правила по расписанию сохранён заметкой", any("Правило — Дежурная проверка" in f for f in os.listdir(d)), os.listdir(d))
    b.morning()
    check("утренняя сводка сохранена заметкой", any("Утренняя сводка" in f for f in os.listdir(d)), os.listdir(d))
    fo.close()


def test_stt_whisper():
    import struct
    import types
    import stt as S
    import brain as B
    from commands import Store
    from llm import LLM

    def chunk(amp, n=4000):
        return b"".join(struct.pack("<h", amp if (i // 20) % 2 else -amp) for i in range(n))
    quiet, loud = chunk(8), chunk(3000)
    chunks = [(quiet, S.rms(quiet))] * 10 + [(loud, S.rms(loud))] * 6 + [(quiet, S.rms(quiet))] * 3
    out = S.trim_utterance(chunks)
    check("Whisper: из буфера вырезана тишина в начале, оставлено 2 блока до голоса", len(out) == (2 + 6 + 3) * 8000, len(out))
    check("Whisper: одна тишина — пустая фраза", S.trim_utterance([(quiet, S.rms(quiet))] * 12) == b"" and S.trim_utterance([]) == b"")
    check("громкость блока считается (тишина ≪ голос)", S.rms(quiet) < 20 < 2500 < S.rms(loud))
    check("«галлюцинации» Whisper на шуме отсекаются", S.looks_hallucinated("Субтитры сделал DimaTorzok", "") and S.looks_hallucinated("Продолжение следует...", "раз")
          and S.looks_hallucinated("да да да да да да да", "да") and S.looks_hallucinated("", "привет")
          and S.looks_hallucinated("очень длинная фраза " * 12, "тест") and not S.looks_hallucinated("Открой калькулятор.", "открой калькулятор"))

    class FakeW:
        def __init__(self, text="Открой калькулятор.", ready=True, boom=False):
            self.text, self.ready, self.boom, self.got = text, ready, boom, []
        def transcribe(self, pcm):
            self.got.append(len(pcm))
            if self.boom:
                raise RuntimeError("упала")
            return self.text
    cfg = make_cfg()
    st = S.STT(cfg, on_final=lambda *a: None)
    ch = [(loud, S.rms(loud))] * 6
    check("движок vosk: текст не меняется", st.refine("открой калькулятор", ch) == "открой калькулятор" and st.last_engine == "vosk")
    st.whisper = FakeW()
    check("Whisper готов: берётся его текст (с пунктуацией и регистром)", st.refine("откройте калькулятор", ch) == "Открой калькулятор." and st.last_engine == "whisper")
    st.whisper = FakeW(ready=False)
    check("Whisper ещё грузится — работает Vosk, без ожидания", st.refine("привет", ch) == "привет" and st.whisper.got == [])
    st.whisper = FakeW(text="Субтитры сделал DimaTorzok")
    check("галлюцинация — берётся Vosk", st.refine("привет", ch) == "привет" and st.last_engine == "vosk")
    st.whisper = FakeW(boom=True)
    check("ошибка Whisper — берётся Vosk, без падения", st.refine("привет", ch) == "привет")
    st.whisper = FakeW()
    check("слишком короткий звук (<0,4 с) не отправляется в Whisper", st.refine("да", [(loud, S.rms(loud))]) == "да" and st.whisper.got == [])

    # движок на подставном faster_whisper: порядок попыток cuda → cpu, фильтр сегментов, подсказка, нет пакета
    calls, notes = [], []

    class Seg:
        def __init__(self, text, nsp=0.0, lp=-0.2):
            self.text, self.no_speech_prob, self.avg_logprob = text, nsp, lp

    class FM:
        def __init__(self, name, device="cpu", compute_type="int8", download_root=None):
            calls.append((name, device, compute_type, download_root))
            if device == "cuda":
                raise RuntimeError("CUDA не найдена")
            self.kw = None
        def transcribe(self, audio, **kw):
            FM.last = (len(audio), kw)
            return iter([Seg(" Открой "), Seg("шум", 0.9, -2.0), Seg("калькулятор ")]), None
    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = FM
    real = sys.modules.get("faster_whisper", "нет")
    sys.modules["faster_whisper"] = fake
    try:
        w = S.WhisperEngine(dict(cfg, whisper_model="small", whisper_device="auto"), note=notes.append)
        w.load()
        check("Whisper: видеокарта не вышла — загрузился на процессоре (int8)", w.ready and w.device == "cpu" and [c[1] for c in calls] == ["cuda", "cpu"]
              and calls[1][2] == "int8" and calls[1][3].endswith(os.path.join("models", "whisper")), calls)
        check("…пользователю сказано, что готов", any("готов" in n and "процессор" in n for n in notes), notes)
        text = w.transcribe(b"\x00\x00" * 16000)
        n_samples, kw = FM.last
        check("Whisper: язык ru, подсказка со словарём, шумовой сегмент отброшен", text == "Открой калькулятор" and kw["language"] == "ru"
              and "ХРАЗ" in kw["initial_prompt"] and kw["condition_on_previous_text"] is False and n_samples == 16000, (text, kw))

        class FM2(FM):
            def __init__(self, *a, **k):
                self.cuda = k.get("device") == "cuda"
                calls.append(("fm2", k.get("device")))
            def transcribe(self, audio, **kw):
                if self.cuda:
                    raise RuntimeError("Library cublas64_12.dll is not found")
                return iter([Seg("после перехода")]), None
        fake.WhisperModel = FM2
        calls.clear()
        w2 = S.WhisperEngine(dict(cfg, whisper_device="cuda"), note=notes.append)
        w2.load()
        check("Whisper: на видеокарте загрузился", w2.device == "cuda")
        check("Whisper: на видеокарте нет библиотек CUDA — сам переходит на процессор и отвечает", w2.transcribe(b"\x00\x00" * 8000) == "после перехода" and w2.device == "cpu", calls)
    finally:
        if real == "нет":
            sys.modules.pop("faster_whisper", None)
        else:
            sys.modules["faster_whisper"] = real
    notes.clear()
    sys.modules["faster_whisper"] = None                                    # пакета нет → ImportError
    try:
        w3 = S.WhisperEngine(cfg, note=notes.append)
        w3.load()
        check("нет пакета faster-whisper — понятное сообщение, работа на Vosk", not w3.ready and any("pip install faster-whisper" in n and "Vosk" in n for n in notes), notes)
    finally:
        if real == "нет":
            sys.modules.pop("faster_whisper", None)
        else:
            sys.modules["faster_whisper"] = real

    # цикл распознавания целиком: подставные sounddevice и vosk, три фразы
    got, partials = [], []
    state = {"muted": True}

    class FK:
        def __init__(self, model, rate, grammar=None):
            self.grammar, self.n = grammar, 0
        def AcceptWaveform(self, data):
            if self.grammar:
                return False
            self.n += 1
            return self.n % 6 == 0
        def Result(self):
            return json.dumps({"text": "откройте калькулятор"})
        def PartialResult(self):
            return json.dumps({"partial": "храз" if self.grammar else "открой"})
        def Reset(self):
            self.n = 0

    class FStream:
        def __init__(self, samplerate, blocksize, dtype, channels, device, callback):
            self.cb, self.alive = callback, True
        def start(self):
            def feed():
                for i in range(18):
                    if not self.alive:
                        return
                    self.cb(loud, 4000, None, None)
                    time.sleep(0.01)
                    if i == 5:
                        state["muted"] = False                          # первая фраза прошла, пока ХРАЗ «говорил»
                while self.alive:
                    time.sleep(0.05)
            threading.Thread(target=feed, daemon=True).start()
        def stop(self):
            self.alive = False
        def close(self):
            self.alive = False
    sd_ = types.ModuleType("sounddevice")
    sd_.RawInputStream = FStream
    vk = types.ModuleType("vosk")
    vk.Model, vk.KaldiRecognizer, vk.SetLogLevel = (lambda p: object()), FK, (lambda n: None)
    saved = {k: sys.modules.get(k) for k in ("sounddevice", "vosk")}
    sys.modules["sounddevice"], sys.modules["vosk"] = sd_, vk
    try:
        c2 = dict(cfg, vosk_model_abs=SANDBOX, stt_engine="whisper", wake_spotter=True, barge_in=False)
        st2 = S.STT(c2, on_final=lambda t, sp: got.append((t, sp)), on_partial=partials.append, is_muted=lambda: state["muted"])
        st2.whisper = FakeW()
        check("цикл распознавания запущен", st2.start())
        check("пока ХРАЗ говорил (микрофон заглушён) — фраза не распознаётся; потом две фразы идут через Whisper",
              wait(lambda: len(got) >= 1, 10), got)
        time.sleep(0.3)
        check("итог цикла: текст Whisper, слово активации услышал отдельный распознаватель (spotted)", got and all(t == "Открой калькулятор." for t, _ in got) and got[0][1] is True, got)
        check("в Whisper ушёл звук одной фразы (6 блоков по 8000 байт), а не весь поток", st2.whisper.got and all(n == 6 * 8000 for n in st2.whisper.got), st2.whisper.got)
        check("частичные результаты Vosk идут как раньше", "открой" in partials)
        st2.enabled.clear()
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    fo = FakeOllama()
    b = B.Brain(make_cfg(fo.url), LLM(make_cfg(fo.url)), TTS(), Store(), UI())
    check("«Хараз, открой…» (так Whisper слышит ХРАЗ) — слово активации срезается", b._strip_wake_raw("Хараз, открой калькулятор.", True) == "открой калькулятор."
          and b._strip_wake_raw("Храз, открой калькулятор.", False) == "открой калькулятор.")
    fo.close()


if __name__ == "__main__":
    for f in (test_fallback_and_games, test_powershell_gate, test_groups, test_scheduler, test_read_log,
              test_router_extras, test_verify_undo_stats_wol, test_present_and_text, test_coder, test_khraz_info, test_reports, test_stt_whisper):
        print(f"\n— {f.__name__}")
        f()
    print(f"\nВсе проверки дополнений пройдены: {len(T.PASSED)}")
