"""Shared PyQt6 stubs for headless testing.

Installs tolerant stub modules in ``sys.modules`` so ``photo_stitcher``
can be imported and its wizard logic exercised without Qt system libraries
or a display. Any attribute access or call on a stub returns another stub.
"""
import sys
import types


class _StubMeta(type):
    def __getattr__(cls, name):
        return _QtStub()


class _QtStub(metaclass=_StubMeta):
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return _QtStub()

    def __getattr__(self, name):
        return _QtStub()


class _FakeSignal:
    """Minimal stand-in for a PyQt signal: connect/disconnect/emit work
    synchronously. Callers disconnect their slots when done (as the real
    code does), so slots never leak between workers."""

    def __init__(self, *args, **kwargs):
        self._slots: list = []

    def connect(self, slot):
        self._slots.append(slot)

    def disconnect(self, slot):
        self._slots.remove(slot)

    def emit(self, *args, **kwargs):
        for slot in list(self._slots):
            slot(*args, **kwargs)


class _FakeThreadPool:
    """QThreadPool stand-in that runs QRunnables synchronously (headless tests)."""

    _instance = None

    @classmethod
    def globalInstance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self, runnable):
        runnable.run()


def install() -> None:
    pyqt6 = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtgui = types.ModuleType("PyQt6.QtGui")
    qtwidgets = types.ModuleType("PyQt6.QtWidgets")
    for _name in ["Qt", "QUrl", "QObject", "QRunnable"]:
        setattr(qtcore, _name, _QtStub)
    qtcore.QThreadPool = _FakeThreadPool
    qtcore.pyqtSignal = _FakeSignal
    for _name in ["QPixmap", "QImage", "QDesktopServices"]:
        setattr(qtgui, _name, _QtStub())
    for _name in ["QApplication", "QFileDialog", "QFrame", "QGridLayout", "QHBoxLayout",
                  "QLabel", "QMainWindow", "QMessageBox", "QProgressBar", "QProgressDialog",
                  "QPushButton", "QSizePolicy",
                  "QStackedWidget", "QVBoxLayout", "QWidget",
                  "QRadioButton", "QButtonGroup"]:
        setattr(qtwidgets, _name, _QtStub)
    pyqt6.QtCore = qtcore
    pyqt6.QtGui = qtgui
    pyqt6.QtWidgets = qtwidgets
    sys.modules["PyQt6"] = pyqt6
    sys.modules["PyQt6.QtCore"] = qtcore
    sys.modules["PyQt6.QtGui"] = qtgui
    sys.modules["PyQt6.QtWidgets"] = qtwidgets
