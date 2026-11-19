"""Подтверждения опасных действий.

Каждая операция «замораживается»: параметры сериализуются один раз, от них считается SHA-256, и при
подтверждении выполняется ровно то, что было показано (хеш сверяется). Подтверждение одноразовое и
истекает. Для изменений через сторонние MCP-серверы (kind="mcp") голосовое «да» не принимается никогда —
только кнопка в окне. Текст модели, голос и данные из инструментов подтверждением не являются."""
import hashlib
import json
import threading
import time
import uuid


class Op:
    def __init__(self, kind, payload, title, preview, voice_ok, ttl):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.frozen = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        self.hash = hashlib.sha256(self.frozen.encode()).hexdigest()
        self.title, self.preview = title, preview
        self.voice_ok = voice_ok and kind != "mcp"
        self.expires = time.time() + ttl
        self.state = "pending"            # pending → approved/rejected/expired/cancelled

    @property
    def payload(self):
        return json.loads(self.frozen)


class Confirmations:
    def __init__(self, ttl=300):
        self.ttl = ttl
        self.ops = {}
        self.lock = threading.Lock()

    def create(self, kind, payload, title, preview, voice_ok=False):
        op = Op(kind, payload, title, preview, voice_ok, self.ttl)
        with self.lock:
            self.ops[op.id] = op
        return op

    def take(self, op_id, via):
        """Проверить и «погасить» подтверждение. Возвращает (op | None, причина отказа)."""
        with self.lock:
            op = self.ops.get(op_id)
            if not op:
                return None, "операция не найдена"
            if op.state != "pending":
                return None, f"операция уже {_STATE.get(op.state, op.state)}"
            if time.time() > op.expires:
                op.state = "expired"
                return None, "время подтверждения истекло — подготовьте операцию заново"
            if via != "ui" and not op.voice_ok:
                return None, "такие операции подтверждаются только кнопкой в окне"
            if hashlib.sha256(op.frozen.encode()).hexdigest() != op.hash:
                op.state = "cancelled"
                return None, "параметры изменились после предпросмотра — нужна новая подготовка"
            op.state = "approved"
            return op, ""

    def reject(self, op_id):
        with self.lock:
            op = self.ops.get(op_id)
            if op and op.state == "pending":
                op.state = "rejected"
                return op
        return None

    def latest_pending(self, voice_only=False):
        with self.lock:
            pend = [o for o in self.ops.values() if o.state == "pending" and time.time() <= o.expires
                    and (o.voice_ok or not voice_only)]
        return pend[-1] if pend else None

    def cancel_all(self):
        with self.lock:
            gone = [o for o in self.ops.values() if o.state == "pending"]
            for o in gone:
                o.state = "cancelled"
        return gone


_STATE = {"approved": "подтверждена", "rejected": "отклонена", "expired": "просрочена", "cancelled": "отменена"}
