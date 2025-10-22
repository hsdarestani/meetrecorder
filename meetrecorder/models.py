"""Data models used across the Meet Recorder project."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional


@dataclass(slots=True)
class Meeting:
    """A scheduled meeting that should be joined and recorded."""

    title: str
    meet_url: str
    start_time: datetime
    duration: timedelta
    timezone: str
    participants: List[str] = field(default_factory=list)
    notes: Optional[str] = None

    @property
    def end_time(self) -> datetime:
        return self.start_time + self.duration

    def validate(self) -> None:
        if not self.title:
            raise ValueError("Meeting title must not be empty")
        if "https://" not in self.meet_url:
            raise ValueError("Meeting URL must be an HTTPS link")
        if self.duration.total_seconds() <= 0:
            raise ValueError("Meeting duration must be positive")


@dataclass(slots=True)
class RecordingResult:
    """Represents the output of a recording session."""

    meeting: Meeting
    media_path: Path
    transcript_path: Optional[Path]
    started_at: datetime
    ended_at: datetime
    errors: List[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        base = (
            f"Recording for '{self.meeting.title}' started at {self.started_at.isoformat()} "
            f"and ended at {self.ended_at.isoformat()}."
        )
        if self.errors:
            base += " Errors: " + ", ".join(self.errors)
        return base


def ensure_valid_meetings(meetings: Iterable[Meeting]) -> List[Meeting]:
    validated: List[Meeting] = []
    for meeting in meetings:
        meeting.validate()
        validated.append(meeting)
    return validated
