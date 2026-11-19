"""Адаптер ХРАЗа к MCP-серверам (сторонним) (stdio, MCP Python SDK 2.x).

Шлюз о ХРАЗе не знает; адаптер не знает о личности. Что делает:
- запускает MCP-сервер из конфигурации (conf) и держит одну сессию в фоновом потоке;
- отдаёт модели только инструменты из allowed_tools (белый список клиента; права всё равно проверяет сервер);
- читает сразу, а инструменты записи (write_tools) сам НЕ вызывает — их вызывает только мозг после
  подтверждения кнопкой (confirmations.py);
- при обрыве связи на записи возвращает unknown=True — повторять вслепую нельзя;
- stop() — закрывает сессию и процесс сервера, новые вызовы невозможны."""
import asyncio
import concurrent.futures
import json
import os
import threading

from config import BASE

CONFIG_PATH = os.environ.get("KHRAZ_MCP_CONFIG") or os.path.join(BASE, "khraz_mcp_config.json")   # только если conf не передан


def _bundled_path(a):
    if os.path.isabs(a):
        return a
    for cand in (os.path.normpath(os.path.join(BASE, a))):
        if os.path.exists(cand):
            return cand
    return os.path.normpath(os.path.join(BASE, a))


def _safe(name):
    """Имена вида finance.debtors → finance__debtors (точки в именах функций модели не любят)."""
    return name.replace(".", "__")


class MCPResult:
    def __init__(self, ok, text="", data=None, error="", unknown=False):
        self.ok, self.text, self.data, self.error, self.unknown = ok, text, data, error, unknown

    def __repr__(self):
        return f"MCPResult(ok={self.ok}, unknown={self.unknown}, error={self.error!r}, text={self.text[:80]!r})"


class MCPAdapter:
    def __init__(self, path=None, conf=None):
        if conf is None:
            path = path or os.environ.get("KHRAZ_MCP_CONFIG") or CONFIG_PATH
            with open(path, encoding="utf-8") as f:
                conf = json.load(f)
        self.conf = conf
        self.allowed = set(self.conf.get("allowed_tools") or [])
        self.writes = set(self.conf.get("write_tools") or [])
        self.tools = {}                 # real name -> {"description", "schema"}
        self.error = None
        self.ready = threading.Event()
        self._loop = None
        self._queue = None
        self._thread = None
        self._stopped = True

    # ---- состояние ----------------------------------------------------------------
    @property
    def connected(self):
        return self.ready.is_set() and not self.error and not self._stopped

    def status_text(self):
        if self._stopped:
            return "ВЫКЛ"
        if not self.ready.is_set():
            return "ПОДКЛЮЧЕНИЕ…"
        return "ОШИБКА" if self.error else f"ПОДКЛЮЧЁН · {len(self.tools)} ИНСТР."

    def is_write(self, name):
        return name in self.writes

    def real_name(self, safe_name):
        for n in self.tools:
            if _safe(n) == safe_name or n == safe_name:
                return n
        return None

    def tools_for_llm(self):
        return [{"type": "function", "function": {"name": _safe(n), "description": t["description"],
                                                  "parameters": t["schema"]}} for n, t in self.tools.items()]

    def accepts(self, name, param):
        return param in (self.tools.get(name, {}).get("schema", {}).get("properties") or {})

    # ---- запуск / остановка --------------------------------------------------------
    def start(self, wait=15):
        if self._thread and self._thread.is_alive():
            return self.connected
        self.ready.clear()
        self.error, self.tools, self._stopped = None, {}, False
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.ready.wait(wait)
        if not self.ready.is_set():
            self.error = "шлюз не ответил вовремя"
        return self.connected

    def stop(self):
        """Выход: больше никаких вызовов, процесс сервера завершается."""
        self._stopped = True
        if self._loop and self._queue:
            try:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
            except RuntimeError:
                pass
        if self._thread:
            self._thread.join(timeout=8)
        self._thread = None
        self.ready.clear()

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        finally:
            self._loop.close()
            self._loop = None

    async def _main(self):
        """Вся работа с сессией — внутри одной задачи (anyio требует выходить из контекстов в той же задаче)."""
        from contextlib import AsyncExitStack

        from mcp import ClientSession
        s = self.conf["server"]
        self._queue = asyncio.Queue()
        try:
            async with AsyncExitStack() as stack:
                read, write = await stack.enter_async_context(self._transport(s))
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    for t in listed.tools:
                        if self.allowed and t.name not in self.allowed:
                            continue          # инструменты вне белого списка модели не показываем
                        schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}
                        ann = getattr(t, "annotations", None)
                        self.tools[t.name] = {"description": t.description or "", "schema": schema,
                                              "read_only": bool(getattr(ann, "read_only_hint", None)
                                                                or getattr(ann, "readOnlyHint", None)),
                                              "destructive": bool(getattr(ann, "destructive_hint", None)
                                                                  or getattr(ann, "destructiveHint", None))}
                    self.ready.set()
                    while True:
                        req = await self._queue.get()
                        if req is None:
                            break
                        name, args, fut, timeout = req
                        try:
                            res = await asyncio.wait_for(session.call_tool(name, args), timeout)
                            fut.set_result(res)
                        except BaseException as e:      # noqa: BLE001 — передаём вызывающему
                            fut.set_exception(e if isinstance(e, Exception) else RuntimeError(str(e)))
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            self.ready.set()

    def _transport(self, s):
        """stdio (команда), http (Streamable HTTP) или sse — как в конфигурациях Claude Desktop и других клиентов."""
        kind = (s.get("type") or ("http" if s.get("url") else "stdio")).lower()
        if kind in ("http", "streamable-http", "streamable_http"):
            from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
            return streamable_http_client(s["url"], http_client=create_mcp_http_client(headers=s.get("headers") or None))
        if kind == "sse":
            from mcp.client.sse import sse_client
            return sse_client(s["url"], headers=s.get("headers") or None)
        from mcp import StdioServerParameters
        from mcp.client.stdio import get_default_environment, stdio_client
        env = get_default_environment()
        for k in s.get("env_passthrough", []):
            if os.environ.get(k):
                env[k] = os.environ[k]
        env.update({k: str(v) for k, v in (s.get("env") or {}).items()})
        cwd = s.get("cwd") or "."
        if not os.path.isabs(cwd):
            cwd = os.path.join(BASE, cwd)
        if not os.path.isdir(cwd):
            cwd = BASE
        command, args = s["command"], list(s.get("args", []))
        if s.get("bundled"):
            # наш шлюз: путь — от папки ХРАЗа (или внутри exe); в exe python нет — запускаем через сам khraz.exe
            args = [_bundled_path(a) if a.endswith(".py") else a for a in args]
            import sys
            if getattr(sys, "frozen", False):
                command, args = sys.executable, ["--run-py"] + args
            elif command in ("python", "python3"):
                command = sys.executable
        return stdio_client(StdioServerParameters(command=command, args=args, env=env, cwd=cwd),
                            errlog=open(os.devnull, "w"))

    # ---- вызов ------------------------------------------------------------------------
    def call(self, name, args, write=False):
        """Синхронный вызов инструмента. Для записи вызывать ТОЛЬКО после подтверждения кнопкой."""
        if not self.connected:
            return MCPResult(False, error=self.error or "MCP-сервер не подключён")
        if name not in self.tools:
            return MCPResult(False, error=f"инструмент {name} недоступен")
        timeout = float(self.conf.get("write_timeout_sec" if write else "read_timeout_sec", 30))
        fut = concurrent.futures.Future()
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, (name, args, fut, timeout))
            res = fut.result(timeout + 5)
        except Exception as e:
            # на записи результат неизвестен: сервер мог успеть выполнить операцию
            return MCPResult(False, error=f"{type(e).__name__}: {e}", unknown=write)
        return self._convert(res)

    @staticmethod
    def _convert(res):
        parts = []
        for c in getattr(res, "content", None) or []:
            t = getattr(c, "text", None)
            if t:
                parts.append(t)
        data = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
        text = "\n".join(parts) or (json.dumps(data, ensure_ascii=False) if data else "")
        if data is None and text:
            try:
                data = json.loads(text)
            except Exception:
                data = None
        is_err = bool(getattr(res, "is_error", False) or getattr(res, "isError", False))
        if not is_err and isinstance(data, dict) and data.get("error"):
            return MCPResult(False, text=text, data=data, error=str(data["error"]))
        return MCPResult(not is_err, text=text, data=data, error=text if is_err else "")
