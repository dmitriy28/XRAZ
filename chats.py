"""Чаты: история разговоров отдельно от долговременной памяти. Каждый чат — файл chats/<id>.json.
Можно создать новый, переключиться, переименовать, удалить один или очистить все."""
import json
import os
import threading
import time
import uuid

from config import DATA

DIR = os.path.join(DATA, "chats")


class Chats:
    def __init__(self, folder=None):
        self.dir = folder or DIR
        os.makedirs(self.dir, exist_ok=True)
        self.lock = threading.Lock()
        self.current = None
        items = self.list()
        self.current = self._read(items[0]["id"]) if items else self.new()

    # ---- файлы ---------------------------------------------------------------------
    def _path(self, cid):
        return os.path.join(self.dir, f"{cid}.json")

    def _read(self, cid):
        with open(self._path(cid), encoding="utf-8") as f:
            return json.load(f)

    def _write(self, chat):
        tmp = self._path(chat["id"]) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(chat, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._path(chat["id"]))

    # ---- операции ------------------------------------------------------------------
    def list(self):
        out = []
        for name in os.listdir(self.dir):
            if not name.endswith(".json"):
                continue
            try:
                c = self._read(name[:-5])
                out.append({"id": c["id"], "title": c.get("title") or "Без названия", "updated": c.get("updated", ""),
                            "count": len(c.get("messages", []))})
            except Exception:
                continue
        out.sort(key=lambda c: c["updated"], reverse=True)
        return out

    def new(self):
        if self.current is not None and not self.current["messages"]:
            return self.current               # пустой чат не плодим
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        chat = {"id": time.strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:4], "title": "", "created": now,
                "updated": now, "messages": []}
        with self.lock:
            self.current = chat
            self._write(chat)
        return chat

    def open(self, cid):
        with self.lock:
            self.current = self._read(cid)
        return self.current

    @property
    def messages(self):
        return self.current["messages"]

    def history(self):
        """Сообщения для модели: только роль и текст."""
        return [{"role": m["role"], "content": m["content"]} for m in self.current["messages"]]

    def add(self, role, content, meta=None):
        with self.lock:
            msg = {"id": uuid.uuid4().hex[:10], "role": role, "content": content, "ts": time.strftime("%H:%M")}
            if meta:
                msg["meta"] = meta
            self.current["messages"].append(msg)
            if not self.current.get("title") and role == "user":
                t = content.strip().replace("\n", " ")
                self.current["title"] = t[:48] + ("…" if len(t) > 48 else "")
            self.current["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._write(self.current)
        return msg

    def find(self, msg_id):
        """(вопрос пользователя, сообщение ассистента) по id ответа — для оценки 👍/👎."""
        msgs = self.current["messages"]
        for i, m in enumerate(msgs):
            if m.get("id") == msg_id and m["role"] == "assistant":
                q = next((x["content"] for x in reversed(msgs[:i]) if x["role"] == "user"), "")
                return q, m
        return None, None

    def set_meta(self, msg_id, **kw):
        with self.lock:
            for m in self.current["messages"]:
                if m.get("id") == msg_id:
                    m.setdefault("meta", {}).update(kw)
                    self._write(self.current)
                    return True
        return False

    def rename(self, cid, title):
        c = self._read(cid)
        c["title"] = title.strip()[:80]
        self._write(c)
        if self.current["id"] == cid:
            self.current["title"] = c["title"]

    def clear_current(self):
        with self.lock:
            self.current["messages"] = []
            self._write(self.current)

    def delete(self, cid):
        try:
            os.remove(self._path(cid))
        except FileNotFoundError:
            pass
        if self.current and self.current["id"] == cid:
            self.current = None
            items = self.list()
            self.current = self._read(items[0]["id"]) if items else self.new()

    def delete_all(self):
        for c in self.list():
            try:
                os.remove(self._path(c["id"]))
            except FileNotFoundError:
                pass
        self.current = None
        return self.new()
