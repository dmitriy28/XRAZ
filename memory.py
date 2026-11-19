"""Долговременная память ХРАЗа — отдельно от истории чатов (chats.py).

- Сохраняется только то, что пользователь явно попросил («запомни…») или подтвердил (карточка / «да»).
- В разговор подмешиваются не все записи, а подходящие: поиск по смыслу через bge-m3 (Ollama /api/embed);
  если модели нет — нечёткий поиск по словам. Предпочтения (kind=preference) подмешиваются всегда.
- Каждую запись можно посмотреть и удалить (вкладка «Память»), есть полная очистка.
Хранится локально в memory.json; старый archive.json переносится автоматически."""
import json
import math
import os
import threading
import time
import uuid

from rapidfuzz import fuzz

from config import DATA
from textutil import normalize

PATH = os.path.join(DATA, "memory.json")
OLD_ARCHIVE = os.path.join(DATA, "archive.json")
LIMIT = 500
MIN_SCORE = 0.45          # косинусная близость bge-m3, ниже — «не про это»


def _cos(a, b):
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db = math.sqrt(sum(y * y for y in b)) or 1.0
    return num / (da * db)


class Memory:
    def __init__(self, llm=None, path=None):
        self.llm = llm
        self.path = path or PATH
        self.lock = threading.Lock()
        self.items = []
        self.embed_ok = None          # None — ещё не пробовали, False — bge-m3 недоступна
        self._load()

    # ---- хранение ---------------------------------------------------------------
    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.items = json.load(f).get("items", [])
                return
            except Exception:
                self.items = []
        if self.path == PATH and os.path.exists(OLD_ARCHIVE):      # перенос старого архива
            try:
                with open(OLD_ARCHIVE, encoding="utf-8") as f:
                    for text in json.load(f):
                        self.items.append(self._new(text, "fact", "архив"))
                self._save()
            except Exception:
                pass

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "items": self.items}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    @staticmethod
    def _new(text, kind, source):
        return {"id": uuid.uuid4().hex[:8], "text": text, "kind": kind, "source": source,
                "created": time.strftime("%Y-%m-%d %H:%M")}

    @property
    def notes(self):
        """Совместимость: тексты всех записей."""
        return [m["text"] for m in self.items]

    # ---- эмбеддинги -------------------------------------------------------------
    def _embed(self, texts):
        if not self.llm:
            self.embed_ok = False
            return None
        if self.embed_ok is False or not texts:
            return None
        try:
            vecs = self.llm.embed(texts)
            self.embed_ok = bool(vecs)
            return vecs or None
        except Exception:
            self.embed_ok = False         # bge-m3 нет — работаем нечётким поиском
            return None

    def _fill_vectors(self):
        missing = [m for m in self.items if not m.get("vec")]
        if not missing:
            return
        vecs = self._embed([m["text"] for m in missing])
        if vecs and len(vecs) == len(missing):
            for m, v in zip(missing, vecs):
                m["vec"] = [round(x, 5) for x in v]
            with self.lock:
                self._save()

    # ---- операции ------------------------------------------------------------------
    def add(self, text, kind="fact", source="по просьбе"):
        text = (text or "").strip().rstrip(".")
        if not text:
            raise ValueError("пустая запись")
        text = text[:1].upper() + text[1:]
        with self.lock:
            for m in self.items:
                if fuzz.ratio(normalize(text), normalize(m["text"])) > 90:
                    return m
            item = self._new(text, kind, source)
            self.items.append(item)
            self.items = self.items[-LIMIT:]
        v = self._embed([text])
        if v:
            item["vec"] = [round(x, 5) for x in v[0]]
        with self.lock:
            self._save()
        return item

    def delete(self, item_id):
        with self.lock:
            before = len(self.items)
            self.items = [m for m in self.items if m["id"] != item_id]
            if len(self.items) != before:
                self._save()
                return True
        return False

    def clear(self):
        with self.lock:
            self.items = []
            self._save()

    def search(self, query, k=6, min_score=MIN_SCORE):
        """[(запись, близость 0..1)] — по смыслу (bge-m3) или по словам, если bge-m3 недоступна."""
        if not self.items or not (query or "").strip():
            return []
        self._fill_vectors()
        q = self._embed([query]) if self.embed_ok is not False else None
        scored = []
        if q:
            for m in self.items:
                if m.get("vec"):
                    scored.append((m, _cos(q[0], m["vec"])))
        else:
            nq = normalize(query)
            for m in self.items:
                scored.append((m, fuzz.token_set_ratio(nq, normalize(m["text"])) / 100 * 0.8))
        scored = [x for x in scored if x[1] >= min_score]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    def relevant(self, query, k=6):
        """Что подмешать в разговор: все предпочтения + подходящие факты."""
        prefs = [m for m in self.items if m.get("kind") == "preference"][-10:]
        facts = [m for m, _ in self.search(query, k) if m.get("kind") != "preference"]
        return prefs + facts

    def find_one(self, query):
        """Для «забудь …»: самая похожая запись (или None)."""
        res = self.search(query, k=1, min_score=0.5)
        if res:
            return res[0][0]
        nq = normalize(query)
        best = max(self.items, key=lambda m: fuzz.partial_ratio(nq, normalize(m["text"])), default=None)
        if best and fuzz.partial_ratio(nq, normalize(best["text"])) >= 70:
            return best
        return None


Archive = Memory          # старое имя для совместимости
