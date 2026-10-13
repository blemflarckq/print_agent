"""Loads config.json (see config.example.json). Kept dead simple on purpose --
this file is what a non-technical deploy step edits, so no schema library, just
a plain JSON read with sane KeyErrors if something's missing."""
import json
import os
import sys

def _default_path():
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "config.json")


class Config:
    def __init__(self, path=None):
        self.path = path or _default_path()
        with open(self.path, "r", encoding="utf-8") as f:
            self._data = json.load(f)

    @property
    def odoo(self):
        return self._data["odoo"]

    @property
    def poll_interval(self):
        return self._data.get("poll_interval_seconds", 3)

    @property
    def election(self):
        return self._data.get("election", {})

    @property
    def printers(self):
        return self._data.get("printers", {})
