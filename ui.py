"""Окно ХРАЗа (PyQt6): ретрофутуризм Предприятия 3826 — тёмный металл, советский красный, латунь.
Чат — веб-страница (WebEngine) с markdown и формулами KaTeX. Без WebEngine — простой текстовый чат."""
import json
import math
import os
import random
import re
import sys
import threading

from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (QAction, QActionGroup, QBrush, QColor, QFont, QFontDatabase, QIcon, QKeySequence, QLinearGradient, QPainter, QShortcut,
                         QPainterPath, QPen, QPixmap, QRadialGradient)
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
                             QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                             QSizeGrip, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout,
                             QWidget)

import actions
import config
import persona

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")

try:
    from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    HAS_WEB = True

    class ChatPage(QWebEnginePage):
        """Перехват кнопок карточек подтверждения: khraz://approve/<id>, khraz://reject/<id>.
        Только живой клик пользователя (тип навигации LinkClicked) — скрипт со страницы так не подтвердит."""
        def __init__(self, on_action, parent=None):
            super().__init__(parent)
            self.on_action = on_action

        def acceptNavigationRequest(self, url, nav_type, is_main):
            if url.scheme() == "khraz":
                if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                    self.on_action(url.host(), url.path().strip("/"))
                return False
            if url.scheme() in ("http", "https"):
                import webbrowser
                webbrowser.open(url.toString())
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main)

except Exception:
    HAS_WEB = False

C = dict(bg="#0e0b0a", panel="#17110f", panel2="#1e1613", line="#3a2a22", red="#d7262e", red_dim="#7d1a1e",
         brass="#c9a24a", brass_dim="#6e5a2e", cream="#eadfc8", muted="#8f8070", amber="#ff9d2e", steel="#9fb3c8")

STYLE = """
* {{ font-family: 'Segoe UI'; font-size: 13px; color: {cream}; }}
QMainWindow, QWidget {{ background: {bg}; }}
QLabel, QCheckBox {{ background: transparent; }}
QWidget#side QWidget {{ background: transparent; }}
QWidget#side QPushButton {{ background: {panel2}; }}
QWidget#side {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #140f0d, stop:1 {bg});
               border-right: 1px solid {line}; }}
QTabWidget::pane {{ border: 1px solid {line}; background: {bg}; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 9px 18px; color: {muted}; font-family: 'Oswald'; font-size: 13px;
               letter-spacing: 3px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {cream}; border-bottom: 2px solid {red}; }}
QTabBar::tab:hover {{ color: {brass}; }}
QLineEdit, QPlainTextEdit, QComboBox, QTextBrowser, QListWidget, QTableWidget {{
  background: {panel}; border: 1px solid {line}; border-radius: 3px; padding: 6px; selection-background-color: {red_dim}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 1px solid {brass_dim}; }}
QComboBox QAbstractItemView {{ background: {panel}; border: 1px solid {line}; }}
QPushButton {{ background: {panel2}; border: 1px solid {line}; border-radius: 3px; padding: 7px 14px;
              font-family: 'Oswald'; letter-spacing: 2px; }}
QPushButton:hover {{ border-color: {brass_dim}; color: #fff3dc; }}
QPushButton#primary {{ background: {red}; border: 1px solid {red}; color: #fff; }}
QPushButton#primary:hover {{ background: #ef3a42; }}
QHeaderView::section {{ background: {panel}; border: none; color: {muted}; padding: 5px; font-family: 'Oswald';
                        letter-spacing: 2px; }}
QListWidget::item {{ padding: 6px; border-bottom: 1px solid #221915; }}
QListWidget::item:selected {{ background: #2a1b17; color: #fff3dc; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {brass_dim}; background: {panel}; }}
QCheckBox::indicator:checked {{ background: {red}; border-color: {red}; }}
QScrollBar:vertical {{ background: transparent; width: 8px; }}
QScrollBar::handle:vertical {{ background: {line}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QLabel#h {{ font-family: 'Oswald'; letter-spacing: 3px; color: {brass}; font-size: 12px; }}
QLabel#hint {{ color: {muted}; }}
""".format(**C)

STATE_TEXT = {"listening": "ЖДУ ПРИКАЗА", "idle": "ЖДУ ПРИКАЗА", "thinking": "АНАЛИЗ…", "speaking": "ДОКЛАДЫВАЮ",
              "off": "МИКРОФОН ОТКЛЮЧЁН"}


class PromptEdit(QPlainTextEdit):
    """Поле ввода приказа: многострочное (textarea), растёт по мере набора до max_lines строк, дальше — прокрутка.
    Enter — передать, Shift+Enter — новая строка. Совместимо с QLineEdit: text(), setText(), clear(), setPlaceholderText()."""
    submitted = pyqtSignal()
    focused = pyqtSignal(bool)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.focused.emit(True)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.focused.emit(False)

    def __init__(self, placeholder="", max_lines=6, pad=12):
        super().__init__()
        self.max_lines, self.pad = max_lines, pad
        self.setPlaceholderText(placeholder)
        self.setTabChangesFocus(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.document().documentLayout().documentSizeChanged.connect(lambda *_: self._fit())
        self._fit()

    def text(self):
        return self.toPlainText()

    def setText(self, t):
        self.setPlainText(t)

    def _fit(self):
        lines = max(1, min(self.max_lines, int(self.document().size().height()) or 1))
        h = lines * self.fontMetrics().lineSpacing() + 2 * int(self.document().documentMargin()) + 2 * self.frameWidth() + self.pad
        self.setFixedHeight(h)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if self.document().size().height() > self.max_lines
                                        else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def showEvent(self, e):
        super().showEvent(e)
        self._fit()                       # рамка и отступы из стиля известны только после применения стиля

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self._fit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(e)


class Bridge(QObject):
    """Мозг дёргает эти методы из своих потоков — Qt получает сигналы в главном потоке."""
    sig_status = pyqtSignal(str)
    sig_partial = pyqtSignal(str)
    sig_user = pyqtSignal(str)
    sig_assistant = pyqtSignal(str)
    sig_start = pyqtSignal()
    sig_token = pyqtSignal(str)
    sig_done = pyqtSignal(str)
    sig_cmds = pyqtSignal()
    sig_confirm = pyqtSignal(str, str, str, bool)
    sig_resolve = pyqtSignal(str, str)
    sig_model = pyqtSignal(str, str)
    sig_action = pyqtSignal(str)
    sig_more = pyqtSignal()
    sig_chat = pyqtSignal()
    sig_memory = pyqtSignal()
    sig_ollama = pyqtSignal(bool, str)
    sig_report = pyqtSignal(str)
    sig_tool_start = pyqtSignal(str, str, str)
    sig_tool_end = pyqtSignal(str, bool, str)
    sig_file = pyqtSignal(str)
    sig_hub = pyqtSignal(str)
    sig_mic = pyqtSignal()
    sig_alert = pyqtSignal(str)
    sig_rateable = pyqtSignal(str)
    sig_rated = pyqtSignal(str, int)
    sig_kb = pyqtSignal()
    sig_hotkey = pyqtSignal()

    def status(self, s): self.sig_status.emit(s)
    def model_info(self, model, reason): self.sig_model.emit(model, reason)
    def action(self, text): self.sig_action.emit(text)
    def offer_more(self): self.sig_more.emit()
    def chat_switched(self): self.sig_chat.emit()
    def memory_changed(self): self.sig_memory.emit()
    def tool_start(self, cid, name, args): self.sig_tool_start.emit(cid, name, args)
    def tool_end(self, cid, ok, result): self.sig_tool_end.emit(cid, ok, result)
    def file_ready(self, path): self.sig_file.emit(path)
    def hub_status(self, text): self.sig_hub.emit(text)
    def alert(self, text): self.sig_alert.emit(text)
    def rateable(self, msg_id): self.sig_rateable.emit(msg_id)
    def rated(self, msg_id, vote): self.sig_rated.emit(msg_id, vote)
    def kb_changed(self): self.sig_kb.emit()
    def partial(self, t): self.sig_partial.emit(t)
    def user(self, t): self.sig_user.emit(t)
    def assistant(self, t): self.sig_assistant.emit(t)
    def assistant_start(self): self.sig_start.emit()
    def assistant_token(self, tok): self.sig_token.emit(tok)
    def assistant_done(self, text): self.sig_done.emit(text)
    def commands_changed(self): self.sig_cmds.emit()
    def confirm(self, op_id, title, md, voice_ok): self.sig_confirm.emit(op_id, title, md, voice_ok)
    def resolve(self, op_id, text): self.sig_resolve.emit(op_id, text)


class PolymerEye(QWidget):
    """Портрет ХРАЗа в латунном «иллюминаторе»: обод с делениями, вращающиеся сегменты и подсветка
    цветом состояния (слушает / думает / говорит)."""

    def __init__(self, portrait=None):
        super().__init__()
        self.setMinimumSize(200, 200)
        self.state, self.t, self.energy = "idle", 0.0, 0.0
        self.portrait = QPixmap(portrait) if portrait and os.path.exists(portrait) else None
        tm = QTimer(self)
        tm.timeout.connect(self._tick)
        tm.start(33)

    def _tick(self):
        self.t += 0.033
        target = {"speaking": 1.0, "thinking": 0.6, "listening": 0.25, "idle": 0.2}.get(self.state, 0.1)
        self.energy += (target - self.energy) * 0.08
        self.update()

    def _color(self):
        return QColor({"thinking": C["amber"], "speaking": C["red"],
                       "off": "#4a3f38"}.get(self.state, C["red"]))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        R = min(w, h) / 2 - 8
        col = self._color()
        t, en = self.t, self.energy
        # латунный обод с делениями
        rim = QRadialGradient(cx, cy, R)
        rim.setColorAt(0.86, QColor("#1a1210"))
        rim.setColorAt(0.93, QColor(C["brass_dim"]))
        rim.setColorAt(0.97, QColor(C["brass"]))
        rim.setColorAt(1.0, QColor("#3b2d16"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(rim))
        p.drawEllipse(QPointF(cx, cy), R, R)
        p.setPen(QPen(QColor("#2a1f12"), 1.4))
        for i in range(60):
            a = i * math.pi / 30
            r1 = R * (0.875 if i % 5 else 0.84)
            p.drawLine(QPointF(cx + math.cos(a) * r1, cy + math.sin(a) * r1),
                       QPointF(cx + math.cos(a) * R * 0.905, cy + math.sin(a) * R * 0.905))
        # вращающиеся сегменты (быстрее, когда думает)
        speed = {"thinking": 2.4, "speaking": 1.0}.get(self.state, 0.35)
        pen = QPen(QColor(col.red(), col.green(), col.blue(), 150), 3)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        rr = R * 0.79
        for k in range(3):
            start = (t * 60 * speed + k * 120) * 16
            p.drawArc(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr), int(start), 70 * 16)
        # портрет с подсветкой состояния и полосой развёртки
        r = R * 0.72
        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), r, r)
        p.save()
        p.setClipPath(clip)
        if self.portrait:
            p.drawPixmap(QRectF(cx - r, cy - r, 2 * r, 2 * r), self.portrait, QRectF(self.portrait.rect()))
        else:
            p.fillRect(QRectF(cx - r, cy - r, 2 * r, 2 * r), QColor("#1b1412"))
        p.fillRect(QRectF(cx - r, cy - r, 2 * r, 2 * r), QColor(col.red(), col.green(), col.blue(), int(25 + 70 * en)))
        y = cy - r + (t * 40 % (2 * r))
        band = QLinearGradient(0, y - 18, 0, y + 18)
        band.setColorAt(0, QColor(255, 255, 255, 0))
        band.setColorAt(0.5, QColor(255, 235, 220, int(30 + 50 * en)))
        band.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(cx - r, y - 18, 2 * r, 36), QBrush(band))
        p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), int(140 + 110 * en)), 2.5))
        p.drawEllipse(QPointF(cx, cy), r, r)


class CompactWindow(QWidget):
    """Компактный «голографический» режим: маленькое окно поверх всех окон — портрет пульсирует, ответы идут
    субтитрами, внизу строка приказа. Перетаскивается мышью; Esc — спрятать; двойной щелчок — большое окно."""

    def __init__(self, main):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.main = main
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("ХРАЗ")
        self.resize(380, 520)
        self.setMinimumSize(320, 360)
        self._drag = None
        self._live = ""
        self._upd_pending = False
        box = QWidget(self)
        box.setObjectName("holo")
        # своё оформление целиком: стили главного окна на отдельное окно не распространяются
        box.setStyleSheet(f"""
            QWidget#holo {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(24,16,14,0.96),
                            stop:1 rgba(12,9,8,0.96)); border: 1px solid {C['red_dim']}; border-radius: 16px; }}
            QWidget {{ font-family: 'Segoe UI'; color: {C['cream']}; }}
            QLabel {{ background: transparent; }}
            QPushButton#ico {{ background: transparent; border: none; border-radius: 13px; color: {C['muted']};
                              font-size: 13px; padding: 0; }}
            QPushButton#ico:hover {{ background: rgba(255,255,255,0.07); color: {C['cream']}; }}
            QWidget#bar {{ background: rgba(0,0,0,0.35); border: 1px solid {C['line']}; border-radius: 19px; }}
            QWidget#bar:focus-within {{ border-color: {C['brass_dim']}; }}
            QLineEdit, QPlainTextEdit {{ background: transparent; border: none; padding: 0 4px; font-size: 13px;
                        color: {C['cream']}; selection-background-color: {C['red_dim']}; }}
            QPushButton#send {{ background: {C['red']}; border: none; border-radius: 14px; color: #fff;
                               font-size: 13px; padding: 0; }}
            QPushButton#send:hover {{ background: #ef3a42; }}
            QPushButton#stop {{ background: transparent; border: 1px solid {C['red_dim']}; border-radius: 14px;
                               color: {C['red']}; font-size: 11px; padding: 0; }}
            QPushButton#stop:hover {{ border-color: {C['red']}; background: rgba(215,38,46,0.15); }}
            QTextBrowser#sub {{ background: transparent; border: none; color: {C['cream']}; font-size: 13.5px;
                               selection-background-color: {C['red_dim']}; }}
            QScrollBar:vertical {{ background: transparent; width: 7px; margin: 2px 0; }}
            QScrollBar::handle:vertical {{ background: {C['line']}; border-radius: 3px; min-height: 28px; }}
            QScrollBar::handle:vertical:hover {{ background: {C['brass_dim']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}""")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(box)
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 12, 12, 14)
        v.setSpacing(8)
        # шапка: имя, статус-точка, развернуть, закрыть
        top = QHBoxLayout()
        top.setSpacing(6)
        cap = QLabel("ХРАЗ")
        cap.setStyleSheet(f"font-family:'Russo One'; font-size:15px; color:{C['red']}; letter-spacing:4px;")
        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color:{C['red']}; font-size:9px;")
        self.state_lbl = QLabel("ЖДУ ПРИКАЗА")
        self.state_lbl.setStyleSheet(f"font-family:'Oswald'; font-size:10px; letter-spacing:3px; color:{C['muted']};")
        self.btn_eye = IconButton("down", "Спрятать портрет — больше места для ответа", (26, 26))
        self.btn_eye.clicked.connect(self._toggle_eye)
        big = IconButton("expand", "Открыть большое окно", (26, 26))
        big.clicked.connect(lambda: (self.main.showNormal(), self.main.activateWindow()))
        close = IconButton("close", "Спрятать (Esc)", (26, 26), hover=C["red"])
        close.clicked.connect(self.hide)
        top.addWidget(cap)
        top.addSpacing(6)
        top.addWidget(self.dot)
        top.addWidget(self.state_lbl)
        top.addStretch()
        top.addWidget(self.btn_eye)
        top.addWidget(big)
        top.addWidget(close)
        # портрет (сжимается, когда нужно больше места для текста)
        self.eye = PolymerEye(os.path.join(ASSETS, "img", "khraz_portrait.png"))
        self.eye.setMinimumSize(110, 110)
        # последний приказ — одной строкой; ответ — прокручиваемое поле (колесо мыши, полоса справа, выделение и копирование)
        self.sub_user = QLabel("")
        self.sub_user.setStyleSheet(f"color:{C['brass']}; font-size:12px; padding: 0 6px;")
        self.sub_user.setMaximumHeight(18)
        self.sub = QTextBrowser()
        self.sub.setObjectName("sub")
        self.sub.setOpenLinks(False)
        self.sub.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.sub.setMinimumHeight(90)
        self.sub.document().setDefaultStyleSheet(
            f"a {{ color:{C['brass']}; }} code, pre {{ font-family:'JetBrains Mono'; color:{C['cream']}; "
            f"background-color:#1e1613; }} th {{ color:{C['brass']}; }}")
        self.sub.setMarkdown("Слушаю, майор.")
        # строка приказа: поле + отправить + стоп
        bar = QWidget()
        bar.setObjectName("bar")
        bar.setMinimumHeight(40)
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(12, 5, 5, 5)
        bh.setSpacing(5)
        self.inp = PromptEdit("Приказ, майор…", max_lines=4, pad=2)      # многострочное: Enter — передать, Shift+Enter — строка
        self.inp.submitted.connect(self._send)
        stop = QPushButton("■")
        stop.setObjectName("stop")
        stop.setFixedSize(28, 28)
        stop.setToolTip("Стоп: прервать ответ и речь")
        stop.setCursor(Qt.CursorShape.PointingHandCursor)
        stop.clicked.connect(self.main.stop_answer)
        send = QPushButton("➤")
        send.setObjectName("send")
        send.setFixedSize(28, 28)
        send.setToolTip("Передать (Enter)")
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.clicked.connect(self._send)
        bh.addWidget(self.inp, 1, Qt.AlignmentFlag.AlignVCenter)
        bh.addWidget(stop, 0, Qt.AlignmentFlag.AlignBottom)
        bh.addWidget(send, 0, Qt.AlignmentFlag.AlignBottom)
        v.addLayout(top)
        v.addWidget(self.eye, 1)
        v.addWidget(self.sub_user)
        v.addWidget(self.sub, 3)
        v.addWidget(bar)
        grip = QSizeGrip(self)                                  # окно можно растянуть за правый нижний угол
        grip.setFixedSize(14, 14)
        grip.setStyleSheet("background: transparent;")
        self._grip = grip
        QShortcut(QKeySequence("Esc"), self, activated=self.hide)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "_grip"):
            self._grip.move(self.width() - 18, self.height() - 18)

    def _toggle_eye(self):
        show = not self.eye.isVisible()
        self.eye.setVisible(show)
        self.btn_eye.set_kind("down" if show else "up")
        self.btn_eye.setToolTip("Спрятать портрет — больше места для ответа" if show else "Показать портрет")

    # перетаскивание
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        self.main.showNormal()
        self.main.activateWindow()

    def _send(self):
        t = self.inp.text().strip()
        if t:
            self.inp.clear()
            self.main.brain.type(t)

    def summon(self):
        if self.isVisible() and self.isActiveWindow():
            return self.hide()
        if not self.isVisible():
            scr = QApplication.primaryScreen().availableGeometry()
            self.move(scr.right() - self.width() - 24, scr.bottom() - self.height() - 24)
        self.show()
        self.raise_()
        self.activateWindow()
        self.inp.setFocus()

    # субтитры
    @staticmethod
    def _plain(md):
        import re
        t = re.sub(r"```.*?```", " [код] ", md, flags=re.S)
        t = re.sub(r"\$\$.*?\$\$", " [формула] ", t, flags=re.S)
        t = re.sub(r"[*_`#>]", "", t)
        return t.strip()

    def _set_md(self, md, to_top=False):
        bar = self.sub.verticalScrollBar()
        prev, at_bottom = bar.value(), bar.value() >= bar.maximum() - 4
        self.sub.setMarkdown(md)                                 # замена документа сбрасывает позицию — вернём её сами
        if to_top:
            bar.setValue(0)
        elif at_bottom:                                          # у конца — следим за новыми строками
            bar.setValue(bar.maximum())
        else:                                                    # листает вручную — остаёмся на месте
            bar.setValue(min(prev, bar.maximum()))

    def subtitle(self, md, user=False):
        if user:                                                 # приказ — строкой над ответом
            t = " ".join(self._plain(md).split())
            self.sub_user.setText("› " + (t if len(t) <= 80 else t[:79] + "…"))
            return
        self._set_md(md, to_top=True)

    def begin(self):
        self._live = ""
        self._set_md("…", to_top=True)

    def token(self, tok):
        self._live += tok
        if not self._upd_pending:                                # разметка тяжёлая — обновляем не чаще 8 раз в секунду
            self._upd_pending = True
            QTimer.singleShot(120, self._flush_live)

    def _flush_live(self):
        self._upd_pending = False
        if self._live:
            self._set_md(self._live)

    def finish(self, text):
        self._live = ""
        if text:
            self._set_md(text, to_top=True)                      # готовый ответ читаем с начала

    def set_state(self, st):
        self.eye.state = st
        self.state_lbl.setText(STATE_TEXT.get(st, st.upper()))
        col = {"thinking": C["amber"], "speaking": C["red"], "off": "#5a4d44"}.get(st, "#3fbf6f")
        self.dot.setStyleSheet(f"color:{col}; font-size:9px;")


class IconButton(QPushButton):
    """Кнопка заголовка с иконкой, нарисованной линиями (а не текстовым символом): одинаковый размер и центр у всех кнопок,
    не зависит от шрифта. kind: min, max, restore, close, compact (окно в окне), expand, up, down."""

    def __init__(self, kind, tip="", size=(38, 28), hover=None, parent=None):
        super().__init__(parent)
        self.kind, self._hover_bg = kind, hover
        self.setFixedSize(*size)
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self._over = False

    def set_kind(self, kind):
        self.kind = kind
        self.update()

    def enterEvent(self, e):
        self._over = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._over = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        if self._over:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self._hover_bg or "#ffffff14"))
            p.drawRoundedRect(QRectF(r), 4, 4)
        col = QColor("#ffffff" if (self._over and self._hover_bg) else (C["cream"] if self._over else C["muted"]))
        p.setPen(QPen(col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = r.width() / 2, r.height() / 2
        k = self.kind
        if k == "min":
            p.drawLine(QPointF(cx - 5, cy + 0.5), QPointF(cx + 5, cy + 0.5))
        elif k == "max":
            p.drawRect(QRectF(cx - 5, cy - 5, 10, 10))
        elif k == "restore":
            p.drawRect(QRectF(cx - 5, cy - 2, 8, 8))
            p.drawPolyline([QPointF(cx - 2, cy - 2), QPointF(cx - 2, cy - 5), QPointF(cx + 5, cy - 5), QPointF(cx + 5, cy + 2), QPointF(cx + 3, cy + 2)])
        elif k == "close":
            p.drawLine(QPointF(cx - 4.5, cy - 4.5), QPointF(cx + 4.5, cy + 4.5))
            p.drawLine(QPointF(cx - 4.5, cy + 4.5), QPointF(cx + 4.5, cy - 4.5))
        elif k in ("compact", "expand"):                                  # окно в окне: большое с маленьким в углу
            p.drawRect(QRectF(cx - 6, cy - 5, 12, 10))
            p.setBrush(col)
            if k == "compact":
                p.drawRect(QRectF(cx + 0.5, cy + 0.5, 5, 4))
            else:
                p.drawRect(QRectF(cx - 6, cy - 5, 12, 3))
        elif k in ("up", "down"):
            d = 2.5 if k == "down" else -2.5
            p.drawPolyline([QPointF(cx - 4, cy - d), QPointF(cx, cy + d), QPointF(cx + 4, cy - d)])


class TitleBar(QWidget):
    """Своя строка заголовка (как в компактном окне): имя, статус, компактный режим, свернуть, развернуть, закрыть.
    Перетаскивание и двойной щелчок — через системные вызовы Qt (работает со снап-раскладками Windows)."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("titlebar")
        self.setFixedHeight(40)
        self.setStyleSheet(f"""
            QWidget#titlebar {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #1a1210, stop:1 {C['bg']});
                               border-bottom: 1px solid {C['line']}; }}
            QLabel {{ background: transparent; }}
            QPushButton {{ background: transparent; border: none; border-radius: 4px; color: {C['muted']};
                          font-family: 'Segoe UI'; font-size: 14px; padding: 0; letter-spacing: 0; }}
            QPushButton:hover {{ background: rgba(255,255,255,0.08); color: {C['cream']}; }}
            QPushButton#close:hover {{ background: {C['red']}; color: #fff; }}""")
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 0, 8, 0)
        h.setSpacing(4)
        cap = QLabel("ХРАЗ")
        cap.setStyleSheet(f"font-family:'Russo One'; font-size:16px; color:{C['red']}; letter-spacing:5px;")
        sub_ = QLabel("ХРАНИТЕЛЬ ЗНАНИЙ")
        sub_.setStyleSheet(f"font-family:'Oswald'; font-size:11px; letter-spacing:4px; color:{C['brass_dim']};")
        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color:{C['red']}; font-size:9px;")
        self.state_lbl = QLabel("ЖДУ ПРИКАЗА")
        self.state_lbl.setStyleSheet(f"font-family:'Oswald'; font-size:10px; letter-spacing:3px; color:{C['muted']};")
        h.addWidget(cap)
        h.addSpacing(10)
        h.addWidget(sub_)
        h.addSpacing(14)
        h.addWidget(self.dot)
        h.addWidget(self.state_lbl)
        h.addStretch()
        self.btn_compact = self._btn("compact", "Компактный режим", win.toggle_compact)
        self.btn_min = self._btn("min", "Свернуть", win.showMinimized)
        self.btn_max = self._btn("max", "Развернуть", self.toggle_max)
        self.btn_close = self._btn("close", "Свернуть в трей (выход — через иконку в трее)", win.close, hover=C["red"])
        self.btn_close.setObjectName("close")
        for b in (self.btn_compact, self.btn_min, self.btn_max, self.btn_close):
            h.addWidget(b)

    def _btn(self, kind, tip, slot, hover=None):
        b = IconButton(kind, tip, (38, 28), hover)
        b.clicked.connect(slot)
        return b

    def toggle_max(self):
        if self.win.isMaximized():
            self.win.showNormal()
        else:
            self.win.showMaximized()
        self.sync()

    def sync(self):
        mx = self.win.isMaximized()
        self.btn_max.set_kind("restore" if mx else "max")
        self.btn_max.setToolTip("Восстановить" if mx else "Развернуть")

    def set_state(self, st):
        self.state_lbl.setText(STATE_TEXT.get(st, st.upper()))
        col = {"thinking": C["amber"], "speaking": C["red"], "off": "#5a4d44"}.get(st, "#3fbf6f")
        self.dot.setStyleSheet(f"color:{col}; font-size:9px;")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self.win.isMaximized():
            h = self.win.windowHandle()
            if h:
                h.startSystemMove()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.toggle_max()


class EdgeGrip(QWidget):
    """Тонкая невидимая полоса по краю окна: без системной рамки её приходится делать самим (изменение размера)."""
    CURSORS = {Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor, Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
               Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor, Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor}

    def __init__(self, parent, edges):
        super().__init__(parent)
        self.edges = edges
        self.win = parent.window()
        if edges in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge):
            cur = Qt.CursorShape.SizeFDiagCursor
        elif edges in (Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.Edge.LeftEdge | Qt.Edge.BottomEdge):
            cur = Qt.CursorShape.SizeBDiagCursor
        else:
            cur = self.CURSORS[edges]
        self.setCursor(cur)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self.win.isMaximized():
            h = self.win.windowHandle()
            if h:
                h.startSystemResize(self.edges)


class Main(QMainWindow):
    def __init__(self, build):
        super().__init__()
        self.bridge = Bridge()
        self.cfg, self.llm, self.tts, self.store, self.brain, self.stt = build(self.bridge)
        self.current_cmd = None
        self.web_ready, self.web_queue = False, []
        self.compact = CompactWindow(self)
        self.last_meta = ""
        self._reasons = {}
        self.files = {}               # id карточки → путь файла (в ссылках чата путей нет)
        self.setWindowTitle("ХРАЗ — Хранитель знаний")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinMaxButtonsHint)
        self.resize(1360, 840)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(STYLE)

        root = QWidget()
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._side())
        tabs = QTabWidget()
        self.tabs = tabs
        self.chat_tab = self._chat_tab()
        tabs.addTab(self.chat_tab, "ДИАЛОГ")
        tabs.addTab(self._cmd_tab(), "КОМАНДЫ")
        self.mem_tab = self._archive_tab()
        tabs.addTab(self.mem_tab, "ПАМЯТЬ")
        self.log_tab = self._log_tab()
        tabs.addTab(self.log_tab, "ЖУРНАЛ")
        tabs.addTab(self._scroll(self._settings_tab()), "НАСТРОЙКИ")
        tabs.addTab(self._scroll(self._connectors_tab()), "КОННЕКТОРЫ")
        tabs.currentChanged.connect(self._tab_changed)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(12, 12, 12, 12)
        wl.addWidget(tabs)
        lay.addWidget(wrap, 1)
        frame = QWidget()                       # своя рамка: заголовок как в компактном окне + тонкая обводка
        frame.setObjectName("frame")
        frame.setStyleSheet(f"QWidget#frame {{ background: {C['bg']}; border: 1px solid {C['line']}; }}")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(1, 1, 1, 1)
        fl.setSpacing(0)
        self.titlebar = TitleBar(self)
        fl.addWidget(self.titlebar)
        fl.addWidget(root, 1)
        self.setCentralWidget(frame)
        self._grips = [EdgeGrip(frame, Qt.Edge.LeftEdge), EdgeGrip(frame, Qt.Edge.RightEdge),
                       EdgeGrip(frame, Qt.Edge.TopEdge), EdgeGrip(frame, Qt.Edge.BottomEdge),
                       EdgeGrip(frame, Qt.Edge.LeftEdge | Qt.Edge.TopEdge), EdgeGrip(frame, Qt.Edge.RightEdge | Qt.Edge.TopEdge),
                       EdgeGrip(frame, Qt.Edge.LeftEdge | Qt.Edge.BottomEdge),
                       EdgeGrip(frame, Qt.Edge.RightEdge | Qt.Edge.BottomEdge)]
        self._frame = frame

        b = self.bridge
        b.sig_status.connect(self.on_status)
        b.sig_partial.connect(lambda t: self.lbl_partial.setText(f"«{t}»"))
        b.sig_user.connect(lambda t: self._js("add", "user", t))
        b.sig_assistant.connect(lambda t: (self._js("add", "bot", t), self._refresh_list_soon()))
        b.sig_start.connect(lambda: self._js("start", self.last_meta))
        b.sig_token.connect(lambda tok: self._js("token", tok))
        b.sig_done.connect(lambda t: (self._js("end", t), self._refresh_list_soon()))
        b.sig_cmds.connect(self.reload_cmds)
        b.sig_confirm.connect(self.on_confirm)
        b.sig_resolve.connect(lambda i, t: self._js("resolve", i, t))
        b.sig_model.connect(self.on_model)
        b.sig_action.connect(lambda t: self._set_row("act", t or "—", "busy" if t else "off"))
        b.sig_more.connect(lambda: self._js("more"))
        b.sig_chat.connect(self.reload_chat)
        b.sig_memory.connect(self.reload_archive)
        b.sig_ollama.connect(self.on_ollama)
        b.sig_report.connect(lambda md: self._js("add", "sys", md))
        b.sig_tool_start.connect(lambda i, n, a: self._js("toolStart", i, n, a))
        b.sig_tool_end.connect(lambda i, ok, r: self._js("toolEnd", i, ok, r))
        b.sig_file.connect(self.on_file)
        b.sig_mic.connect(self._mic_ready)
        b.sig_alert.connect(self.on_alert)
        b.sig_rateable.connect(lambda i: self._js("rateable", i, 0))
        b.sig_rated.connect(lambda i, v: self._js("rated", i, v))
        b.sig_kb.connect(self._kb_status)
        # компактное окно повторяет диалог субтитрами
        b.sig_status.connect(lambda st: self.compact.set_state(st))
        b.sig_partial.connect(lambda t: self.compact.subtitle(f"«{t}»", user=True))
        b.sig_user.connect(lambda t: self.compact.subtitle(t, user=True))
        b.sig_start.connect(lambda: self.compact.begin())
        b.sig_token.connect(lambda tok: self.compact.token(tok))
        b.sig_done.connect(lambda t: self.compact.finish(t))
        b.sig_assistant.connect(lambda t: self.compact.subtitle(t))
        b.sig_hub.connect(lambda t: (setattr(self, "_hub_text", t), self._update_conn_row(),
                                     hasattr(self, "m_state") and self.m_state.setText(
                                         "; ".join(f"{n}: {x}" for n, _, x in self.brain.hub.status()))))
        self.llm.on_model = lambda m, st: b.sig_model.emit(m, "загружаю модель в видеопамять…" if st == "loading"
                                                            else self._reasons.get(m, "готова"))

        self._tray()
        self._hotkey = None
        self.bridge.sig_hotkey.connect(self.toggle_compact)
        self._start_hotkey()
        if not self.stt.start():
            self._js("add", "sys", f"⚠ {self.stt.error}. Пока можно писать текстом.")
            self.stt.enabled.clear()
            self.btn_mic.setText("НЕТ VOSK")
            self._set_row("mic", "НЕТ VOSK — только текст", "bad")
            self.on_status("off")
            if "Нет модели" in (self.stt.error or ""):
                threading.Thread(target=self._first_run_models, daemon=True).start()
        QTimer.singleShot(3000, self._check_stt)
        QTimer.singleShot(600, self.brain.greet)
        QTimer.singleShot(1200, lambda: threading.Thread(target=self.startup_check, daemon=True).start())
        self._otimer = QTimer(self)
        self._otimer.timeout.connect(lambda: threading.Thread(target=self.poll_ollama, daemon=True).start())
        self._otimer.start(15000)
        self._set_row("mic", "ВКЛ" if self.stt.enabled.is_set() else "ВЫКЛ", "ok" if self.stt.enabled.is_set() else "off")
        self._update_conn_row()
        self.on_model(self.cfg["model"], "автовыбор" if self.brain.mode == "auto" else f"режим {self.brain.mode}")
        if self.cfg.pop("_migrated", None):
            config.save(self.cfg)
            self._js("add", "sys", f"Настройки обновлены: основная модель теперь **{self.cfg['model']}**, "
                                   f"сложные вопросы — **{self.cfg['model_smart']}**, код — **{self.cfg['model_code']}** "
                                   "(только по команде «режим кода»).")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_grips()
        if hasattr(self, "titlebar"):
            self.titlebar.sync()

    def changeEvent(self, e):
        super().changeEvent(e)
        if hasattr(self, "titlebar"):
            self.titlebar.sync()
            self._place_grips()

    def _place_grips(self):
        if not hasattr(self, "_grips"):
            return
        w, h, t, c = self._frame.width(), self._frame.height(), 5, 12
        geo = [(0, c, t, h - 2 * c), (w - t, c, t, h - 2 * c), (c, 0, w - 2 * c, t), (c, h - t, w - 2 * c, t),
               (0, 0, c, c), (w - c, 0, c, c), (0, h - c, c, c), (w - c, h - c, c, c)]
        for g, (x, y, gw, gh) in zip(self._grips, geo):
            g.setGeometry(x, y, gw, gh)
            g.setVisible(not self.isMaximized())
            g.raise_()

    # ---------------- левая панель ----------------
    def _side(self):
        side = QWidget()
        side.setObjectName("side")
        side.setFixedWidth(300)
        v = QVBoxLayout(side)
        v.setContentsMargins(20, 22, 20, 18)
        title = QLabel("ХРАЗ")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"font-family:'Russo One'; font-size:46px; color:{C['red']}; letter-spacing:8px;")
        sub = QLabel("ХРАНИТЕЛЬ ЗНАНИЙ")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"font-family:'Oswald'; font-size:13px; letter-spacing:6px; color:{C['brass']};")
        self.eye = PolymerEye(os.path.join(ASSETS, "img", "khraz_portrait.png"))
        self.lbl_status = QLabel(STATE_TEXT["idle"])
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setStyleSheet(f"font-family:'Oswald'; font-size:15px; letter-spacing:5px; color:{C['cream']};")
        self.lbl_partial = QLabel("")
        self.lbl_partial.setWordWrap(True)
        self.lbl_partial.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_partial.setMinimumHeight(40)
        self.lbl_partial.setStyleSheet(f"color:{C['muted']}; font-style:italic;")
        self.btn_mic = QPushButton("МИКРОФОН: ВКЛ")
        self.btn_mic.clicked.connect(self.toggle_mic)
        self.btn_voice = QPushButton("ГОЛОС: ВКЛ")
        self.btn_voice.clicked.connect(self.toggle_voice)
        self.status_box = self._status_box()
        for wdg in (title, sub):
            v.addWidget(wdg)
        v.addSpacing(10)
        v.addWidget(self.eye, 1)
        v.addWidget(self.lbl_status)
        v.addWidget(self.lbl_partial)
        v.addStretch()
        row = QHBoxLayout()
        row.addWidget(self.btn_mic)
        row.addWidget(self.btn_voice)
        v.addLayout(row)
        v.addSpacing(6)
        self.btn_compact = QPushButton("КОМПАКТНЫЙ РЕЖИМ")
        self.btn_compact.setToolTip("Маленькое окно поверх всех окон: портрет, субтитры, строка ввода. "
                                    "Горячая клавиша — в Настройках (по умолчанию Win+Shift+X)")
        self.btn_compact.clicked.connect(self.toggle_compact)
        v.addSpacing(6)
        v.addWidget(self.btn_compact)
        v.addSpacing(8)
        v.addWidget(self.status_box)
        return side

    # ---------------- строка состояния: микрофон, Ollama, модель, действие ----------------
    ROWS = (("mic", "МИКРОФОН"), ("ollama", "OLLAMA"), ("model", "МОДЕЛЬ"), ("act", "ДЕЙСТВИЕ"), ("cab", "КОННЕКТОРЫ"))
    DOT = {"ok": "#3fbf6f", "bad": "#ff4b4b", "busy": "#ff9d2e", "off": "#5a4d44"}

    def _status_box(self):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(2, 4, 2, 0)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(3)
        self.rows = {}
        for i, (key, name) in enumerate(self.ROWS):
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{self.DOT['off']}; font-size:10px;")
            lab = QLabel(name)
            lab.setStyleSheet(f"font-family:'Oswald'; font-size:10px; letter-spacing:2px; color:{C['muted']};")
            val = QLabel("—")
            val.setWordWrap(True)
            val.setStyleSheet(f"font-family:'JetBrains Mono'; font-size:10.5px; color:{C['cream']};")
            g.addWidget(dot, i, 0, Qt.AlignmentFlag.AlignTop)
            g.addWidget(lab, i, 1, Qt.AlignmentFlag.AlignTop)
            g.addWidget(val, i, 2)
            self.rows[key] = (dot, val)
        g.setColumnStretch(2, 1)
        return w

    def _set_row(self, key, text, state="ok", tip=""):
        if not hasattr(self, "rows") or key not in self.rows:
            return
        dot, val = self.rows[key]
        dot.setStyleSheet(f"color:{self.DOT.get(state, self.DOT['off'])}; font-size:10px;")
        val.setText(text if len(text) < 60 else text[:57] + "…")
        val.setToolTip(tip or text)

    def on_model(self, model, reason):
        self._sync_model_btn()
        busy = "загружаю" in reason
        if not busy:
            self._reasons[model] = reason
            self.last_meta = f"{model} · {reason}"
        self._set_row("model", f"{model}\n{reason}", "busy" if busy else "ok", self.last_meta)

    def on_ollama(self, ok, text):
        self._set_row("ollama", text, "ok" if ok else "bad")

    def poll_ollama(self):
        v = self.llm.version()
        if v:
            loaded = self.llm.loaded()
            self.bridge.sig_ollama.emit(True, f"v{v}" + (f" · в памяти: {', '.join(loaded)}" if loaded else ""))
        else:
            self.bridge.sig_ollama.emit(False, "НЕТ СВЯЗИ")

    def startup_check(self, always=False):
        """Ollama доступна? Модели установлены? Недостающие — точной командой ollama pull."""
        import startup
        rep = startup.check(self.cfg)
        self.poll_ollama()
        if always or not rep.ollama or rep.missing:
            self.bridge.sig_report.emit(rep.markdown())

    # ---------------- диалог ----------------
    def _chats_panel(self):
        w = QWidget()
        w.setFixedWidth(210)
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 4, 8)
        h = QLabel("ЧАТЫ")
        h.setObjectName("h")
        self.chat_list = QListWidget()
        self.chat_list.setWordWrap(True)
        self.chat_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chat_list.itemClicked.connect(self.open_chat)
        self.chat_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chat_list.customContextMenuRequested.connect(self._chat_menu)
        b_new = QPushButton("+ НОВЫЙ ЧАТ")
        b_new.setObjectName("primary")
        b_new.clicked.connect(lambda: (self.brain.new_chat(), self.reload_chat()))
        b_del = QPushButton("УДАЛИТЬ ЧАТ")
        b_del.clicked.connect(self.delete_chat)
        b_all = QPushButton("ОЧИСТИТЬ ВСЁ…")
        b_all.setToolTip("Удалить все чаты и всю долговременную память")
        b_all.clicked.connect(self.wipe_all)
        for x in (h, b_new):
            v.addWidget(x)
        v.addWidget(self.chat_list, 1)
        v.addWidget(b_del)
        v.addWidget(b_all)
        return w

    def _refresh_list_soon(self):
        QTimer.singleShot(400, self.reload_chat_list)

    def reload_chat_list(self):
        self.chat_list.clear()
        cur = self.brain.chats.current["id"]
        for c in self.brain.chats.list():
            it = QListWidgetItem(f"{c['title']}\n{c['updated'][5:16]} · {c['count']} сообщ.")
            it.setData(Qt.ItemDataRole.UserRole, c["id"])
            self.chat_list.addItem(it)
            if c["id"] == cur:
                self.chat_list.setCurrentItem(it)

    def reload_chat(self):
        """Показать текущий чат целиком (после переключения, очистки, нового чата)."""
        self._js("clear")
        for m in self.brain.chats.messages[-200:]:
            meta = (m.get("meta") or {}).get("model", "") if m["role"] == "assistant" else ""
            self._js("add", "user" if m["role"] == "user" else "bot", m["content"], meta, m.get("ts", ""))
            if m["role"] == "assistant" and m.get("id"):
                self._js("rateable", m["id"], int((m.get("meta") or {}).get("vote") or 0))
        self.reload_chat_list()

    def open_chat(self, item):
        self.brain.chats.open(item.data(Qt.ItemDataRole.UserRole))
        self.reload_chat()

    def _chat_menu(self, pos):
        it = self.chat_list.itemAt(pos)
        if not it:
            return
        menu = QMenu(self)
        a_ren = menu.addAction("Переименовать")
        a_del = menu.addAction("Удалить")
        act = menu.exec(self.chat_list.mapToGlobal(pos))
        cid = it.data(Qt.ItemDataRole.UserRole)
        if act == a_ren:
            title, ok = QInputDialog.getText(self, "ХРАЗ", "Название чата:", text=it.text().split("\n")[0])
            if ok and title.strip():
                self.brain.chats.rename(cid, title)
                self.reload_chat_list()
        elif act == a_del:
            self.chat_list.setCurrentItem(it)
            self.delete_chat()

    def delete_chat(self):
        it = self.chat_list.currentItem()
        if not it:
            return
        if QMessageBox.question(self, "ХРАЗ", f"Удалить чат «{it.text().split(chr(10))[0]}»? "
                                              "Память при этом не трогается.") != QMessageBox.StandardButton.Yes:
            return
        self.brain.chats.delete(it.data(Qt.ItemDataRole.UserRole))
        self.reload_chat()

    def wipe_all(self):
        if QMessageBox.question(self, "ХРАЗ", "Удалить ВСЕ чаты и ВСЮ долговременную память? Восстановить будет "
                                              "нельзя.") != QMessageBox.StandardButton.Yes:
            return
        self.brain.memory.clear()
        self.brain.chats.delete_all()
        self.reload_chat()
        self.reload_archive()
        self._js("add", "sys", "Все чаты и память очищены.")

    def read_document(self):
        roots = [os.path.expanduser(x) for x in self.cfg.get("search_roots", [])]
        path, _ = QFileDialog.getOpenFileName(self, "Документ или фото решения для ХРАЗа", roots[0] if roots else "",
                                              "Документы и фото (*.txt *.md *.pdf *.docx *.csv *.json *.py *.log "
                                              "*.png *.jpg *.jpeg *.webp);;Все (*)")
        if not path:
            return
        from tools.files import is_forbidden
        if is_forbidden(self.cfg, path):
            QMessageBox.warning(self, "ХРАЗ", "Эта папка закрыта для ХРАЗа (forbidden_paths).")
            return
        if path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):      # фото → проверка решения
            self.inp.clear()
            return threading.Thread(target=self.brain.check_solution, kwargs={"path": path,
                                    "raw": f"проверь решение: {os.path.basename(path)}"}, daemon=True).start()
        self.brain.picked_files.add(path)
        q = self.inp.text().strip() or "кратко перескажи"
        self.inp.clear()
        self.brain.type(f"Прочитай документ {path} и {q}")

    def _chat_tab(self):
        outer = QWidget()
        oh = QHBoxLayout(outer)
        oh.setContentsMargins(0, 0, 0, 0)
        oh.setSpacing(0)
        oh.addWidget(self._chats_panel())
        w = QWidget()
        oh.addWidget(w, 1)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        if HAS_WEB:
            self.view = QWebEngineView()
            self.view.setPage(ChatPage(self.on_card_action, self.view))
            s = self.view.settings()
            s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
            self.view.page().setBackgroundColor(QColor(C["bg"]))
            self.view.loadFinished.connect(self._web_loaded)
            self.view.load(QUrl.fromLocalFile(os.path.join(ASSETS, "web", "chat.html")))
        else:
            self.view = QTextBrowser()
            self.view.setOpenExternalLinks(True)
            self._plain = []
        v.addWidget(self.view, 1)
        # ---- карточка ввода: поле сверху, ниже тулбар (как в Claude) ----
        composer = QWidget()
        composer.setObjectName("composer")
        self._composer = composer
        composer.setStyleSheet(f"""
            QWidget#composer {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 16px; }}
            QWidget#composer[focus="true"] {{ border: 1px solid {C['brass_dim']}; }}
            QPlainTextEdit {{ background: transparent; border: none; padding: 2px 4px; font-size: 14px; color: {C['cream']};
                              selection-background-color: {C['red_dim']}; }}
            QPushButton {{ background: transparent; border: none; border-radius: 15px; padding: 0; color: {C['muted']};
                           font-family: 'Segoe UI'; letter-spacing: 0; }}
            QPushButton:hover {{ background: rgba(255,255,255,0.08); color: {C['cream']}; }}
            QPushButton#plus {{ font-size: 18px; }}
            QPushButton#model {{ color: {C['brass']}; font-family: 'Oswald'; font-size: 12px; letter-spacing: 2px; padding: 0 12px; }}
            QPushButton#model:hover {{ background: rgba(201,162,74,0.12); }}
            QPushButton#stopb {{ color: {C['red']}; border: 1px solid {C['red_dim']}; font-family: 'Oswald'; font-size: 11px;
                                letter-spacing: 2px; padding: 0 12px; }}
            QPushButton#stopb:hover {{ background: rgba(215,38,46,0.15); border-color: {C['red']}; }}
            QPushButton#sendb {{ background: {C['red']}; color: #fff; font-size: 15px; }}
            QPushButton#sendb:hover {{ background: #ef3a42; }}
            QPushButton#sendb:disabled {{ background: #3a2a22; color: #6b5a50; }}""")
        cv = QVBoxLayout(composer)
        cv.setContentsMargins(14, 10, 10, 8)
        cv.setSpacing(4)
        self.inp = PromptEdit("Приказ, майор…  Enter — передать, Shift+Enter — новая строка", max_lines=7, pad=4)
        self.inp.submitted.connect(self.send)
        self.inp.focused.connect(self._composer_focus)
        self.inp.textChanged.connect(self._sync_send)
        cv.addWidget(self.inp)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        doc = QPushButton("+")
        doc.setObjectName("plus")
        doc.setFixedSize(30, 30)
        doc.setCursor(Qt.CursorShape.PointingHandCursor)
        doc.setToolTip("Прикрепить документ (txt, md, pdf, docx) или фото решения. В строке можно написать, что с ним сделать")
        doc.clicked.connect(self.read_document)
        self.btn_stop = QPushButton("■ СТОП")
        self.btn_stop.setObjectName("stopb")
        self.btn_stop.setFixedHeight(30)
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setToolTip("Прервать размышление и озвучку (Esc). Голосом: «Храз, стоп»")
        self.btn_stop.clicked.connect(self.stop_answer)
        self.btn_stop.setVisible(False)                       # виден только пока ХРАЗ думает или говорит
        self.btn_model = QPushButton("АВТО ▾")                # выбор модели, как в Claude: у поля ввода
        self.btn_model.setObjectName("model")
        self.btn_model.setFixedHeight(30)
        self.btn_model.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_model.clicked.connect(self._show_model_menu)
        self.model_menu = QMenu(self)
        self.btn_send = QPushButton("➤")
        self.btn_send.setObjectName("sendb")
        self.btn_send.setFixedSize(32, 32)
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.setToolTip("Передать (Enter)")
        self.btn_send.clicked.connect(self.send)
        self.btn_send.setEnabled(False)
        QShortcut(QKeySequence("Esc"), self, activated=self.stop_answer)
        tools.addWidget(doc)
        tools.addWidget(self.btn_stop)
        tools.addStretch()
        tools.addWidget(self.btn_model)
        tools.addWidget(self.btn_send)
        cv.addLayout(tools)
        wrap = QHBoxLayout()
        wrap.setContentsMargins(16, 6, 16, 14)
        wrap.addWidget(composer)
        v.addLayout(wrap)
        return outer

    def _composer_focus(self, on):
        self._composer.setProperty("focus", "true" if on else "false")
        self._composer.style().unpolish(self._composer)
        self._composer.style().polish(self._composer)

    def _sync_send(self):
        self.btn_send.setEnabled(bool(self.inp.text().strip()))

    def _show_model_menu(self):
        self._build_model_menu()
        m = self.model_menu
        sz = m.sizeHint()
        m.exec(self.btn_model.mapToGlobal(QPoint(self.btn_model.width() - sz.width(), -sz.height() - 6)))      # открывается вверх

    # ---- выбор модели у поля ввода ----
    ROLE_TITLE = {"auto": "АВТО", "fast": "БЫСТРАЯ", "smart": "УМНАЯ", "code": "КОД"}

    def _build_model_menu(self):
        m = self.model_menu
        m.clear()
        m.setStyleSheet(f"QMenu {{ background:{C['panel']}; border:1px solid {C['brass_dim']}; padding:4px; }} "
                        f"QMenu::item {{ padding:7px 22px 7px 14px; }} QMenu::item:selected {{ background:{C['panel2']}; }} "
                        f"QMenu::item:disabled {{ color:{C['muted']}; font-family:'Oswald'; letter-spacing:2px; font-size:10px; }}")
        m.addAction("МОДЕЛЬ ДЛЯ ОТВЕТОВ").setEnabled(False)
        grp = QActionGroup(m)
        grp.setExclusive(True)
        for rid, title in (("auto", "Авто — сам выбирает под вопрос"), ("fast", f"Быстрая · {self.cfg.get('model')}"),
                           ("smart", f"Умная · {self.cfg.get('model_smart')}"), ("code", f"Код · {self.cfg.get('model_code')}")):
            if rid != "auto" and re.search(r"ocr|embed|bge|minilm|nomic", title, re.I):
                title += "  ⚠ не для диалога"
            a = m.addAction(title)
            a.setCheckable(True)
            a.setChecked(self.brain.mode == rid)
            grp.addAction(a)
            a.triggered.connect(lambda _=False, r=rid: self.pick_mode(r))
        try:
            import coder
            cs = coder.status(self.cfg)
        except Exception:                           # noqa: BLE001
            cs = None
        if cs:
            m.addSeparator()
            m.addAction("КЛОД / КОДЕКС — для «спроси Клода…»").setEnabled(False)
            cgrp = QActionGroup(m)
            cgrp.setExclusive(True)
            st = cs["state"]
            for ag in cs["agents"]:
                for mo in (ag["models"] or [""]):
                    a = m.addAction(f"{ag['title']}" + (f" · {mo}" if mo else "") + ("" if ag["installed"] else "  (не найден)"))
                    a.setCheckable(True)
                    a.setChecked(st["agent"] == ag["id"] and st["model"] == mo)
                    cgrp.addAction(a)
                    a.triggered.connect(lambda _=False, ai=ag["id"], mi=mo: self._pick_coder(ai, mi))
            m.addSeparator()
            pgrp = QActionGroup(m)
            pgrp.setExclusive(True)
            for pn in cs["projects"]:
                a = m.addAction(f"Проект: {pn}")
                a.setCheckable(True)
                a.setChecked(st["project"] == pn)
                pgrp.addAction(a)
                a.triggered.connect(lambda _=False, n=pn: self._pick_coder_project(n))
            m.addAction("＋ Добавить проект (папку)…" if cs["projects"] else "＋ Выбрать папку проекта…  (без неё не запустится)"
                        ).triggered.connect(self._add_coder_project)

    def _add_coder_project(self):
        import coder
        d = QFileDialog.getExistingDirectory(self, "Папка проекта для Клода / Кодекса")
        if not d:
            return
        from tools.files import is_forbidden
        if is_forbidden(self.cfg, d):
            QMessageBox.warning(self, "ХРАЗ", "Эта папка в списке запрещённых.")
            return
        try:
            name = coder.add_project(self.cfg, d)
            config.save(self.cfg)
            coder.set_state(self.cfg, project=name)
        except ValueError as e:
            self._js("add", "sys", f"⚠ {e}")
            return
        self._js("add", "sys", f"Проект **{name}** добавлен: агент получит только эту папку. Запуск — «спроси Клода …».")

    def _pick_coder_project(self, name):
        import coder
        try:
            coder.set_state(self.cfg, project=name)
            self._js("add", "sys", f"Проект кодера: **{name}**.")
        except ValueError as e:
            self._js("add", "sys", f"⚠ {e}")

    def pick_mode(self, mode):
        self.brain.set_mode(mode)
        self._sync_model_btn()

    def _pick_coder(self, agent, model):
        import coder
        try:
            coder.set_state(self.cfg, agent=agent, model=model)
            self._js("add", "sys", f"Кодер: **{agent}** · {model or 'модель по умолчанию'}. Запуск — фразой «спроси Клода …» (с подтверждением).")
        except ValueError as e:
            self._js("add", "sys", f"⚠ {e}")

    def _sync_model_btn(self):
        if hasattr(self, "btn_model"):
            mode = self.brain.mode
            self.btn_model.setText(self.ROLE_TITLE.get(mode, "АВТО") + " ▾")
            self.btn_model.setToolTip({"auto": "Модель выбирается автоматически под вопрос",
                                       "fast": f"Всегда {self.cfg.get('model')}", "smart": f"Всегда {self.cfg.get('model_smart')}",
                                       "code": f"Всегда {self.cfg.get('model_code')}"}.get(mode, ""))

    def _web_loaded(self, ok):
        self.web_ready = True
        queued, self.web_queue = self.web_queue, []
        self.reload_chat()                      # история текущего чата
        for code in queued:
            self.view.page().runJavaScript(code)

    def _js(self, fn, *args):
        if HAS_WEB:
            code = f"KH.{fn}({', '.join(json.dumps(a) for a in args)})"
            if self.web_ready:
                self.view.page().runJavaScript(code)
            else:
                self.web_queue.append(code)
            return
        # запасной вариант без WebEngine
        if fn == "add":
            self._plain.append([args[0], args[1]])
        elif fn == "start":
            self._plain.append(["bot", ""])
        elif fn == "token" and self._plain:
            self._plain[-1][1] += args[0]
        elif fn == "end" and self._plain and args and args[0]:
            self._plain[-1][1] = args[0]
        elif fn == "clear":
            self._plain.clear()
        md = "\n\n".join(("**Майор:** " if r == "user" else "**ХРАЗ:** ") + t for r, t in self._plain[-100:])
        self.view.setMarkdown(md)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def toggle_compact(self):
        self.compact.summon()

    def _start_hotkey(self):
        from hotkey import GlobalHotkey
        if self._hotkey:
            self._hotkey.stop()
        combo = (self.cfg.get("hotkey") or "").strip()
        if not combo:
            return
        self._hotkey = GlobalHotkey(combo, self.bridge.sig_hotkey.emit)     # из потока Windows — через сигнал
        if not self._hotkey.start() and sys.platform == "win32":
            self._js("add", "sys", f"⚠ Горячая клавиша: {self._hotkey.error}")

    def on_alert(self, md):
        self._js("alert", md)
        self.compact.subtitle(md)
        if self.isHidden() and hasattr(self, "tray"):
            self.tray.showMessage("ХРАЗ", md.replace("*", "")[:200], QSystemTrayIcon.MessageIcon.Information, 6000)

    def on_confirm(self, op_id, title, md, voice_ok):
        import sfx
        if not self.brain.silent:
            sfx.play("card", self.cfg)
        if HAS_WEB:
            self._js("confirm", op_id, title, md, voice_ok)
            return
        # без WebEngine — обычный диалог Qt
        r = QMessageBox.question(self, f"ХРАЗ · {title}", md + "\n\nПодтвердить?")
        self.on_card_action("approve" if r == QMessageBox.StandardButton.Yes else "reject", op_id)

    def on_file(self, path):
        fid = f"f{len(self.files) + 1}"
        self.files[fid] = path
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        human = f"{size / 1024:.1f} КБ" if size < 1024 ** 2 else f"{size / 1024 ** 2:.1f} МБ"
        preview = QUrl.fromLocalFile(path).toString() if path.lower().endswith((".png", ".jpg", ".jpeg")) else ""
        self._js("file", fid, os.path.basename(path), human, os.path.dirname(path), preview)

    def file_action(self, act, fid):
        import shutil
        from PyQt6.QtGui import QDesktopServices
        path = self.files.get(fid)
        if not path or not os.path.exists(path):
            return self._js("add", "sys", "Файл не найден — возможно, его переместили или удалили.")
        if act == "open":
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        elif act == "folder":
            if sys.platform == "win32":
                import subprocess
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
        elif act == "save":
            dest, _ = QFileDialog.getSaveFileName(self, "Сохранить файл", os.path.join(
                os.path.expanduser("~/Downloads"), os.path.basename(path)))
            if dest:
                from tools.files import is_forbidden
                if is_forbidden(self.cfg, dest):
                    return QMessageBox.warning(self, "ХРАЗ", "Сохранять в эту папку запрещено.")
                shutil.copy2(path, dest)
                self._js("add", "sys", f"Сохранено: `{dest}`")

    def on_card_action(self, action, op_id):
        if action == "rate":
            vote, _, mid = op_id.partition("/")
            return threading.Thread(target=self.brain.rate, args=(mid, 1 if vote == "up" else -1), daemon=True).start()
        if action == "file":
            act, _, fid = op_id.partition("/")
            return self.file_action(act, fid)
        if action == "continue":
            self.brain.type("подробнее")
        elif action == "approve":
            self.brain.approve(op_id, via="ui")
        elif action == "reject":
            self.brain.reject(op_id)

    def send(self):
        t = self.inp.text().strip()
        if t:
            self.inp.clear()
            self.brain.type(t)

    def stop_answer(self):
        self.brain.stop()
        self.on_status("listening")

    def clear_chat(self):
        self.brain.chats.clear_current()
        self.reload_chat()

    def on_status(self, s):
        if not self.stt.enabled.is_set() and s in ("idle", "listening"):
            s = "off"
        self.eye.state = s
        self.lbl_status.setText(STATE_TEXT.get(s, s.upper()))
        if hasattr(self, "titlebar"):
            self.titlebar.set_state(s)
        if hasattr(self, "btn_stop"):
            self.btn_stop.setVisible(s in ("thinking", "speaking"))
        if s in ("idle", "listening", "off"):
            self.lbl_partial.setText("")

    def toggle_mic(self):
        if self.stt.enabled.is_set():
            self.stt.enabled.clear()
            self._set_row("mic", "ВЫКЛ — запись остановлена", "off")
            self.btn_mic.setText("МИКРОФОН: ВЫКЛ")
            self.on_status("off")
        else:
            self.stt.enabled.set()
            self._set_row("mic", "ВКЛ — слушаю «Храз…»", "ok")
            self.btn_mic.setText("МИКРОФОН: ВКЛ")
            self.on_status("idle")

    def toggle_voice(self):
        self.brain.silent = not self.brain.silent
        self.tts.mute(self.brain.silent)
        self.btn_voice.setText("ГОЛОС: ВЫКЛ" if self.brain.silent else "ГОЛОС: ВКЛ")

    def _first_run_models(self):
        """Установленный exe: модели речи скачиваются при первом запуске (вместо setup.bat)."""
        import models_dl
        b = self.bridge
        try:
            b.sig_report.emit("Первый запуск: скачиваю распознавание речи Vosk (45 МБ)…")
            path = models_dl.ensure_vosk(lambda p: b.sig_action.emit(f"Vosk: {p}%"))
            self.cfg["vosk_model_abs"] = path
            if self.cfg.get("tts_engine") == "piper" or not self.cfg.get("fish_api_key"):
                b.sig_report.emit("Скачиваю запасной голос Piper (60 МБ)…")
                models_dl.ensure_piper(lambda p: b.sig_action.emit(f"Piper: {p}%"))
            b.sig_action.emit("")
            if self.stt.start():
                b.sig_mic.emit()
                b.sig_report.emit("Готово: микрофон работает. Скажите «Храз…».")
        except Exception as e:
            b.sig_report.emit(f"⚠ Модели не скачались ({e}). Проверьте интернет и перезапустите ХРАЗ.")

    def _mic_ready(self):
        self.stt.enabled.set()
        self.btn_mic.setText("МИКРОФОН: ВКЛ")
        self._set_row("mic", "ВКЛ — слушаю «Храз…»", "ok")
        self.on_status("idle")

    def _check_stt(self):
        if self.stt.error and "Нет модели" not in self.stt.error:
            self._js("add", "sys", f"⚠ {self.stt.error}")
            self.on_status("off")

    # ---------------- конструктор команд ----------------
    def _cmd_tab(self):
        w = QWidget()
        h = QHBoxLayout(w)
        lv = QVBoxLayout()
        lbl = QLabel("МОИ КОМАНДЫ")
        lbl.setObjectName("h")
        self.cmd_list = QListWidget()
        self.cmd_list.currentItemChanged.connect(self.pick_cmd)
        btn_new = QPushButton("+ НОВАЯ")
        btn_new.clicked.connect(self.new_cmd)
        hint = QLabel("Голосом: «ХРАЗ, создай команду…»")
        hint.setObjectName("hint")
        lv.addWidget(lbl)
        lv.addWidget(self.cmd_list, 1)
        lv.addWidget(btn_new)
        lv.addWidget(hint)
        h.addLayout(lv, 1)

        rv = QVBoxLayout()
        form = QFormLayout()
        self.ed_name = QLineEdit()
        self.ed_phrases = QLineEdit()
        self.ed_phrases.setPlaceholderText("через запятую: режим работы, рабочий режим")
        self.ed_reply = QLineEdit()
        self.ed_reply.setPlaceholderText("что ХРАЗ скажет после выполнения")
        form.addRow("Название", self.ed_name)
        form.addRow("Фразы", self.ed_phrases)
        form.addRow("Ответ", self.ed_reply)
        rv.addLayout(form)
        l2 = QLabel("ЦЕПОЧКА ШАГОВ")
        l2.setObjectName("h")
        rv.addWidget(l2)
        self.steps = QTableWidget(0, 2)
        self.steps.setHorizontalHeaderLabels(["ДЕЙСТВИЕ", "ПАРАМЕТР"])
        self.steps.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.steps.setColumnWidth(0, 210)
        self.steps.verticalHeader().setVisible(False)
        rv.addWidget(self.steps, 1)
        row = QHBoxLayout()
        for text, fn in (("+ ШАГ", self.add_step), ("− ШАГ", self.del_step), ("↑", lambda: self.move_step(-1)),
                         ("↓", lambda: self.move_step(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        rv.addLayout(row)
        row2 = QHBoxLayout()
        b_run = QPushButton("▶ ПРОВЕРИТЬ")
        b_run.clicked.connect(self.test_cmd)
        b_del = QPushButton("УДАЛИТЬ")
        b_del.clicked.connect(self.delete_cmd)
        b_save = QPushButton("СОХРАНИТЬ")
        b_save.setObjectName("primary")
        b_save.clicked.connect(self.save_cmd)
        row2.addWidget(b_run)
        row2.addWidget(b_del)
        row2.addStretch()
        row2.addWidget(b_save)
        rv.addLayout(row2)
        h.addLayout(rv, 2)
        self.reload_cmds()
        return w

    def reload_cmds(self):
        keep = self.current_cmd["id"] if self.current_cmd else None
        self.cmd_list.blockSignals(True)
        self.cmd_list.clear()
        for c in self.store.items:
            it = QListWidgetItem(c["name"])
            it.setData(Qt.ItemDataRole.UserRole, c["id"])
            self.cmd_list.addItem(it)
            if c["id"] == keep:
                self.cmd_list.setCurrentItem(it)
        self.cmd_list.blockSignals(False)
        if self.cmd_list.currentItem() is None and self.cmd_list.count():
            self.cmd_list.setCurrentRow(0)
        elif self.cmd_list.currentItem():
            self.pick_cmd(self.cmd_list.currentItem(), None)

    def pick_cmd(self, item, _prev):
        if not item:
            return
        cid = item.data(Qt.ItemDataRole.UserRole)
        c = next((x for x in self.store.items if x["id"] == cid), None)
        if c:
            self._fill(dict(c))

    def _fill(self, c):
        self.current_cmd = c
        self.ed_name.setText(c.get("name", ""))
        self.ed_phrases.setText(", ".join(c.get("phrases", [])))
        self.ed_reply.setText(c.get("reply", ""))
        self.steps.setRowCount(0)
        for s in c.get("steps", []):
            self.add_step(s)

    def add_step(self, step=None):
        step = step if isinstance(step, dict) else {"type": "open_app", "param": ""}
        r = self.steps.rowCount()
        self.steps.insertRow(r)
        cb = QComboBox()
        for k, v in actions.ACTIONS.items():
            cb.addItem(k, k)
            cb.setItemData(cb.count() - 1, v[1], Qt.ItemDataRole.ToolTipRole)
        cb.setCurrentIndex(max(0, cb.findData(step.get("type"))))
        self.steps.setCellWidget(r, 0, cb)
        self.steps.setCellWidget(r, 1, QLineEdit(str(step.get("param", ""))))

    def _read_steps(self):
        return [{"type": self.steps.cellWidget(r, 0).currentData(), "param": self.steps.cellWidget(r, 1).text()}
                for r in range(self.steps.rowCount())]

    def del_step(self):
        r = self.steps.currentRow()
        if r < 0:
            r = self.steps.rowCount() - 1
        if r >= 0:
            self.steps.removeRow(r)

    def move_step(self, d):
        r = self.steps.currentRow()
        st = self._read_steps()
        if 0 <= r < len(st) and 0 <= r + d < len(st):
            st[r], st[r + d] = st[r + d], st[r]
            self.steps.setRowCount(0)
            for s in st:
                self.add_step(s)
            self.steps.selectRow(r + d)

    def new_cmd(self):
        self.cmd_list.clearSelection()
        self._fill({"id": None, "name": "Новая команда", "phrases": [], "steps": [], "reply": ""})

    def save_cmd(self):
        c = self.current_cmd or {"id": None}
        phrases = [p.strip() for p in self.ed_phrases.text().split(",") if p.strip()]
        if not phrases:
            QMessageBox.warning(self, "ХРАЗ", "Добавьте хотя бы одну фразу.")
            return
        data = dict(name=self.ed_name.text().strip() or phrases[0].capitalize(), phrases=phrases,
                    steps=self._read_steps(), reply=self.ed_reply.text().strip())
        if c.get("id"):
            c.update(data)
            self.store.upsert(c)
        else:
            c = self.store.add(**data)
        self.current_cmd = c
        self.reload_cmds()

    def delete_cmd(self):
        if self.current_cmd and self.current_cmd.get("id"):
            self.store.delete(self.current_cmd["id"])
            self.current_cmd = None
            self.reload_cmds()

    def test_cmd(self):
        said = actions.run_steps(self._read_steps(), self.brain)
        self.brain.notify(". ".join(said) or self.ed_reply.text() or persona.say("ack"))

    # ---------------- архив ----------------
    # ---------------- память ----------------
    def _archive_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        lbl = QLabel("ДОЛГОВРЕМЕННАЯ ПАМЯТЬ — ОТДЕЛЬНО ОТ ЧАТОВ")
        lbl.setObjectName("h")
        hint = QLabel("Сохраняется только то, что вы попросили («Храз, запомни…») или подтвердили. "
                      "В разговор подмешиваются подходящие записи (поиск bge-m3) и все предпочтения.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        self.mem_search = QLineEdit()
        self.mem_search.setPlaceholderText("Поиск по памяти (по смыслу, если доступна bge-m3)…")
        self.mem_search.returnPressed.connect(self.search_memory)
        self.mem_table = QTableWidget(0, 4)
        self.mem_table.setHorizontalHeaderLabels(["ЗАПИСЬ", "ТИП", "ДОБАВЛЕНА", "ИСТОЧНИК"])
        self.mem_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.mem_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.mem_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.mem_table.verticalHeader().setVisible(False)
        self.mem_state = QLabel("")
        self.mem_state.setObjectName("hint")
        row = QHBoxLayout()
        self.arch_inp = QLineEdit()
        self.arch_inp.setPlaceholderText("Новая запись, например: ученики занимаются по вторникам и четвергам")
        self.arch_inp.returnPressed.connect(self.arch_add)
        self.arch_pref = QCheckBox("предпочтение")
        self.arch_pref.setToolTip("Предпочтения (как отвечать, как обращаться) подмешиваются в каждый разговор")
        b_add = QPushButton("ЗАНЕСТИ")
        b_add.setObjectName("primary")
        b_add.clicked.connect(self.arch_add)
        row.addWidget(self.arch_inp, 1)
        row.addWidget(self.arch_pref)
        row.addWidget(b_add)
        row2 = QHBoxLayout()
        b_del = QPushButton("УДАЛИТЬ ВЫБРАННЫЕ")
        b_del.clicked.connect(self.arch_del)
        b_clear = QPushButton("ОЧИСТИТЬ ПАМЯТЬ…")
        b_clear.clicked.connect(self.arch_clear)
        row2.addWidget(self.mem_state, 1)
        row2.addWidget(b_del)
        row2.addWidget(b_clear)
        for x in (lbl, hint, self.mem_search):
            v.addWidget(x)
        v.addWidget(self.mem_table, 1)
        v.addLayout(row)
        v.addLayout(row2)
        return w

    def _fill_memory(self, items, scores=None):
        self.mem_table.setRowCount(0)
        for i, m in enumerate(items):
            self.mem_table.insertRow(i)
            text = m["text"] + (f"   ({scores[i]:.2f})" if scores else "")
            cells = [text, "предпочтение" if m.get("kind") == "preference" else "факт", m.get("created", ""),
                     m.get("source", "")]
            for j, c in enumerate(cells):
                it = QTableWidgetItem(c)
                it.setData(Qt.ItemDataRole.UserRole, m["id"])
                self.mem_table.setItem(i, j, it)
        mem = self.brain.memory
        how = {None: "bge-m3: ещё не проверена", True: "поиск по смыслу: bge-m3", False: "bge-m3 недоступна — поиск по словам"}
        self.mem_state.setText(f"Записей: {len(mem.items)} · {how[mem.embed_ok]}")

    def reload_archive(self):
        self.mem_search.clear()
        self._fill_memory(list(reversed(self.brain.memory.items)))

    def search_memory(self):
        q = self.mem_search.text().strip()
        if not q:
            return self.reload_archive()
        res = self.brain.memory.search(q, k=20, min_score=0.3)
        self._fill_memory([m for m, _ in res], [sc for _, sc in res])

    def arch_add(self):
        t = self.arch_inp.text().strip()
        if t:
            self.brain.memory.add(t, kind="preference" if self.arch_pref.isChecked() else "fact", source="вручную")
            self.arch_inp.clear()
            self.reload_archive()

    def arch_del(self):
        ids = {self.mem_table.item(r.row(), 0).data(Qt.ItemDataRole.UserRole)
               for r in self.mem_table.selectionModel().selectedRows()}
        if not ids:
            return
        if QMessageBox.question(self, "ХРАЗ", f"Удалить из памяти записей: {len(ids)}?") != QMessageBox.StandardButton.Yes:
            return
        for i in ids:
            self.brain.memory.delete(i)
        self.reload_archive()

    def arch_clear(self):
        if QMessageBox.question(self, "ХРАЗ", f"Очистить всю память ({len(self.brain.memory.items)} записей)? "
                                              "Чаты останутся.") != QMessageBox.StandardButton.Yes:
            return
        self.brain.memory.clear()
        self.reload_archive()

    # ---------------- журнал инструментов ----------------
    def _log_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        lbl = QLabel("ЖУРНАЛ ДЕЙСТВИЙ — ЧТО ХРАЗ ВЫЗЫВАЛ")
        lbl.setObjectName("h")
        hint = QLabel("Каждый вызов инструмента: аргументы после проверки, итог, длительность. Файл logs/tools.jsonl.")
        hint.setObjectName("hint")
        self.log_table = QTableWidget(0, 6)
        self.log_table.setHorizontalHeaderLabels(["ВРЕМЯ", "ИНСТРУМЕНТ", "АРГУМЕНТЫ", "ИТОГ", "МС", "РЕЗУЛЬТАТ"])
        self.log_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.log_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.log_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.log_table.verticalHeader().setVisible(False)
        b = QPushButton("ОБНОВИТЬ")
        b.clicked.connect(self.reload_log)
        v.addWidget(lbl)
        v.addWidget(hint)
        v.addWidget(self.log_table, 1)
        v.addWidget(b, 0, Qt.AlignmentFlag.AlignRight)
        return w

    def reload_log(self):
        import tools
        recs = list(reversed(tools.read_log(300)))
        self.log_table.setRowCount(len(recs))
        status = {"ok": "выполнено", "needs_confirm": "ждёт подтверждения", "invalid": "отклонено проверкой",
                  "error": "ошибка", "unknown": "нет такого"}
        for i, r in enumerate(recs):
            cells = [r.get("ts", "")[5:], r.get("tool", ""), json.dumps(r.get("args", {}), ensure_ascii=False),
                     status.get(r.get("status"), r.get("status", "")) + (" (подтв.)" if r.get("via") == "confirmed" else ""),
                     str(r.get("ms", "")), r.get("result", "")]
            for j, c in enumerate(cells):
                self.log_table.setItem(i, j, QTableWidgetItem(c))

    def _tab_changed(self, i):
        w = self.tabs.widget(i)
        if w is self.mem_tab:
            self.reload_archive()
        elif w is self.log_tab:
            self.reload_log()

    @staticmethod
    def _scroll(widget):
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(widget)
        sa.setStyleSheet("QScrollArea { border: none; }")
        return sa

    # ---------------- настройки ----------------
    def _settings_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        f.setVerticalSpacing(9)
        self.s_url = QLineEdit(self.cfg["ollama_url"])
        self.s_model = QComboBox()
        self.s_model.setEditable(True)
        self.s_vision = QComboBox()
        self.s_vision.setEditable(True)
        self.s_smart = QComboBox()
        self.s_smart.setEditable(True)
        self.s_code = QComboBox()
        self.s_code.setEditable(True)
        self.s_embed = QComboBox()
        self.s_embed.setEditable(True)
        self._fill_models()
        self.s_mode = QComboBox()
        for key, name in (("auto", "Авто: основная, сложное — умной"), ("fast", "Всегда основная"),
                          ("smart", "Всегда умная (gpt-oss)"), ("code", "Режим кода")):
            self.s_mode.addItem(name, key)
        self.s_mode.setCurrentIndex(max(0, self.s_mode.findData(self.cfg.get("model_mode", "auto"))))
        self.s_short = QCheckBox("Краткие ответы: 1–4 предложения («продолжи» — подробнее)")
        self.s_short.setChecked(self.cfg.get("short_answers", True))
        b_check = QPushButton("ПРОВЕРИТЬ OLLAMA И МОДЕЛИ")
        b_check.clicked.connect(lambda: threading.Thread(target=self.startup_check, args=(True,), daemon=True).start())
        # разрешённые программы
        self.s_apps = QTableWidget(0, 2)
        self.s_apps.setHorizontalHeaderLabels(["НАЗВАНИЕ", "КОМАНДА ИЛИ ПУТЬ"])
        self.s_apps.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.s_apps.verticalHeader().setVisible(False)
        self.s_apps.setMinimumHeight(170)
        for name, cmd in (self.cfg.get("allowed_apps") or {}).items():
            r = self.s_apps.rowCount()
            self.s_apps.insertRow(r)
            self.s_apps.setItem(r, 0, QTableWidgetItem(name))
            self.s_apps.setItem(r, 1, QTableWidgetItem(cmd))
        b_app_add = QPushButton("+ ПРОГРАММА")
        b_app_add.clicked.connect(self._add_app)
        b_app_del = QPushButton("УБРАТЬ")
        b_app_del.clicked.connect(lambda: self.s_apps.removeRow(self.s_apps.currentRow()))
        # папки поиска
        self.s_roots = QListWidget()
        self.s_roots.setMaximumHeight(96)
        self.s_roots.addItems(self.cfg.get("search_roots") or [])
        b_root_add = QPushButton("+ ПАПКА")
        b_root_add.clicked.connect(self._add_root)
        b_root_del = QPushButton("УБРАТЬ")
        b_root_del.clicked.connect(lambda: self.s_roots.takeItem(self.s_roots.currentRow()))
        self.s_notes = QLineEdit(self.cfg.get("notes_dir", ""))
        self.s_forbid = QLineEdit(", ".join(self.cfg.get("forbidden_paths") or []))
        self.s_forbid.setToolTip("Сюда ХРАЗ не заглядывает и не пишет")
        b_ref = QPushButton("↻")
        b_ref.clicked.connect(self._fill_models)
        mrow = QHBoxLayout()
        mrow.addWidget(self.s_model, 1)
        mrow.addWidget(b_ref)
        self.s_persona = QCheckBox("Характер ХРАЗа (KHRAZ_PERSONA.md). Выключить — нейтральный ассистент")
        self.s_persona.setChecked(self.cfg["personality"])
        self.s_wake = QLineEdit(", ".join(self.cfg["wake_words"]))
        self.s_tts = QComboBox()
        self.s_tts.addItems(["fish", "piper", "sapi", "silero"])
        self.s_tts.setCurrentText(self.cfg["tts_engine"])
        self.s_fish_key = QLineEdit(self.cfg["fish_api_key"])
        self.s_fish_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.s_fish_voice = QLineEdit(self.cfg["fish_voice_id"])
        self.s_fish_voice.setPlaceholderText("ID модели голоса с fish.audio")
        self.s_fish_model = QComboBox()
        self.s_fish_model.addItems(["s1", "s2-pro", "s2.1-pro", "s2.1-pro-free"])
        self.s_fish_model.setCurrentText(self.cfg["fish_model"])
        self.s_fish_lat = QComboBox()
        self.s_fish_lat.addItems(["low", "balanced", "normal"])
        self.s_fish_lat.setCurrentText(self.cfg["fish_latency"])
        b_warm = QPushButton("ПРОГРЕТЬ ФРАЗЫ ХРАЗА")
        b_warm.setToolTip("Один раз озвучить все готовые реплики через Fish Audio — потом они звучат мгновенно")
        b_warm.clicked.connect(self.prewarm)
        self.s_piper = QComboBox()
        for vname in ("dmitri", "ruslan", "denis", "irina"):
            self.s_piper.addItem(vname, f"models/piper/ru_RU-{vname}-medium.onnx")
        self.s_piper.setCurrentIndex(max(0, self.s_piper.findData(self.cfg["piper_voice"])))
        self.s_fx = QCheckBox("Металлический эффект для Piper")
        self.s_fx.setChecked(self.cfg["jarvis_fx"])
        self.s_long = QCheckBox("Озвучивать длинные ответы целиком (иначе — начало, остальное на экране)")
        self.s_long.setChecked(self.cfg["speak_long_answers"])
        self.s_voice_ok = QCheckBox("Опасные действия на ПК можно подтверждать голосом «да»")
        self.s_voice_ok.setChecked(self.cfg["voice_confirm_local"])
        self.s_router = QCheckBox("Если команда не найдена — спросить модель")
        self.s_router.setChecked(self.cfg["llm_router"])
        self.s_city = QLineEdit(self.cfg["city"])
        self.s_mic = QComboBox()
        self.s_mic.addItem("По умолчанию", None)
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    self.s_mic.addItem(d["name"], i)
        except Exception:
            pass
        self.s_mic.setCurrentIndex(max(0, self.s_mic.findData(self.cfg.get("mic_device"))))
        self.s_stt = QComboBox()
        self.s_stt.addItem("Vosk (быстро, проще)", "vosk")
        self.s_stt.addItem("Vosk + Whisper (точнее, нужен faster-whisper)", "whisper")
        self.s_stt.setCurrentIndex(max(0, self.s_stt.findData(self.cfg.get("stt_engine", "vosk"))))
        self.s_whisper = QComboBox()
        self.s_whisper.setEditable(True)
        self.s_whisper.addItems(["small", "medium", "large-v3-turbo"])
        self.s_whisper.setCurrentText(self.cfg.get("whisper_model", "small"))
        self.s_wdev = QComboBox()
        for t, v in (("авто (видеокарта, иначе процессор)", "auto"), ("видеокарта", "cuda"), ("процессор", "cpu")):
            self.s_wdev.addItem(t, v)
        self.s_wdev.setCurrentIndex(max(0, self.s_wdev.findData(self.cfg.get("whisper_device", "auto"))))
        f.addRow(self._h("НЕЙРОСЕТИ"))
        f.addRow("Ollama URL", self.s_url)
        f.addRow("Основная", mrow)
        f.addRow("Для сложных задач", self.s_smart)
        f.addRow("Для кода (по команде)", self.s_code)
        f.addRow("Поиск по памяти", self.s_embed)
        f.addRow("Для экрана", self.s_vision)
        f.addRow("Выбор модели", self.s_mode)
        f.addRow("", self.s_short)
        f.addRow("", b_check)
        f.addRow(self._h("ИНСТРУМЕНТЫ"))
        f.addRow("Разрешённые программы", self.s_apps)
        f.addRow("", self._pair(b_app_add, b_app_del))
        f.addRow("Папки поиска файлов", self.s_roots)
        f.addRow("", self._pair(b_root_add, b_root_del))
        f.addRow("Папка заметок", self.s_notes)
        self.s_autosave = QCheckBox("Сохранять результаты заметками (подпапка «Отчёты ХРАЗ»): правила, утренняя сводка, ответы Клода, таблицы")
        self.s_autosave.setChecked(bool(self.cfg.get("notes_autosave", True)))
        f.addRow("", self.s_autosave)
        f.addRow("Запрещённые папки", self.s_forbid)
        f.addRow(self._h("ГОЛОС И ХАРАКТЕР"))
        f.addRow("", self.s_persona)
        f.addRow("Слова активации*", self.s_wake)
        f.addRow("Микрофон*", self.s_mic)
        f.addRow("Распознавание речи*", self.s_stt)
        f.addRow("Модель Whisper*", self._pair(self.s_whisper, self.s_wdev))
        f.addRow("Голос*", self.s_tts)
        f.addRow("Fish Audio ключ*", self.s_fish_key)
        f.addRow("Fish Audio голос (ID)*", self.s_fish_voice)
        f.addRow("Fish модель / задержка*", self._pair(self.s_fish_model, self.s_fish_lat))
        f.addRow("", b_warm)
        f.addRow("Запасной голос Piper*", self.s_piper)
        f.addRow("", self.s_fx)
        f.addRow("", self.s_long)
        f.addRow("", self.s_router)
        f.addRow("", self.s_voice_ok)
        f.addRow("Город для погоды", self.s_city)
        self.s_fishfx = QCheckBox("Голос Atomic Heart: металл и короткое эхо для Fish Audio")
        self.s_fishfx.setChecked(self.cfg.get("fish_fx", False))
        self.s_sfx = QCheckBox("Звуки интерфейса (обращение, карточка, готово, ошибка)")
        self.s_sfx.setChecked(self.cfg.get("sfx", True))
        self.s_hotkey = QLineEdit(self.cfg.get("hotkey", ""))
        self.s_hotkey.setPlaceholderText("win+shift+x — компактное окно поверх всех окон (пусто — выключено)")
        f.addRow("", self.s_fishfx)
        f.addRow("", self.s_sfx)
        f.addRow("Горячая клавиша", self.s_hotkey)
        # ХРАЗ сам
        f.addRow(self._h("ХРАЗ НАЧИНАЕТ САМ"))
        self.s_pro = QCheckBox("Следить за делами и сообщать о важном (узлы VPN, подписки, занятия)")
        self.s_pro.setChecked(self.cfg.get("proactive", True))
        self.s_morning = QLineEdit(self.cfg.get("morning_time", ""))
        self.s_morning.setPlaceholderText("08:30 — утренний доклад; пусто — только по «доброе утро»")
        self.s_quiet = QLineEdit(self.cfg.get("quiet_hours", ""))
        self.s_quiet.setPlaceholderText("23:00-08:00 — в эти часы только текст, без голоса")
        self.s_habits = QCheckBox("Замечать повторы и предлагать «сделать командой?»")
        self.s_habits.setChecked(self.cfg.get("suggest_commands", True))
        f.addRow("", self.s_pro)
        f.addRow("Утренний доклад в", self.s_morning)
        f.addRow("Тихие часы", self.s_quiet)
        f.addRow("", self.s_habits)
        # база знаний
        f.addRow(self._h("БАЗА ЗНАНИЙ"))
        kb_hint = QLabel("Папки с конспектами, договорами, заметками (txt, md, pdf, docx…). ХРАЗ один раз индексирует "
                         "их через bge-m3 и дальше отвечает по ним со ссылкой «файл, стр.». Повторная индексация "
                         "берёт только изменённые файлы.")
        kb_hint.setObjectName("hint")
        kb_hint.setWordWrap(True)
        self.s_kb = QListWidget()
        self.s_kb.setMaximumHeight(110)
        self.s_kb.addItems(self.cfg.get("kb_folders") or [])
        b_kb_add = QPushButton("+ ПАПКА")
        b_kb_add.clicked.connect(self._kb_add)
        b_kb_del = QPushButton("УБРАТЬ")
        b_kb_del.clicked.connect(lambda: self.s_kb.takeItem(self.s_kb.currentRow()))
        b_kb_idx = QPushButton("ИНДЕКСИРОВАТЬ")
        b_kb_idx.clicked.connect(self._kb_index)
        self.s_kb_state = QLabel("")
        self.s_kb_state.setObjectName("hint")
        kb_row = QWidget()
        kh = QHBoxLayout(kb_row)
        kh.setContentsMargins(0, 0, 0, 0)
        for b in (b_kb_add, b_kb_del, b_kb_idx):
            kh.addWidget(b)
        f.addRow("", kb_hint)
        f.addRow("Папки", self.s_kb)
        f.addRow("", kb_row)
        f.addRow("", self.s_kb_state)
        self._kb_status()
        b = QPushButton("СОХРАНИТЬ")
        b.setObjectName("primary")
        b.clicked.connect(self.save_settings)
        f.addRow("", b)
        note = QLabel("* применится после перезапуска")
        note.setObjectName("hint")
        f.addRow("", note)
        return w

    # ---------------- коннекторы: сторонние MCP-серверы ----------------
    def _connectors_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(self._mcp_section())
        v.addStretch()
        return w

    @staticmethod
    def _wide_table(t, stretch, widths):
        """Таблицы коннекторов — на всю ширину вкладки, выше, с разумными колонками и переносом длинного."""
        hh = t.horizontalHeader()
        hh.setMinimumSectionSize(50)
        for col, wpx in widths.items():
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            t.setColumnWidth(col, wpx)
        hh.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setDefaultSectionSize(34)
        t.setMinimumHeight(240)
        t.setWordWrap(False)
        t.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        t.setToolTip("Двойной щелчок — редактировать ячейку; границы колонок можно тянуть мышью")
        t.setSizePolicy(t.sizePolicy().horizontalPolicy(), t.sizePolicy().verticalPolicy())

    def _update_conn_row(self):
        hub = getattr(self, "_hub_text", "")
        self._set_row("cab", f"MCP: {hub}" if hub else "MCP: ВЫКЛ", "ok" if hub else "off")

    # ---------------- сторонние MCP-серверы ----------------
    MCP_COLS = ["ИМЯ", "ТИП", "КОМАНДА ИЛИ URL", "АРГУМЕНТЫ", "КЛЮЧЕВЫЕ СЛОВА", "ДОВЕРИЕ", "ВКЛ"]
    TRUST_NAMES = {"ask": "спрашивать всё", "read_auto": "чтение сразу", "auto": "всё сразу*"}

    def _mcp_section(self):
        w = QWidget()
        f = QFormLayout(w)
        f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        f.setVerticalSpacing(9)
        f.addRow(self._h("MCP-СЕРВЕРЫ (СТОРОННИЕ)"))
        hint = QLabel("Любые MCP-серверы, как в Claude Desktop: stdio (npx, uvx, python, exe) или http/sse по адресу. "
                      "Их инструменты ХРАЗ вызывает так же, как свои: журнал, карточки, подтверждения. "
                      "«Ключевые слова» — когда обращаться к серверу (например: github, гитхаб, репозиторий). "
                      "Доверие: «спрашивать всё» — подтверждать каждый вызов; «чтение сразу» — без вопросов только "
                      "помеченное сервером как чтение; «всё сразу*» — кроме разрушительных. "
                      "Токены и ключи — кнопкой «Секреты…» (в хранилище Windows).")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        self.m_table = QTableWidget(0, len(self.MCP_COLS))
        self.m_table.setHorizontalHeaderLabels(self.MCP_COLS)
        self._wide_table(self.m_table, stretch=2, widths={0: 110, 1: 78, 3: 190, 4: 150, 5: 130, 6: 44})
        for srv in self.cfg.get("mcp_servers") or []:
            self._mcp_row(srv)
        btns = [("+ СЕРВЕР", lambda: self._mcp_row({"type": "stdio", "trust": "ask", "enabled": True})),
                ("УБРАТЬ", self._mcp_del), ("СЕКРЕТЫ…", self._mcp_secrets),
                ("ИМПОРТ ИЗ CLAUDE DESKTOP…", self._mcp_import), ("СОХРАНИТЬ И ПОДКЛЮЧИТЬ", self._mcp_apply)]
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        for text, fn in btns:
            b = QPushButton(text)
            if text.startswith("СОХРАНИТЬ"):
                b.setObjectName("primary")
            b.clicked.connect(fn)
            h.addWidget(b)
        self.m_state = QLabel("")
        self.m_state.setObjectName("hint")
        self.m_state.setWordWrap(True)
        f.addRow(hint)
        f.addRow(self.m_table)
        f.addRow(row)
        f.addRow(self.m_state)
        return w

    def _mcp_row(self, srv):
        r = self.m_table.rowCount()
        self.m_table.insertRow(r)
        target = srv.get("url") if srv.get("type") in ("http", "sse") else srv.get("command", "")
        self.m_table.setItem(r, 0, QTableWidgetItem(srv.get("name", "")))
        tcombo = QComboBox()
        tcombo.addItems(["stdio", "http", "sse"])
        tcombo.setCurrentText(srv.get("type") or "stdio")
        self.m_table.setCellWidget(r, 1, tcombo)
        self.m_table.setItem(r, 2, QTableWidgetItem(target or ""))
        self.m_table.setItem(r, 3, QTableWidgetItem(" ".join(_quote_arg(a) for a in srv.get("args") or [])))
        self.m_table.setItem(r, 4, QTableWidgetItem(srv.get("keywords", "")))
        trust = QComboBox()
        for k, v in self.TRUST_NAMES.items():
            trust.addItem(v, k)
        trust.setCurrentIndex(max(0, trust.findData(srv.get("trust", "ask"))))
        self.m_table.setCellWidget(r, 5, trust)
        it = QTableWidgetItem("")
        it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        it.setCheckState(Qt.CheckState.Checked if srv.get("enabled", True) else Qt.CheckState.Unchecked)
        self.m_table.setItem(r, 6, it)

    def _mcp_servers(self):
        import shlex
        out = []
        for r in range(self.m_table.rowCount()):
            txt = lambda c: (self.m_table.item(r, c).text().strip() if self.m_table.item(r, c) else "")
            name = txt(0)
            if not name:
                continue
            kind = self.m_table.cellWidget(r, 1).currentText()
            srv = {"name": name, "type": kind, "keywords": txt(4),
                   "trust": self.m_table.cellWidget(r, 5).currentData(),
                   "enabled": self.m_table.item(r, 6).checkState() == Qt.CheckState.Checked}
            if kind == "stdio":
                try:
                    args = shlex.split(txt(3), posix=sys.platform != "win32")
                except ValueError:
                    args = txt(3).split()
                srv.update(command=txt(2), args=[a.strip('"') for a in args])
            else:
                srv.update(url=txt(2))
            out.append(srv)
        return out

    def _mcp_current(self):
        r = self.m_table.currentRow()
        it = self.m_table.item(r, 0) if r >= 0 else None
        return it.text().strip() if it else ""

    def _mcp_del(self):
        name = self._mcp_current()
        if not name:
            return
        if QMessageBox.question(self, "ХРАЗ", f"Убрать MCP-сервер «{name}» и его секреты?") != QMessageBox.StandardButton.Yes:
            return
        import mcp_hub
        try:
            mcp_hub.save_secrets(name, {}, {})
        except Exception:
            pass
        self.m_table.removeRow(self.m_table.currentRow())

    def _mcp_secrets(self):
        import mcp_hub
        name = self._mcp_current()
        if not name:
            return QMessageBox.information(self, "ХРАЗ", "Выберите строку сервера.")
        cur = mcp_hub.load_secrets(name)
        shown = "\n".join([f"{k}=••••" for k in cur["env"]] + [f"{k}: ••••" for k in cur["headers"]])
        text, ok = QInputDialog.getMultiLineText(
            self, "ХРАЗ", f"Секреты «{name}» (заменят текущие).\nПеременные: KEY=значение · заголовки: Имя: значение\n"
                          f"Сейчас:\n{shown or '— нет —'}", "")
        if not ok or not text.strip():
            return
        env, headers = mcp_hub.parse_secrets(text)
        try:
            mcp_hub.save_secrets(name, env, headers)
        except Exception as e:
            return QMessageBox.warning(self, "ХРАЗ", f"Не сохранено: {e}")
        self.m_state.setText(f"Секреты «{name}» сохранены: {len(env)} перем., {len(headers)} заголовк.")

    def _mcp_import(self):
        import mcp_hub
        default = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Claude", "claude_desktop_config.json")
        path, _ = QFileDialog.getOpenFileName(self, "Конфиг MCP (Claude Desktop, Cursor…)",
                                              default if os.path.exists(default) else "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                servers, secrets = mcp_hub.import_claude_desktop(json.load(fh))
        except Exception as e:
            return QMessageBox.warning(self, "ХРАЗ", f"Не прочитан: {e}")
        have = {self.m_table.item(r, 0).text() for r in range(self.m_table.rowCount()) if self.m_table.item(r, 0)}
        added = 0
        for srv in servers:
            if srv["name"] in have:
                continue
            self._mcp_row(srv)
            sec = secrets.get(srv["name"]) or {}
            if sec.get("env") or sec.get("headers"):
                try:
                    mcp_hub.save_secrets(srv["name"], sec.get("env") or {}, sec.get("headers") or {})
                except Exception:
                    pass
            added += 1
        self.m_state.setText(f"Импортировано серверов: {added}. Доверие у новых — «спрашивать всё». "
                             "Проверьте и нажмите «Сохранить и подключить».")

    def _mcp_apply(self):
        self.cfg["mcp_servers"] = self._mcp_servers()
        config.save(self.cfg)
        self.m_state.setText("Подключаю…")

        def work():
            self.brain.connect_hub()
            st = self.brain.hub.status()
            self.bridge.assistant("**MCP-серверы**\n\n" + ("\n".join(("✅ " if ok else "❌ ") + f"{n} — {t}"
                                                                      for n, ok, t in st) or "нет серверов"))
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _pair(a, b):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(a, 1)
        h.addWidget(b, 1)
        return w

    def _fill_models(self):
        models = self.llm.models()
        for box, key in ((self.s_model, "model"), (self.s_vision, "vision_model"), (self.s_smart, "model_smart"),
                         (self.s_code, "model_code"), (self.s_embed, "embed_model")):
            cur = self.cfg.get(key) or ""
            box.clear()
            box.addItems(models or [cur])
            box.setCurrentText(cur)

    @staticmethod
    def _h(text):
        lab = QLabel(text)
        lab.setObjectName("h")
        lab.setContentsMargins(0, 10, 0, 2)
        return lab

    def _add_app(self):
        path, _ = QFileDialog.getOpenFileName(self, "Программа", "", "Программы (*.exe *.lnk);;Все (*)")
        name, ok = QInputDialog.getText(self, "ХРАЗ", "Как вы будете её называть (например, «фотошоп»):",
                                        text=os.path.splitext(os.path.basename(path))[0].lower() if path else "")
        if not ok or not name.strip():
            return
        r = self.s_apps.rowCount()
        self.s_apps.insertRow(r)
        self.s_apps.setItem(r, 0, QTableWidgetItem(name.strip().lower()))
        self.s_apps.setItem(r, 1, QTableWidgetItem(path or name.strip().lower()))

    def _kb_add(self):
        d = QFileDialog.getExistingDirectory(self, "Папка для базы знаний")
        if not d:
            return
        from tools.files import is_forbidden
        if is_forbidden(self.cfg, d):
            return QMessageBox.warning(self, "ХРАЗ", "Эта папка в списке запрещённых.")
        self.s_kb.addItem(d)

    def _kb_index(self):
        self.cfg["kb_folders"] = [self.s_kb.item(i).text() for i in range(self.s_kb.count())]
        config.save(self.cfg)
        self.brain.reindex_kb()

    def _kb_status(self):
        if not hasattr(self, "s_kb_state"):
            return
        files, chunks = self.brain.kb.stats()
        good, bad = self.brain.feedback.stats()
        self.s_kb_state.setText(f"В базе: файлов {files}, фрагментов {chunks}. Оценок ответов: 👍 {good} · 👎 {bad}.")

    def _add_root(self):
        d = QFileDialog.getExistingDirectory(self, "Папка для поиска файлов")
        if not d:
            return
        from tools.files import is_forbidden
        if is_forbidden(self.cfg, d):
            QMessageBox.warning(self, "ХРАЗ", "Эта папка в списке запрещённых.")
            return
        self.s_roots.addItem(d)

    def prewarm(self):
        phrases = persona.all_phrases()
        self.brain.notify(f"Прогреваю {len(phrases)} реплик через Fish Audio. Это займёт пару минут.")
        self.tts.prewarm(phrases, on_done=lambda n: self.bridge.assistant(f"Готово: в кэше {n} реплик."))

    def save_settings(self):
        self.cfg.update(
            ollama_url=self.s_url.text().strip(), model=self.s_model.currentText().strip(),
            vision_model=self.s_vision.currentText().strip(), personality=self.s_persona.isChecked(),
            wake_words=[x.strip().lower() for x in self.s_wake.text().split(",") if x.strip()],
            tts_engine=self.s_tts.currentText(), fish_api_key=self.s_fish_key.text().strip(),
            fish_voice_id=self.s_fish_voice.text().strip(), fish_model=self.s_fish_model.currentText(),
            fish_latency=self.s_fish_lat.currentText(), piper_voice=self.s_piper.currentData(),
            jarvis_fx=self.s_fx.isChecked(), speak_long_answers=self.s_long.isChecked(),
            llm_router=self.s_router.isChecked(), city=self.s_city.text().strip() or "Москва",
            mic_device=self.s_mic.currentData(), voice_confirm_local=self.s_voice_ok.isChecked(),
            stt_engine=self.s_stt.currentData(), whisper_model=self.s_whisper.currentText().strip() or "small",
            whisper_device=self.s_wdev.currentData(),
            model_smart=self.s_smart.currentText().strip(), model_code=self.s_code.currentText().strip(),
            embed_model=self.s_embed.currentText().strip(), short_answers=self.s_short.isChecked(),
            allowed_apps={self.s_apps.item(r, 0).text().strip().lower(): self.s_apps.item(r, 1).text().strip()
                          for r in range(self.s_apps.rowCount())
                          if self.s_apps.item(r, 0) and self.s_apps.item(r, 1) and self.s_apps.item(r, 0).text().strip()},
            search_roots=[self.s_roots.item(i).text() for i in range(self.s_roots.count())],
            notes_dir=self.s_notes.text().strip() or "~/Documents/ХРАЗ заметки", notes_autosave=self.s_autosave.isChecked(),
            forbidden_paths=[x.strip() for x in self.s_forbid.text().split(",") if x.strip()])
        self.cfg.update(
            fish_fx=self.s_fishfx.isChecked(), sfx=self.s_sfx.isChecked(), hotkey=self.s_hotkey.text().strip().lower(),
            proactive=self.s_pro.isChecked(), morning_time=self.s_morning.text().strip(),
            quiet_hours=self.s_quiet.text().strip(), suggest_commands=self.s_habits.isChecked(),
            kb_folders=[self.s_kb.item(i).text() for i in range(self.s_kb.count())])
        if self.cfg["proactive"]:
            self.brain.watcher.start()
        else:
            self.brain.watcher.stop()
        self._start_hotkey()
        self.brain.set_mode(self.s_mode.currentData(), quiet=True)
        self.brain.memory.embed_ok = None          # модель поиска могла смениться
        config.save(self.cfg)
        self.brain.wake_re = self.brain._wake_regex()
        self._update_model_label()
        QMessageBox.information(self, "ХРАЗ", "Настройки сохранены.")

    def _update_model_label(self):
        self.on_model(self.cfg["model"], "автовыбор" if self.brain.mode == "auto" else f"режим {self.brain.mode}")

    # ---------------- трей ----------------
    def _tray(self):
        pm = QPixmap(os.path.join(ASSETS, "img", "khraz_icon.png"))
        if not pm.isNull():
            return self._tray_with(QIcon(pm))
        pm = QPixmap(64, 64)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(C["brass"]), 5))
        p.setBrush(QColor("#1b1f23"))
        p.drawEllipse(6, 6, 52, 52)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C["red"]))
        p.drawEllipse(22, 22, 20, 20)
        p.end()
        self._tray_with(QIcon(pm))

    def _tray_with(self, icon):
        self.setWindowIcon(icon)
        QApplication.instance().setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        menu = QMenu()
        a_show = QAction("Открыть", self)
        a_show.triggered.connect(self.showNormal)
        a_mic = QAction("Микрофон вкл/выкл", self)
        a_mic.triggered.connect(self.toggle_mic)
        a_compact = QAction("Компактный режим", self)
        a_compact.triggered.connect(self.toggle_compact)
        a_quit = QAction("Выход", self)
        a_quit.triggered.connect(QApplication.instance().quit)
        menu.addActions([a_show, a_compact, a_mic, a_quit])
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.showNormal() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def closeEvent(self, e):
        e.ignore()
        self.hide()
        self.tray.showMessage("ХРАЗ", "Работаю в фоне. Выход — через иконку в трее.",
                              QSystemTrayIcon.MessageIcon.Information, 2000)


def _int(text, default):
    try:
        return max(1, int(str(text).strip()))
    except ValueError:
        return default


def _quote_arg(a):
    return f'"{a}"' if (" " in a or not a) else a


def _load_fonts():
    for f in ("RussoOne-Regular.ttf", "Oswald.ttf", "JetBrainsMono.ttf"):
        QFontDatabase.addApplicationFont(os.path.join(ASSETS, "fonts", f))


def run_gui(build):
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-logging")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    _load_fonts()
    w = Main(build)
    w.show()
    sys.exit(app.exec())
