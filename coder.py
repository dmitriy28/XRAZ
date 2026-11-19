"""Мост к внешним кодовым агентам — Claude Code и Codex (их командные программы `claude` и `codex`).

ХРАЗ передаёт задачу вместе с контекстом (недавний разговор, нужные факты из памяти, проект) и показывает ответ в чате.
Безопасность:
- работает только по явной просьбе («спроси Клода…», «отдай Кодексу…», «через кодера…») и только после подтверждения: в карточке
  видно агента, модель, проект, режим и уровень контекста — он уходит в облако (Anthropic/OpenAI);
- проекты — только из coder_projects (имя → папка); произвольные пути и команды модель задать не может;
- по умолчанию режим «plan»: только чтение и анализ. Режим «edit» (правки файлов) подтверждается только в окне ХРАЗа;
  режимы без запросов разрешений (bypassPermissions и т. п.) не предусмотрены вовсе;
- запрос идёт через stdin, а системная подсказка — через временный файл: в командную строку не попадает ничего, кроме
  проверенных имён модели и режима (важно для .cmd-оболочек npm в Windows);
- «СТОП» / Esc завершает процесс агента; лимит времени coder_timeout (по умолчанию 900 с).
Шаблоны команд можно поменять в config.json (coder_agents), если у вас другая версия программы."""
import copy
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from config import DATA

STATE_PATH = os.path.join(DATA, "coder.json")
MODEL_RE = re.compile(r"[\w.\-:/]{1,60}")
MODES = ("plan", "edit")
CONTEXTS = ("none", "chat", "full")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
SYSTEM_PROMPT = ("Тебя вызвал локальный голосовой ассистент ХРАЗ по просьбе владельца. Отвечай по-русски. Первая строка — "
                 "краткий итог (его озвучат), дальше разбор: файлы, причины, шаги. Если режим только чтение — ничего не меняй.")

DEFAULT_AGENTS = {
    "claude": {"title": "Claude Code", "exe": "claude",
               "cmd": ["{exe}", "-p", "--model", "{model}", "--permission-mode", "{perm}",
                       "--append-system-prompt-file", "{sysfile}", "{continue}"],
               "perm": {"plan": "plan", "edit": "acceptEdits"}, "models": ["sonnet", "opus", "haiku"],
               "default_model": "sonnet", "continue": "--continue"},
    "codex": {"title": "Codex", "exe": "codex",
              "cmd": ["{exe}", "exec", "--model", "{model}", "--sandbox", "{perm}", "--skip-git-repo-check", "-"],
              "perm": {"plan": "read-only", "edit": "workspace-write"}, "models": ["gpt-5-codex", "gpt-5"],
              "default_model": "gpt-5-codex", "continue": ""},
}
_lock = threading.Lock()
_proc = {"p": None}


def agents(cfg):
    """Агенты: встроенные шаблоны + поверх них coder_agents из config.json."""
    out = copy.deepcopy(DEFAULT_AGENTS)
    for name, a in (cfg.get("coder_agents") or {}).items():
        if isinstance(a, dict):
            out.setdefault(name, {"title": name, "exe": name, "cmd": [], "perm": {"plan": "plan", "edit": "plan"},
                                  "models": [], "default_model": "", "continue": ""}).update(a)
    return out


def projects(cfg):
    return {k: os.path.expanduser(v) for k, v in (cfg.get("coder_projects") or {}).items() if isinstance(v, str) and v}


def exe_path(cfg, name, agent):
    custom = (cfg.get("coder_paths") or {}).get(name)
    return custom if custom and os.path.exists(os.path.expanduser(custom)) else shutil.which(agent.get("exe") or name)


# ---------------------------------------------------------------- выбор агента/модели (переключается из окна, браузера, голосом)
def get_state(cfg):
    ags = agents(cfg)
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    pj = projects(cfg)
    agent = st.get("agent") if st.get("agent") in ags else (cfg.get("coder_default") if cfg.get("coder_default") in ags else "claude")
    model = st.get("model") if st.get("model") and MODEL_RE.fullmatch(st.get("model", "")) else ags[agent].get("default_model", "")
    project = st.get("project") if st.get("project") in pj else (next(iter(pj), ""))
    return {"agent": agent, "model": model, "mode": st.get("mode") if st.get("mode") in MODES else "plan",
            "context": st.get("context") if st.get("context") in CONTEXTS else "chat", "project": project,
            "last": st.get("last") or {}, "sessions": st.get("sessions") or {}}


def set_state(cfg, **kw):
    ags, pj = agents(cfg), projects(cfg)
    st = get_state(cfg)
    if kw.get("agent") is not None:
        if kw["agent"] not in ags:
            raise ValueError("агент: " + ", ".join(ags))
        if kw["agent"] != st["agent"] and kw.get("model") is None:
            kw["model"] = ags[kw["agent"]].get("default_model", "")      # другой агент — его модель по умолчанию
        st["agent"] = kw["agent"]
    if kw.get("model") is not None:
        if kw["model"] and not MODEL_RE.fullmatch(kw["model"]):
            raise ValueError("название модели: буквы, цифры, . - _ : /")
        st["model"] = kw["model"]
    if kw.get("mode") is not None:
        if kw["mode"] not in MODES:
            raise ValueError("режим: plan (чтение) или edit (правки)")
        st["mode"] = kw["mode"]
    if kw.get("context") is not None:
        if kw["context"] not in CONTEXTS:
            raise ValueError("контекст: none, chat или full")
        st["context"] = kw["context"]
    if kw.get("project") is not None:
        if kw["project"] not in pj:
            raise ValueError("проекта нет в coder_projects")
        st["project"] = kw["project"]
    _save(st)
    return get_state(cfg)


def effective_mode(args):
    """Режим, в котором реально запустится агент: явный из запроса, иначе выбранный в настройках, иначе plan."""
    if (args or {}).get("mode") in MODES:
        return args["mode"]
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            m = json.load(f).get("mode")
        return m if m in MODES else "plan"
    except (OSError, ValueError):
        return "plan"


def _save(st):
    keep = {k: st[k] for k in ("agent", "model", "mode", "context", "project", "last", "sessions") if k in st}
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(keep, f, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


def status(cfg):
    ags, pj, st = agents(cfg), projects(cfg), get_state(cfg)
    return {"state": st, "projects": list(pj), "configured": bool(pj), "needs_project": not pj,
            "agents": [{"id": k, "title": a.get("title", k), "installed": bool(exe_path(cfg, k, a)), "models": a.get("models", []),
                        "default_model": a.get("default_model", "")} for k, a in ags.items()]}


PROJECT_RE = re.compile(r"[\w\-]{1,30}")


def add_project(cfg, path, name=""):
    """Добавляет проект (папку) в coder_projects. Вызывается только из окна ХРАЗа (диалог выбора папки) — не из чата и не из браузера.
    Возвращает имя проекта; сохранение config.json — на вызывающей стороне."""
    path = os.path.abspath(os.path.expanduser(str(path or "")))
    if not os.path.isdir(path):
        raise ValueError("папка не найдена")
    name = (name or os.path.basename(path.rstrip("/\\")) or "project").strip().lower().replace(" ", "-")
    if not PROJECT_RE.fullmatch(name):
        name = re.sub(r"[^\w\-]", "", name)[:30] or "project"
    pj = dict(cfg.get("coder_projects") or {})
    base, i = name, 2
    while name in pj and os.path.abspath(os.path.expanduser(pj[name])) != path:
        name, i = f"{base}-{i}", i + 1
    pj[name] = path
    cfg["coder_projects"] = pj
    return name


# ---------------------------------------------------------------- контекст и запуск
def build_prompt(brain, task, level, project, mode):
    parts = []
    if level != "none":
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        parts.append(f"# Контекст от ассистента ХРАЗ\nСейчас {now}. Проект: {project}. Режим: "
                     f"{'можно править файлы' if mode == 'edit' else 'только чтение и анализ, файлы не менять'}.")
        msgs = [m for m in (brain.chats.messages[-8:] if getattr(brain, "chats", None) else []) if m.get("content")]
        if msgs:
            lines, total = [], 0
            for m in msgs:
                who = "Владелец" if m["role"] == "user" else "ХРАЗ"
                text = " ".join(m["content"].split())[:800]
                total += len(text)
                if total > 6000:
                    break
                lines.append(f"- {who}: {text}")
            parts.append("## Недавний разговор\n" + "\n".join(lines))
        if level == "full" and getattr(brain, "memory", None):
            try:
                facts = [m["text"] for m in brain.memory.relevant(task, 6)]
            except Exception:                   # noqa: BLE001
                facts = []
            if facts:
                parts.append("## Что известно о владельце (из памяти ХРАЗа)\n" + "\n".join(f"- {x[:300]}" for x in facts))
    parts.append("# ЗАДАЧА\n" + task.strip())
    return "\n\n".join(parts)


def _argv(cfg, name, agent, model, mode, sysfile, cont):
    perm = (agent.get("perm") or {}).get(mode)
    if not perm:
        raise ValueError(f"у агента {name} нет режима {mode}")
    exe = exe_path(cfg, name, agent)
    if not exe:
        raise FileNotFoundError(f"не найдена программа «{agent.get('exe') or name}» (установите или укажите путь в coder_paths)")
    values = {"{exe}": exe, "{model}": model, "{perm}": perm, "{sysfile}": sysfile, "{continue}": agent.get("continue", "") if cont else ""}
    out, tpl, i = [], list(agent.get("cmd") or []), 0
    while i < len(tpl):
        tok = tpl[i]
        nxt = tpl[i + 1] if i + 1 < len(tpl) else None
        if tok.startswith("--") and nxt in values and not values[nxt]:       # необязательная пара: «--model» без модели
            i += 2
            continue
        if tok in values:
            if values[tok]:
                out.append(values[tok])
        else:
            out.append(tok)
        i += 1
    return out


def _kill(p):
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=10, creationflags=0x08000000)
        else:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
    except Exception:                           # noqa: BLE001
        pass


def stop():
    p = _proc.get("p")
    if p and p.poll() is None:
        _kill(p)


def run(brain, task, agent=None, model=None, project=None, mode=None, context=None, on_line=None):
    """Выполняет задачу. Возвращает dict: ok, output, secs, agent, model, project, mode, cancelled."""
    cfg = brain.cfg
    ags, pj, st = agents(cfg), projects(cfg), get_state(cfg)
    agent, project, mode, context = agent or st["agent"], project or st["project"], mode or st["mode"], context or st["context"]
    if agent not in ags:
        raise ValueError(f"агента «{agent}» нет")
    if project not in pj:
        raise ValueError("проект не выбран или его нет в coder_projects")
    cwd = pj[project]
    if not os.path.isdir(cwd):
        raise FileNotFoundError(f"папка проекта не найдена: {cwd}")
    if mode == "edit" and not cfg.get("coder_allow_edit", True):
        raise ValueError("режим правок выключен (coder_allow_edit)")
    model = model if model is not None else (st["model"] if agent == st["agent"] else ags[agent].get("default_model", ""))
    if model and not MODEL_RE.fullmatch(model):
        raise ValueError("неверное название модели")
    prompt = build_prompt(brain, task, context, project, mode)
    cont = bool(cfg.get("coder_continue", True)) and agent == "claude" and \
        (time.time() - float((st["sessions"] or {}).get(f"{agent}:{project}", 0))) < 7200
    fd, sysfile = tempfile.mkstemp(prefix="khraz_sys_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(SYSTEM_PROMPT)
    argv = _argv(cfg, agent, ags[agent], model, mode, sysfile, cont)
    timeout = int(cfg.get("coder_timeout", 900))
    t0, lines, cancelled = time.time(), [], False
    try:
        p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", env=dict(os.environ, NO_COLOR="1", TERM="dumb"),
                             creationflags=0x08000000 if sys.platform == "win32" else 0)
        _proc["p"] = p

        def feed():
            try:
                p.stdin.write(prompt)
                p.stdin.close()
            except OSError:
                pass

        def read():
            for line in p.stdout:
                line = ANSI.sub("", line.rstrip("\n"))
                lines.append(line)
                if on_line and line.strip():
                    on_line(line.strip()[:120])
        ts = [threading.Thread(target=feed, daemon=True), threading.Thread(target=read, daemon=True)]
        for t in ts:
            t.start()
        cancel = getattr(getattr(brain, "llm", None), "cancel", None)
        while p.poll() is None:
            if cancel is not None and cancel.is_set():
                cancelled = True
                _kill(p)
                break
            if time.time() - t0 > timeout:
                _kill(p)
                lines.append(f"[остановлено по лимиту времени {timeout} с]")
                break
            time.sleep(0.1)
        for t in ts:
            t.join(3)
        code = p.poll()
    finally:
        _proc["p"] = None
        try:
            os.remove(sysfile)
        except OSError:
            pass
    out = "\n".join(lines).strip()[:200_000]
    ok = code == 0 and not cancelled
    st2 = get_state(cfg)
    st2["last"] = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "agent": agent, "model": model, "project": project, "ok": ok,
                   "secs": round(time.time() - t0, 1)}
    if ok:
        st2["sessions"] = dict(st2["sessions"], **{f"{agent}:{project}": time.time()})
    _save(st2)
    return {"ok": ok, "output": out, "secs": time.time() - t0, "agent": agent, "model": model, "project": project,
            "mode": mode, "cancelled": cancelled, "code": code, "continued": cont}
