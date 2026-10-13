"""Shared, thread-safe state consumed by the status UI (ui/api.py) and produced
by the poller/election/printer-check loops. Deliberately a plain in-memory
object -- nothing here needs to survive a restart, the source of truth for
jobs is always Odoo."""
import threading
import time
from collections import deque


class AgentState:
    def __init__(self, max_job_history=50):
        self._lock = threading.Lock()
        self.server_ok = None
        self.server_last_checked = None
        self.printer_status = {}
        self.recent_jobs = deque(maxlen=max_job_history)

    def set_server_status(self, ok):
        with self._lock:
            self.server_ok = ok
            self.server_last_checked = time.time()

    def set_printer_status(self, key, ok, error=None):
        with self._lock:
            self.printer_status[key] = {"ok": ok, "error": error, "last_checked": time.time()}

    def record_job(self, label_type, printer_key, result, error=None):
        with self._lock:
            self.recent_jobs.appendleft({
                "time": time.time(), "label_type": label_type,
                "printer_key": printer_key, "result": result, "error": error,
            })

    def snapshot(self):
        with self._lock:
            return {
                "server_ok": self.server_ok,
                "server_last_checked": self.server_last_checked,
                "printer_status": dict(self.printer_status),
                "recent_jobs": list(self.recent_jobs),
            }
