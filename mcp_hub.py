"""Сторонние MCP-серверы (GitHub, файловые, базы данных, Notion, свой код…) — как в Claude Desktop.

Каждый сервер из настроек (Коннекторы → «MCP-серверы») подключается отдельно: stdio (команда: npx, uvx, python,
exe), Streamable HTTP или SSE (URL + заголовки). Его инструменты попадают в общий реестр tools/ под именами
mcp_<сервер>_<инструмент> и вызываются моделью так же, как встроенные: проверка аргументов, журнал, карточка
запроса в чате, подтверждения.

Уровни доверия (что спрашивать):
- ask       — подтверждать каждый вызов (по умолчанию для новых серверов);
- read_auto — инструменты с пометкой «только чтение» (readOnlyHint) сразу, остальные — с подтверждением;
- auto      — всё сразу, кроме помеченных как разрушительные (destructiveHint) — их всегда подтверждаем.
Секреты (переменные окружения и HTTP-заголовки с токенами) — в хранилище Windows, не в config.json.
Результаты инструментов — данные, а не инструкции."""
import json
import re
import threading

import tools
from tools import Tool, ToolError

TRUST = ("ask", "read_auto", "auto")


def slug(s, n=20):
    s = re.sub(r"[^A-Za-z0-9_]+", "_", s.lower()).strip("_")
    return s[:n] or "x"


def secrets_key(name):
    return f"MCP_SECRETS::{name}"


def load_secrets(name):
    import khraz_secrets
    raw = khraz_secrets.get(secrets_key(name))
    try:
        d = json.loads(raw) if raw else {}
    except ValueError:
        d = {}
    return {"env": d.get("env") or {}, "headers": d.get("headers") or {}}


def save_secrets(name, env, headers):
    import khraz_secrets
    khraz_secrets.set(secrets_key(name), json.dumps({"env": env, "headers": headers}, ensure_ascii=False)
                      if (env or headers) else "")


def parse_secrets(text):
    """Строки «KEY=VALUE» — переменные окружения, «Header: value» — HTTP-заголовки."""
    env, headers = {}, {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line and (":" not in line or line.index("=") < line.index(":")):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
        elif ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip()] = v.strip()
    return env, headers


def import_claude_desktop(data):
    """Конфиг Claude Desktop/Cursor ({"mcpServers": {...}}) → (серверы для config.json, секреты по именам)."""
    servers, secrets = [], {}
    for name, s in (data.get("mcpServers") or data.get("servers") or {}).items():
        item = {"name": name, "enabled": True, "trust": "ask", "keywords": name}
        if s.get("url"):
            item.update(type=(s.get("type") or "http").replace("streamable-http", "http"), url=s["url"])
        else:
            item.update(type="stdio", command=s.get("command", ""), args=list(s.get("args") or []))
        secrets[name] = {"env": s.get("env") or {}, "headers": s.get("headers") or {}}
        servers.append(item)
    return servers, secrets


class Hub:
    def __init__(self, brain):
        self.b = brain
        self.adapters = {}           # имя сервера → MCPAdapter
        self.names = {}              # имя инструмента в реестре → (сервер, настоящее имя)
        self.lock = threading.Lock()

    @property
    def cfg(self):
        return self.b.cfg

    def servers(self):
        return [s for s in (self.cfg.get("mcp_servers") or []) if s.get("name")]

    # ---- подключение -------------------------------------------------------------------
    def _conf(self, s):
        sec = load_secrets(s["name"])
        server = {"type": s.get("type") or ("http" if s.get("url") else "stdio")}
        if server["type"] == "stdio":
            server.update(command=s.get("command", ""), args=list(s.get("args") or []), env=sec["env"],
                          cwd=s.get("cwd") or "")
        else:
            server.update(url=s.get("url", ""), headers=sec["headers"])
        return {"server": server, "allowed_tools": s.get("allowed_tools") or [],
                "read_timeout_sec": 60, "write_timeout_sec": 120}

    def start(self, wait=25):
        """Подключить все включённые серверы (каждый в своём потоке) и зарегистрировать их инструменты."""
        self.stop()
        threads = []
        for s in self.servers():
            if s.get("enabled", True):
                t = threading.Thread(target=self._start_one, args=(s, wait), daemon=True)
                t.start()
                threads.append(t)
        for t in threads:
            t.join(wait + 5)
        return self.status()

    def _start_one(self, s, wait):
        from khraz_mcp_adapter import MCPAdapter
        try:
            a = MCPAdapter(conf=self._conf(s))
        except Exception as e:                      # неверная настройка
            self.b._emit("action", f"MCP «{s['name']}»: {e}")
            return
        with self.lock:
            self.adapters[s["name"]] = a
        a.start(wait)
        if a.connected:
            self._register(s, a)

    def stop(self):
        with self.lock:
            adapters, self.adapters = dict(self.adapters), {}
        for name in list(self.names):
            tools.REGISTRY.pop(name, None)
        self.names.clear()
        for a in adapters.values():
            try:
                a.stop()
            except Exception:
                pass

    def status(self):
        out = []
        for s in self.servers():
            a = self.adapters.get(s["name"])
            if not s.get("enabled", True):
                st = "выключен"
            elif not a:
                st = "не подключён"
            elif a.connected:
                st = f"подключён · {len(a.tools)} инстр."
            else:
                st = f"ошибка: {a.error or 'нет ответа'}"
            out.append((s["name"], bool(a and a.connected), st))
        return out

    def summary(self):
        st = self.status()
        return f"{sum(1 for _, ok, _ in st if ok)}/{len(st)}" if st else ""

    # ---- инструменты в общий реестр ---------------------------------------------------
    def _risk(self, trust, meta):
        if meta.get("destructive"):
            return "delete"
        if meta.get("read_only") and trust in ("read_auto", "auto"):
            return "read"
        return "action" if trust == "auto" else "change"

    def _register(self, s, a):
        trust = s.get("trust") if s.get("trust") in TRUST else "ask"
        pref = f"mcp_{slug(s['name'], 16)}_"
        for real, meta in a.tools.items():
            name = (pref + slug(real, 64))[:64]
            schema = dict(meta.get("schema") or {"type": "object", "properties": {}})
            schema.setdefault("type", "object")
            schema.setdefault("additionalProperties", True)
            risk = self._risk(trust, meta)

            def fn(ctx, _a=a, _real=real, _risk=risk, _srv=s["name"], **args):
                if not _a.connected:
                    raise ToolError(f"MCP-сервер «{_srv}» отключён")
                ctx.ui_action(f"MCP {_srv}: {_real}")
                res = _a.call(_real, args, write=_risk != "read")
                if not res.ok:
                    raise ToolError(f"«{_srv}»: {(res.error or res.text or 'ошибка')[:500]}")
                return res.data if isinstance(res.data, (dict, list)) else (res.text or "Готово")

            desc = f"[MCP {s['name']}] {meta.get('description') or real}"[:1000]
            t = Tool(name, desc, schema, fn, risk=risk,
                     summary=lambda args, _r=real, _s=s["name"]: f"MCP «{_s}»: {_r} "
                                                                  + json.dumps(args, ensure_ascii=False)[:300])
            t.when = lambda cfg, _a=a: _a.connected
            t.mcp_server = s["name"]
            tools.REGISTRY[name] = t
            self.names[name] = (s["name"], real)

    # ---- маршрутизация ------------------------------------------------------------------
    def wants(self, text):
        """Реплика про подключённый сервер: его имя или ключевые слова из настроек."""
        t = (text or "").lower()
        for s in self.servers():
            a = self.adapters.get(s["name"])
            if not (a and a.connected):
                continue
            words = [s["name"]] + [w.strip() for w in (s.get("keywords") or "").split(",")]
            if any(w and w.lower() in t for w in words):
                return True
        return False
