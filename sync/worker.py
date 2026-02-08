from PyQt5.QtCore import QObject, pyqtSignal, QRunnable


class SyncWorkerSignals(QObject):
    message = pyqtSignal(str)
    finished = pyqtSignal(bool, str)  # success, message


class SyncWorker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = SyncWorkerSignals()

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            if isinstance(result, tuple) and len(result) >= 2:
                ok, msg = result[0], result[1]
                self.signals.finished.emit(ok, msg)
            else:
                self.signals.finished.emit(True, "Sync completed.")
        except Exception as e:
            self.signals.finished.emit(False, f"Sync worker error: {e}")
