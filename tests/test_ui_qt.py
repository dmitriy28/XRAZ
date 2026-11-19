"""Проверки окон PyQt6 без экрана (QT_QPA_PLATFORM=offscreen): компактное окно (прокрутка длинного ответа, портрет, размер),
своя шапка главного окна (безрамочное, свернуть/развернуть, края для изменения размера).
Запуск:  python tests/test_ui_qt.py   (нужен PyQt6; без него тест пропускается)"""
import os
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-logging")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import PyQt6  # noqa: F401
except ImportError:
    print("PyQt6 не установлен — тест окон пропущен")
    sys.exit(0)
import test_assistant as T  # noqa: E402

check = T.check


def spin(app, sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def main():
    import brain as B
    import ui
    from commands import Store
    from llm import LLM
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    ui._load_fonts()

    class FB:
        def type(self, t): pass

    class FM:
        brain = FB()
        def stop_answer(self): pass
        def showNormal(self): pass
        def activateWindow(self): pass

    w = ui.CompactWindow(FM())
    w.show()
    w.subtitle("как решить квадратное уравнение", user=True)
    long = "**Итог:** через дискриминант.\n\n" + "\n".join(f"{i}. Шаг {i}: подробное объяснение шага, который нужно сделать." for i in range(1, 25))
    w.begin()
    for ch in long:
        w.token(ch)
    spin(app)
    bar = w.sub.verticalScrollBar()
    check("компактное окно: длинный ответ не обрезается, есть прокрутка", bar.maximum() > 100 and "Шаг 24" in w.sub.toPlainText())
    check("…во время набора следит за концом", bar.value() >= bar.maximum() - 4)
    w.finish(long)
    spin(app, 0.1)
    check("…готовый ответ читается с начала", bar.value() == 0)
    w.begin()
    for ch in long:
        w.token(ch)
    spin(app, 0.4)
    bar.setValue(bar.maximum() // 3)                 # пользователь листает вверх, пока идёт ответ
    keep = bar.value()
    for ch in "\n\n25. Ещё шаг.\n26. И ещё один шаг.":
        w.token(ch)
    spin(app, 0.4)
    check("…если листает вручную во время ответа — не дёргаем к концу", abs(bar.value() - keep) <= 3 and bar.value() < bar.maximum() - 20)
    check("приказ показан отдельной строкой", "квадратное" in w.sub_user.text())
    w._toggle_eye()
    check("портрет можно спрятать — больше места для текста", not w.eye.isVisible())
    w.resize(520, 700)
    spin(app, 0.1)
    check("размер меняется (уголок)", w.width() == 520 and w._grip.x() > 400)
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtTest import QTest
    sent = []
    w.main.brain.type = sent.append
    w.inp.setFocus()
    h1 = w.inp.height()
    QTest.keyClicks(w.inp, "line one")
    QTest.keyClick(w.inp, _Qt.Key.Key_Return, _Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClicks(w.inp, "line two")
    spin(app, 0.1)
    check("компактное окно: поле ввода — многострочное, растёт, Shift+Enter не отправляет", not sent and w.inp.text() == "line one\nline two" and w.inp.height() > h1)
    QTest.keyClick(w.inp, _Qt.Key.Key_Return)
    check("…Enter отправляет всё, перевод строки сохранён, поле очищается", sent == ["line one\nline two"] and w.inp.text() == "")

    fo = T.FakeOllama()

    class STT:
        def __init__(self):
            self.enabled = threading.Event()
            self.enabled.set()
            self.error = ""
        def start(self): return True

    class TTS2(T.TTS):
        def mute(self, on): pass

    def build(bridge):
        cfg = T.make_cfg(fo.url)
        cfg.update(proactive=False)
        b = B.Brain(cfg, LLM(cfg), TTS2(), Store(), bridge)
        return cfg, b.llm, b.tts, Store(), b, STT()
    m = ui.Main(build)
    m.show()
    spin(app, 1.0)
    Qt = ui.Qt
    check("главное окно без системной рамки", bool(m.windowFlags() & Qt.WindowType.FramelessWindowHint))
    check("своя шапка: 4 кнопки, высота 40", m.titlebar.height() == 40 and all(b.isVisible() for b in (
        m.titlebar.btn_compact, m.titlebar.btn_min, m.titlebar.btn_max, m.titlebar.btn_close)))
    check("8 зон изменения размера по краям и углам", len(m._grips) == 8 and all(g.isVisible() for g in m._grips))
    m.on_status("thinking")
    check("статус отражается в шапке", m.titlebar.state_lbl.text() == "АНАЛИЗ…")
    m.titlebar.toggle_max()
    spin(app, 0.2)
    check("развернуть → значок «восстановить», зоны размера скрыты", m.isMaximized() and m.titlebar.btn_max.kind == "restore" and not m._grips[0].isVisible())
    m.titlebar.toggle_max()
    spin(app, 0.2)
    from PyQt6.QtGui import QImage as _QI, QPainter as _QP, QColor as _QC
    from PyQt6.QtCore import QPoint as _QPt
    tb = m.titlebar
    check("после «восстановить» иконка снова «развернуть»", tb.btn_max.kind == "max")
    def bbox(btn, kind=None):
        if kind:
            btn.set_kind(kind)
        img = btn.grab().toImage().convertToFormat(_QI.Format.Format_ARGB32)
        xs, ys = [], []
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if c.alpha() > 40 and c.red() > 90:               # линии иконки светлее фона кнопки
                    xs.append(x)
                    ys.append(y)
        return (min(xs), min(ys), max(xs), max(ys), img.width(), img.height()) if xs else None
    bad = []
    for name, btn, kind in (("compact", tb.btn_compact, None), ("min", tb.btn_min, None), ("max", tb.btn_max, None),
                            ("restore", tb.btn_max, "restore"), ("close", tb.btn_close, None)):
        bb = bbox(btn, kind)
        if not bb:
            bad.append((name, "пусто"))
            continue
        x0, y0, x1, y1, w, h = bb
        if abs((x0 + x1) / 2 - (w - 1) / 2) > 1.2 or abs((y0 + y1) / 2 - (h - 1) / 2) > 1.2:
            bad.append((name, bb))
    tb.btn_max.set_kind("max")
    check("иконки заголовка нарисованы и стоят по центру кнопок (±1 px)", not bad, bad)
    sizes = {(b.width(), b.height()) for b in (tb.btn_compact, tb.btn_min, tb.btn_max, tb.btn_close)}
    check("все кнопки заголовка одного размера", len(sizes) == 1, sizes)
    if os.environ.get("KHRAZ_SHOTS"):
        strip = _QI(4 * 44 + 8, 36, _QI.Format.Format_ARGB32)
        strip.fill(_QC("#0e0b0a"))
        qq = _QP(strip)
        for i, b in enumerate((tb.btn_compact, tb.btn_min, tb.btn_max, tb.btn_close)):
            qq.drawPixmap(4 + i * 44, 4, b.grab())
        qq.end()
        strip = strip.scaled(strip.width() * 3, strip.height() * 3)
        strip.save("/tmp/titlebar_icons.png")
    spin(app, 0.2)
    check("восстановить", not m.isMaximized() and m.titlebar.btn_max.kind == "max")
    check("первая вкладка — «ДИАЛОГ»", m.tabs.tabText(0) == "ДИАЛОГ")
    # поле ввода и выбор модели в главном окне
    sent = []
    m.brain.type = sent.append
    m.inp.setFocus()
    h1 = m.inp.height()
    check("поле ввода сразу нужной высоты: строка + отступы стиля (текст не обрезан)", h1 >= m.inp.fontMetrics().lineSpacing() + 2 * m.inp.frameWidth())
    QTest.keyClicks(m.inp, "row 1")
    for n in range(2, 12):
        QTest.keyClick(m.inp, _Qt.Key.Key_Return, _Qt.KeyboardModifier.ShiftModifier)
        QTest.keyClicks(m.inp, f"row {n}")
    spin(app, 0.2)
    check("главное окно: поле ввода растёт и упирается в предел (дальше прокрутка)", h1 < m.inp.height() <= 7 * m.inp.fontMetrics().lineSpacing() + 60
          and m.inp.verticalScrollBarPolicy() == _Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    QTest.keyClick(m.inp, _Qt.Key.Key_Return)
    check("…Enter: многострочный приказ передан целиком", len(sent) == 1 and sent[0].count("\n") == 10 and sent[0].startswith("row 1\n") and m.inp.text() == "")
    spin(app, 0.2)
    check("…и поле снова одной строкой", m.inp.height() == h1, (m.inp.height(), h1))
    check("кнопка «Передать» активна только при тексте", not m.btn_send.isEnabled())
    QTest.keyClicks(m.inp, "x")
    spin(app, 0.1)
    check("…появился текст — кнопка активна", m.btn_send.isEnabled())
    m.inp.clear()
    m.tabs.setCurrentWidget(m.chat_tab)
    spin(app, 0.1)
    m.on_status("idle")
    check("«Стоп» скрыт, пока ХРАЗ ничего не делает", not m.btn_stop.isVisibleTo(m))
    m.on_status("thinking")
    check("…и появляется, когда думает или говорит", m.btn_stop.isVisibleTo(m))
    m.on_status("idle")
    heights = {b.height() for b in (m.btn_model, m.btn_send)}
    check("тулбар карточки: кнопки одной строки выровнены (30–32 px)", all(28 <= h <= 34 for h in heights), heights)
    m._build_model_menu()
    titles = [a.text() for a in m.model_menu.actions()]
    check("выбор модели: авто, быстрая, умная, код с реальными названиями", any(t.startswith("Авто") for t in titles)
          and any("qwen3.5:9b" in t and t.startswith("Быстрая") for t in titles) and any("gpt-oss:20b" in t for t in titles)
          and any(t.startswith("Код") for t in titles))
    check("кнопка показывает текущий режим", m.btn_model.text() == "АВТО ▾")
    smart = next(a for a in m.model_menu.actions() if a.text().startswith("Умная"))
    smart.trigger()
    spin(app, 0.3)
    check("выбор «Умная» переключает режим мозга и кнопку", m.brain.mode == "smart" and m.btn_model.text() == "УМНАЯ ▾")
    m._build_model_menu()
    check("отмеченный пункт в меню — выбранный", [a.text() for a in m.model_menu.actions() if a.isChecked()][0].startswith("Умная"))
    m.pick_mode("auto")
    check("обратно в авто", m.brain.mode == "auto" and m.btn_model.text() == "АВТО ▾")

    # ---- блок Клод / Кодекс в списке моделей (виден и без проектов)
    import coder
    for pth in (coder.STATE_PATH,):
        if os.path.exists(pth):
            os.remove(pth)
    m.cfg["coder_projects"] = {}
    m._build_model_menu()
    titles = [a.text() for a in m.model_menu.actions()]
    check("список моделей: блок «Клод / Кодекс» есть и без проектов", any(t.startswith("КЛОД") for t in titles)
          and any(t.startswith("Claude Code") for t in titles) and any(t.startswith("Codex") for t in titles), titles)
    check("…и подсказка выбрать папку проекта", any("Выбрать папку проекта" in t for t in titles))
    check("…модели Claude Code: sonnet, opus, haiku", all(any(t.startswith("Claude Code · " + x) for t in titles) for x in ("sonnet", "opus", "haiku")))
    name = coder.add_project(m.cfg, T.SANDBOX)
    coder.set_state(m.cfg, project=name)
    m._build_model_menu()
    titles = [a.text() for a in m.model_menu.actions()]
    check("проект добавлен — появился в списке, подсказка «Добавить проект»", any(t == f"Проект: {name}" for t in titles)
          and any(t.startswith("＋ Добавить проект") for t in titles) and not any("Выбрать папку проекта" in t for t in titles), titles)
    m.cfg["coder_projects"] = {}
    ocr = m.cfg.get("model_smart")
    m.cfg["model_smart"] = "glm-ocr:latest"
    m._build_model_menu()
    if os.environ.get("KHRAZ_SHOTS"):
        m.model_menu.adjustSize()
        m.model_menu.grab().save("/tmp/qt_pick_claude.png")
    check("OCR-модель в роли «Умная» помечена предупреждением", any(t.startswith("Умная") and "не для диалога" in t for t in [a.text() for a in m.model_menu.actions()]))
    m.cfg["model_smart"] = ocr

    # настройки: Whisper сохраняется
    from PyQt6.QtWidgets import QMessageBox
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    import config as CF
    CF.save = lambda cfg: None
    m.s_stt.setCurrentIndex(m.s_stt.findData("whisper"))
    m.save_settings()
    check("выбор Whisper сохраняется", m.cfg["stt_engine"] == "whisper")
    m.stop_answer()
    fo.close()
    print(f"\nВсе проверки окон пройдены: {len(T.PASSED)}")
    os._exit(0)       # QtWebEngine не любит штатное завершение в тестовом режиме


if __name__ == "__main__":
    main()
