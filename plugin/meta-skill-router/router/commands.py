"""``/route`` slash command: ``dry-run <text>``, ``stats``, ``catalog``. Read-only diagnostics."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from .engine import Router
from .schemas import TaskIntent

USAGE = "Usage: /route dry-run <request text> | /route catalog | /route stats"


def make_handler(router: Router):
    def handler(raw_args: str = "") -> Optional[str]:
        parts = (raw_args or "").strip().split(None, 1)
        if not parts:
            return USAGE
        verb, rest = parts[0].lower(), (parts[1] if len(parts) > 1 else "")
        if verb == "dry-run":
            if not rest.strip():
                return USAGE
            cfg = router.config
            intent = TaskIntent(text=rest.strip(), platform="cli")
            result = router.decide(intent, cfg, purpose="meta-skill-router.dry-run")
            return json.dumps({
                "mode": cfg.mode, "decision": result.decision.to_dict(), "allowed": result.allowed,
                "candidates": [{"name": c.manifest.name, "score": c.score, "warnings": c.warnings} for c in result.candidates],
                "rejections": result.rejections, "latency_ms": result.latency_ms,
            }, ensure_ascii=False, indent=2)
        if verb == "catalog":
            entries = router.catalog.entries("cli", force=True)
            by_source = Counter(m.source for m in entries)
            lines = [f"{len(entries)} skills ({', '.join(f'{k}={v}' for k, v in sorted(by_source.items()))}); "
                     f"build {router.catalog.last_build}"]
            lines += [f"- {m.name} [{m.category}] {m.trust}{' (disabled)' if m.disabled else ''}" for m in entries[:200]]
            return "\n".join(lines)
        if verb == "stats":
            return _stats(router)
        return USAGE
    return handler


def _stats(router: Router) -> str:
    base = router.trace.path_for("x")
    trace_dir = base.parent if base else None
    if not trace_dir or not Path(trace_dir).exists():
        return "No traces yet."
    decisions: Counter = Counter()
    loads = unselected = reroutes = turns = 0
    for f in sorted(Path(trace_dir).glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            kind = rec.get("kind")
            if kind == "route.decision":
                turns += 1
                decisions[(rec.get("decision") or {}).get("decision", "?")] += 1
            elif kind == "skill.load":
                loads += 1
                unselected += 0 if rec.get("selected") else 1
            elif kind == "route.reroute" and rec.get("status") == "ok":
                reroutes += 1
    lines = [f"routed turns: {turns}", "decisions: " + ", ".join(f"{k}={v}" for k, v in sorted(decisions.items())),
             f"skill loads: {loads} (unselected: {unselected})", f"reroutes: {reroutes}"]
    return "\n".join(lines)
