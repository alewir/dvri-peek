# layout.py  — server-side layout state (no cv2/numpy)
import json
import os
import threading

DEFAULT_STATE = {"ui": {"header_collapsed": False}, "devices": {}}

def _deep_copy(d):
    return json.loads(json.dumps(d))

class LayoutStore:
    """Loads/saves dashboard layout state to a JSON file (atomic writes)."""
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._state = self._read()

    def _read(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
            if not isinstance(data, dict) or "devices" not in data:
                return _deep_copy(DEFAULT_STATE)
            data.setdefault("ui", {})
            data["ui"].setdefault("header_collapsed", False)
            data.setdefault("devices", {})
            return data
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            return _deep_copy(DEFAULT_STATE)

    def get(self):
        with self._lock:
            return _deep_copy(self._state)

    def save(self, state):
        state = state or {}
        merged = _deep_copy(DEFAULT_STATE)
        merged["ui"]["header_collapsed"] = bool(
            (state.get("ui") or {}).get("header_collapsed", False))
        merged["devices"] = state.get("devices") or {}
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(merged, f, indent=2)
            os.replace(tmp, self.path)
            self._state = merged
            return _deep_copy(merged)
