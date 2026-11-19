"""Пользовательские команды (commands.json) и нечёткий поиск по фразам."""
import json
import os
import threading
import uuid

from rapidfuzz import fuzz

from config import DATA
from textutil import normalize

PATH = os.path.join(DATA, "commands.json")

EXAMPLES = [
    {"id": "work", "name": "Режим работы", "phrases": ["режим работы", "рабочий режим"],
     "steps": [{"type": "open_app", "param": "telegram"}, {"type": "open_app", "param": "code"},
               {"type": "volume", "param": "30"}],
     "reply": "Режим работы включён"},
    {"id": "game", "name": "Игровой режим", "phrases": ["игровой режим", "пора играть"],
     "steps": [{"type": "open_app", "param": "steam"}, {"type": "open_app", "param": "discord"},
               {"type": "volume", "param": "60"}],
     "reply": "Приятной игры"},
]


class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.items = []
        self.load()

    def load(self):
        if os.path.exists(PATH):
            with open(PATH, encoding="utf-8") as f:
                self.items = json.load(f)
        else:
            self.items = [dict(x) for x in EXAMPLES]
            self.save()

    def save(self):
        with self.lock:
            with open(PATH, "w", encoding="utf-8") as f:
                json.dump(self.items, f, ensure_ascii=False, indent=2)

    def add(self, name, phrases, steps, reply=""):
        cmd = {"id": uuid.uuid4().hex[:8], "name": name, "phrases": phrases, "steps": steps, "reply": reply}
        self.items.append(cmd)
        self.save()
        return cmd

    def upsert(self, cmd):
        for i, c in enumerate(self.items):
            if c["id"] == cmd["id"]:
                self.items[i] = cmd
                break
        else:
            self.items.append(cmd)
        self.save()

    def delete(self, cmd_id):
        self.items = [c for c in self.items if c["id"] != cmd_id]
        self.save()

    def match(self, text, threshold=86):
        t = normalize(text)
        best, score = None, 0
        for c in self.items:
            for p in c["phrases"]:
                s = fuzz.ratio(t, normalize(p))
                if s > score:
                    best, score = c, s
        return best if score >= threshold else None

    def find_by_name(self, text, threshold=75):
        t = normalize(text)
        best, score = None, 0
        for c in self.items:
            for p in [c["name"]] + c["phrases"]:
                s = fuzz.WRatio(t, normalize(p))
                if s > score:
                    best, score = c, s
        return best if score >= threshold else None
