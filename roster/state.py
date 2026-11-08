"""Per-visitor state. Each browser gets a cookie id; its data + roster live in memory and are mirrored to JSON files
(ROSTER_STATE_DIR, default ./.state) so a restart does not lose edits. No database needed."""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from .engine import generate, validate
from .sample_data import DEFAULT_MONTH, build_sample_data

STATE_DIR = Path(os.environ.get("ROSTER_STATE_DIR", ".state"))
_SESSIONS: dict[str, dict] = {}
_SID_RE = re.compile(r"^[a-f0-9]{32}$")
_PERSIST = ("data", "month", "roster", "report", "last_change", "stale_note")


def new_id() -> str:
    return uuid.uuid4().hex


def uid(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:8]


def revalidate(s: dict) -> None:
    s["validation"] = validate(s["data"], s["roster"]) if s.get("roster") else None


def fresh_state() -> dict:
    data = build_sample_data()
    g = generate(data, DEFAULT_MONTH)
    return {"data": data, "month": DEFAULT_MONTH, "roster": g["roster"], "report": g["report"], "validation": g["validation"],
            "last_change": None, "stale_note": "", "toast": ""}


def get(sid: str | None) -> tuple[str, dict, bool]:
    """Return (sid, state, created)."""
    if sid and _SID_RE.match(sid):
        if sid in _SESSIONS:
            return sid, _SESSIONS[sid], False
        f = STATE_DIR / f"{sid}.json"
        if f.exists():
            try:
                s = json.loads(f.read_text())
                s.setdefault("toast", "")
                _SESSIONS[sid] = s
                revalidate(s)
                return sid, s, False
            except (OSError, ValueError):
                pass
    sid = new_id()
    _SESSIONS[sid] = fresh_state()
    return sid, _SESSIONS[sid], True


def save(sid: str, s: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        (STATE_DIR / f"{sid}.json").write_text(json.dumps({k: s.get(k) for k in _PERSIST}))
    except OSError:
        pass  # read-only filesystem: app keeps working in memory


def reset(sid: str) -> dict:
    _SESSIONS[sid] = fresh_state()
    return _SESSIONS[sid]
