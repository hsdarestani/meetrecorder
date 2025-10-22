"""Configuration loading utilities for Meet Recorder."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List

from zoneinfo import ZoneInfo

import yaml

from .models import Meeting, ensure_valid_meetings


ISO_FMT = "%Y-%m-%dT%H:%M:%S"


def _coerce_duration(value: str | int | float) -> timedelta:
    if isinstance(value, (int, float)):
        minutes = float(value)
    else:
        if value.endswith("m"):
            minutes = float(value[:-1])
        elif value.endswith("h"):
            minutes = float(value[:-1]) * 60
        else:
            minutes = float(value)
    return timedelta(minutes=minutes)


def _deserialize_meeting(raw: dict) -> Meeting:
    raw_start = raw["start_time"]
    if isinstance(raw_start, datetime):
        start = raw_start
    else:
        start = datetime.fromisoformat(str(raw_start))
    tz_name = raw.get("timezone", "UTC")
    tz = ZoneInfo(tz_name)
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    else:
        start = start.astimezone(tz)

    duration = _coerce_duration(raw.get("duration", 60))
    return Meeting(
        title=raw["title"],
        meet_url=raw["meet_url"],
        start_time=start,
        duration=duration,
        timezone=tz_name,
        participants=list(raw.get("participants", [])),
        notes=raw.get("notes"),
    )


def load_config(path: str | Path) -> List[Meeting]:
    """Load a configuration file that enumerates the meetings to record."""

    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)

    data = yaml.safe_load(file_path.read_text())
    raw_meetings: Iterable[dict] = data.get("meetings", [])
    meetings = [_deserialize_meeting(item) for item in raw_meetings]
    return ensure_valid_meetings(meetings)


def dump_template(path: str | Path) -> None:
    template = {
        "meetings": [
            {
                "title": "Daily Standup",
                "meet_url": "https://meet.google.com/abc-defg-hij",
                "start_time": datetime.now().replace(microsecond=0).isoformat(),
                "duration": "30m",
                "timezone": "UTC",
                "participants": ["alice@example.com", "bob@example.com"],
                "notes": "Discuss blockers and priorities.",
            }
        ]
    }
    Path(path).write_text(yaml.safe_dump(template, sort_keys=False))
