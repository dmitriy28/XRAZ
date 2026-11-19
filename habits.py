"""Привычки: ХРАЗ замечает повторы и сам предлагает «сделать командой?».

Учитываются успешно выполненные инструменты (одинаковые инструмент + аргументы) и встроенные действия.
На третьем повторе за 30 дней — одно предложение; отказ запоминается, повторно не предлагает."""
import json
import os
import threading
import time

from config import DATA

PATH = os.path.join(DATA, "habits.json")
THRESHOLD, WINDOW_DAYS = 3, 30
SKIP_TOOLS = {"set_timer", "set_reminder", "create_note", "create_file", "memory_save", "memory_search", "find_file",
              "read_document", "web_search", "kb_search"}       # разовые по смыслу — командой не делаем


def key_of(tool, args):
    return tool + " " + json.dumps(args, ensure_ascii=False, sort_keys=True)


class Habits:
    def __init__(self, path=None):
        self.path = path or PATH
        self.lock = threading.Lock()
        self.d = {"seen": {}, "declined": [], "offered": []}
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.d.update(json.load(f))
            except Exception:
                pass

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.d, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def record(self, tool, args, phrase):
        """Отметить выполнение. Возвращает предложение {key, tool, args, phrase, count} или None."""
        if tool in SKIP_TOOLS or tool.startswith("mcp_"):
            return None
        k = key_of(tool, args)
        now = time.time()
        with self.lock:
            rec = self.d["seen"].setdefault(k, {"tool": tool, "args": args, "times": [], "phrases": []})
            rec["times"] = [t for t in rec["times"] if now - t < WINDOW_DAYS * 86400] + [now]
            rec["phrases"] = (rec["phrases"] + [phrase])[-5:]
            self._save()
            if len(rec["times"]) >= THRESHOLD and k not in self.d["declined"] and k not in self.d["offered"]:
                self.d["offered"].append(k)
                self._save()
                return {"key": k, "tool": tool, "args": args, "phrase": min(rec["phrases"], key=len),
                        "count": len(rec["times"])}
        return None

    def decline(self, k):
        with self.lock:
            if k not in self.d["declined"]:
                self.d["declined"].append(k)
                self._save()
