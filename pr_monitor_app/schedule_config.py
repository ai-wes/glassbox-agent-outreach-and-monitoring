from __future__ import annotations

from pr_monitor_app.config import settings
from pr_monitor_app.state import StateStore

STATE_KEY_BEAT_SCHEDULE = "npe:schedule:beat"
STATE_KEY_INGEST_TICK_SECONDS = "npe:schedule:ingest_tick_seconds"

DEFAULT_BEAT_INGEST_SECONDS = 600
DEFAULT_BEAT_PROCESS_SECONDS = 900


def get_ingest_tick_seconds(state: StateStore) -> int:
    raw = state.get_str(STATE_KEY_INGEST_TICK_SECONDS)
    if raw:
        try:
            val = int(raw)
            if val >= 1:
                return val
        except ValueError:
            pass
    return int(settings.ingest_tick_seconds)


def set_ingest_tick_seconds(state: StateStore, seconds: int) -> int:
    sec = max(1, int(seconds))
    state.set_str(STATE_KEY_INGEST_TICK_SECONDS, str(sec))
    return sec


def get_beat_schedule_seconds(state: StateStore) -> dict[str, int]:
    payload = state.get_json(STATE_KEY_BEAT_SCHEDULE) or {}
    ingest = payload.get("ingest_seconds", DEFAULT_BEAT_INGEST_SECONDS)
    process = payload.get("process_seconds", DEFAULT_BEAT_PROCESS_SECONDS)

    try:
        ingest_sec = max(1, int(ingest))
    except (TypeError, ValueError):
        ingest_sec = DEFAULT_BEAT_INGEST_SECONDS
    try:
        process_sec = max(1, int(process))
    except (TypeError, ValueError):
        process_sec = DEFAULT_BEAT_PROCESS_SECONDS

    return {"ingest_seconds": ingest_sec, "process_seconds": process_sec}


def set_beat_schedule_seconds(
    state: StateStore,
    *,
    ingest_seconds: int | None = None,
    process_seconds: int | None = None,
) -> dict[str, int]:
    current = get_beat_schedule_seconds(state)
    if ingest_seconds is not None:
        current["ingest_seconds"] = max(1, int(ingest_seconds))
    if process_seconds is not None:
        current["process_seconds"] = max(1, int(process_seconds))
    state.set_json(STATE_KEY_BEAT_SCHEDULE, current)
    return current

