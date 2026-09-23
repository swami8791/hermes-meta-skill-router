"""Structured routing trace: one JSONL file per session under the plugin data dir.

Every string field passes through Hermes' redaction (forced, so ``security.redact_secrets: false``
cannot leak into a trace file). Files are trimmed oldest-first past ``max_bytes``. Never raises."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_SAFE_SESSION_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _redact(text: str) -> str:
    try:
        from agent.redact import redact_sensitive_text
        return redact_sensitive_text(text, force=True)
    except Exception:
        return _fallback_redact(text)


_FALLBACK_SECRET_RE = re.compile(
    r"(?i)(\b(?:sk|ghp|gho|xox[abp]|AKIA)[A-Za-z0-9_\-]{8,}|\b[A-Za-z_]*(?:key|token|secret|password)\s*[=:]\s*\S{6,})")


def _fallback_redact(text: str) -> str:
    return _FALLBACK_SECRET_RE.sub(lambda m: m.group(0)[:4] + "***", text)


def _walk(value: Any) -> Any:
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, dict):
        return {str(k): _walk(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_walk(v) for v in value]
    return value


class TraceWriter:
    def __init__(self, data_dir: Any, *, enabled: bool = True, max_bytes: int = 5 * 1024 * 1024) -> None:
        """``data_dir``: Path, zero-arg callable returning a Path, or None (tracing disabled)."""
        self._data_dir = data_dir
        self.enabled = enabled
        self.max_bytes = max(64 * 1024, int(max_bytes))
        self._lock = threading.Lock()

    def _dir(self) -> Optional[Path]:
        d = self._data_dir() if callable(self._data_dir) else self._data_dir
        return (Path(d) / "traces") if d else None

    def path_for(self, session_id: str) -> Optional[Path]:
        base = self._dir()
        if not base:
            return None
        safe = _SAFE_SESSION_RE.sub("_", session_id or "no-session")[:120] or "no-session"
        return base / f"{safe}.jsonl"

    def write(self, kind: str, session_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        record = {"schema": "meta-skill-router.trace.v1", "kind": kind, "ts": time.time(), "session_id": session_id}
        record.update(_walk(payload))
        if not self.enabled:
            return record
        path = self.path_for(session_id)
        if path is None:
            return record
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        try:
            with self._lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(line)
                self._trim(path)
        except Exception:
            logger.debug("trace write failed", exc_info=True)
        return record

    def _trim(self, path: Path) -> None:
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size <= self.max_bytes:
            return
        data = path.read_bytes()
        keep = data[-(self.max_bytes // 2):]
        nl = keep.find(b"\n")
        keep = keep[nl + 1:] if nl >= 0 else keep
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(keep)
        os.replace(tmp, path)

    def read(self, session_id: str, *, limit: int = 200) -> list:
        path = self.path_for(session_id)
        if not path or not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
