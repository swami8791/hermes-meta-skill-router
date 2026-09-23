"""Per-session routing state that survives a fresh AIAgent per gateway message.

Kept in memory (locked) and mirrored to a JSON file under the plugin data dir. One record per session
holds the current turn, the allowed skill set for that turn, reroute and load counters."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 6 * 3600
MAX_SESSIONS = 512


def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class TurnState:
    __slots__ = ("turn_id", "decision", "allowed", "reroutes", "loads", "unselected_loads", "mode", "started")

    def __init__(self, turn_id: str, *, mode: str, decision: str, allowed: List[str]) -> None:
        self.turn_id = turn_id
        self.mode = mode
        self.decision = decision
        self.allowed = list(dict.fromkeys(allowed))
        self.reroutes = 0
        self.loads: List[str] = []
        self.unselected_loads: List[str] = []
        self.started = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {"turn_id": self.turn_id, "mode": self.mode, "decision": self.decision, "allowed": self.allowed,
                "reroutes": self.reroutes, "loads": self.loads, "unselected_loads": self.unselected_loads,
                "started": self.started}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TurnState":
        t = cls(str(d.get("turn_id", "")), mode=str(d.get("mode", "shadow")), decision=str(d.get("decision", "")),
                allowed=list(d.get("allowed") or []))
        t.reroutes = int(d.get("reroutes") or 0)
        t.loads = list(d.get("loads") or [])
        t.unselected_loads = list(d.get("unselected_loads") or [])
        t.started = float(d.get("started") or time.time())
        return t


class RouterState:
    def __init__(self, data_dir: Any = None) -> None:
        """``data_dir``: a Path, a zero-arg callable returning one (resolved per call so profile
        switches are honoured), or None for memory-only state."""
        self._lock = threading.RLock()
        self._sessions: Dict[str, TurnState] = {}
        self._touched: Dict[str, float] = {}
        self._data_dir = data_dir
        self._loaded = False

    # -- persistence ------------------------------------------------------
    @property
    def path(self) -> Optional[Path]:
        d = self._data_dir() if callable(self._data_dir) else self._data_dir
        return (Path(d) / "router-state.json") if d else None

    def _load(self) -> None:
        if self._loaded or not self.path:
            self._loaded = True
            return
        self._loaded = True
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            now = time.time()
            for sid, d in (raw.get("sessions") or {}).items():
                t = TurnState.from_dict(d)
                if now - t.started < STATE_TTL_SECONDS:
                    self._sessions[sid] = t
                    self._touched[sid] = t.started
        except FileNotFoundError:
            pass
        except Exception:
            logger.debug("router state unreadable; starting empty", exc_info=True)

    def _save(self) -> None:
        if not self.path:
            return
        try:
            _atomic_write(self.path, {"sessions": {sid: t.to_dict() for sid, t in self._sessions.items()}})
        except Exception:
            logger.debug("router state not persisted", exc_info=True)

    def _evict(self) -> None:
        now = time.time()
        for sid in [s for s, ts in self._touched.items() if now - ts > STATE_TTL_SECONDS]:
            self._sessions.pop(sid, None)
            self._touched.pop(sid, None)
        while len(self._sessions) > MAX_SESSIONS:
            oldest = min(self._touched, key=self._touched.get)
            self._sessions.pop(oldest, None)
            self._touched.pop(oldest, None)

    # -- API --------------------------------------------------------------
    def begin_turn(self, session_id: str, turn_id: str, *, mode: str, decision: str, allowed: List[str]) -> TurnState:
        with self._lock:
            self._load()
            t = TurnState(turn_id, mode=mode, decision=decision, allowed=allowed)
            self._sessions[session_id] = t
            self._touched[session_id] = time.time()
            self._evict()
            self._save()
            return t

    def current(self, session_id: str) -> Optional[TurnState]:
        with self._lock:
            self._load()
            return self._sessions.get(session_id)

    def update(self, session_id: str, fn) -> Optional[TurnState]:
        """Apply ``fn(turn_state)`` under the lock and persist."""
        with self._lock:
            self._load()
            t = self._sessions.get(session_id)
            if t is None:
                return None
            fn(t)
            self._touched[session_id] = time.time()
            self._save()
            return t

    def end_turn(self, session_id: str) -> Optional[TurnState]:
        with self._lock:
            self._load()
            t = self._sessions.pop(session_id, None)
            self._touched.pop(session_id, None)
            self._save()
            return t
