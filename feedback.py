"""Обучение на оценках: 👍 — ответ становится образцом для похожих вопросов, 👎 — примером «так не надо».
Модель не переобучается: образцы подмешиваются в подсказку (few-shot) по сходству вопроса (bge-m3,
без неё — по словам). Хранится в feedback.json; оценку можно снять повторным нажатием."""
import json
import os
import threading
import time

from rapidfuzz import fuzz

from config import DATA
from memory import _cos
from textutil import normalize

PATH = os.path.join(DATA, "feedback.json")
LIMIT = 400


class Feedback:
    def __init__(self, llm=None, path=None):
        self.llm, self.path = llm, path or PATH
        self.lock = threading.Lock()
        self.items = []
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.items = json.load(f).get("items", [])
            except Exception:
                self.items = []

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"items": self.items}, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def _vec(self, text):
        if not self.llm:
            return None
        try:
            v = self.llm.embed([text])
            return [round(x, 5) for x in v[0]] if v else None
        except Exception:
            return None

    def rate(self, msg_id, question, answer, vote, note=""):
        """vote: 1 или -1; та же оценка повторно — снимает её. Возвращает итоговую оценку (0 — снята)."""
        with self.lock:
            old = next((x for x in self.items if x["msg_id"] == msg_id), None)
            if old and old["vote"] == vote:
                self.items.remove(old)
                self._save()
                return 0
            if old:
                self.items.remove(old)
        item = {"msg_id": msg_id, "q": question[:1500], "a": answer[:3000], "vote": vote, "note": note[:300],
                "ts": time.strftime("%Y-%m-%d %H:%M"), "vec": self._vec(question[:1500])}
        with self.lock:
            self.items.append(item)
            self.items = self.items[-LIMIT:]
            self._save()
        return vote

    def similar(self, question, k=2, min_score=0.62):
        """(хорошие, плохие) — образцы для похожего вопроса."""
        if not self.items:
            return [], []
        qv = self._vec(question) if any(x.get("vec") for x in self.items) else None
        nq = normalize(question)
        scored = []
        for x in self.items:
            if qv and x.get("vec"):
                s = _cos(qv, x["vec"])
            else:
                s = fuzz.token_set_ratio(nq, normalize(x["q"])) / 100 * 0.85
            if s >= min_score:
                scored.append((s, x))
        scored.sort(key=lambda z: z[0], reverse=True)
        good = [x for _, x in scored if x["vote"] > 0][:k]
        bad = [x for _, x in scored if x["vote"] < 0][:k]
        return good, bad

    def prompt_block(self, question):
        good, bad = self.similar(question)
        if not good and not bad:
            return ""
        out = "\n\n# Опыт по похожим вопросам (оценки майора)"
        for x in good:
            out += f"\nУДАЧНЫЙ ответ на «{x['q'][:200]}»:\n{x['a'][:700]}"
        for x in bad:
            out += f"\nНЕУДАЧНЫЙ ответ на «{x['q'][:200]}» (так не отвечать{': ' + x['note'] if x['note'] else ''}):\n{x['a'][:400]}"
        return out + "\nОриентируйся на удачные по форме и тону; ошибок неудачных не повторяй."

    def stats(self):
        return sum(1 for x in self.items if x["vote"] > 0), sum(1 for x in self.items if x["vote"] < 0)
