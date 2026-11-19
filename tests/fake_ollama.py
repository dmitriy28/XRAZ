"""Поддельный сервер Ollama для тестов: /api/version, /api/tags, /api/ps, /api/generate (выгрузка),
/api/chat (поток и без), /api/embed (векторы «мешок слов» — похожие фразы ближе)."""
import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeOllama:
    def __init__(self, installed=("qwen3.5:9b", "gpt-oss:20b", "bge-m3:latest")):
        self.installed = list(installed)
        self.loaded = []
        self.unloaded = []
        self.chats = []          # (model, body)
        self.reply = "Ответ модели."
        self.tool_calls = []     # очередь ответов с инструментами: [(name, args)] на один вызов
        srv = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _json(self, code, data):
                b = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                if self.path == "/api/version":
                    return self._json(200, {"version": "0.12.6"})
                if self.path == "/api/tags":
                    return self._json(200, {"models": [{"name": m} for m in srv.installed]})
                if self.path == "/api/ps":
                    return self._json(200, {"models": [{"name": m} for m in srv.loaded]})
                self._json(404, {})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                model = body.get("model", "")
                if self.path == "/api/generate":
                    if body.get("keep_alive") == 0 and model in srv.loaded:
                        srv.loaded.remove(model)
                        srv.unloaded.append(model)
                    return self._json(200, {"done": True})
                if self.path == "/api/embed":
                    if not any(m.startswith(model) for m in srv.installed):
                        return self._json(404, {"error": f"model '{model}' not found"})
                    return self._json(200, {"embeddings": [bow(t) for t in body.get("input", [])]})
                if self.path == "/api/chat":
                    if not any(m == model or m.startswith(model + ":") for m in srv.installed):
                        return self._json(404, {"error": f"model '{model}' not found"})
                    if model not in srv.loaded:
                        srv.loaded.append(model)
                    srv.chats.append((model, body))
                    msg = {"role": "assistant", "content": srv.reply}
                    if body.get("tools") and srv.tool_calls:
                        calls = srv.tool_calls.pop(0)
                        if calls:
                            msg = {"role": "assistant", "content": "",
                                   "tool_calls": [{"function": {"name": n, "arguments": a}} for n, a in calls]}
                    if not body.get("stream"):
                        return self._json(200, {"message": msg, "done": True, "done_reason": "stop"})
                    self.send_response(200)
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    parts = [{"message": {"thinking": "скрытое рассуждение"}}] if "gpt-oss" in model else []
                    parts += [{"message": {"content": w + " "}} for w in srv.reply.split()]
                    parts.append({"message": {"content": ""}, "done": True, "done_reason": "stop"})
                    for p in parts:
                        line = (json.dumps(p) + "\n").encode()
                        self.wfile.write(f"{len(line):x}\r\n".encode() + line + b"\r\n")
                    self.wfile.write(b"0\r\n\r\n")
                    return
                self._json(404, {})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


STOP = {"и", "в", "на", "по", "что", "у", "меня", "мне", "я", "с", "о", "про", "the"}


def bow(text, dim=256):
    """Вектор «мешок основ слов»: общие корни → высокая косинусная близость."""
    v = [0.0] * dim
    for w in re.findall(r"\w+", text.lower()):
        if w in STOP or len(w) < 3:
            continue
        stem = w[:5]
        v[int(hashlib.md5(stem.encode()).hexdigest(), 16) % dim] += 1.0
    return v
