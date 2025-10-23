"""Meet Recorder automation package."""

from .automation import RecorderConfig, TranscriptionConfig
from .config import AppConfig, load_config
from .models import Meeting, RecordingResult
from .scheduler import MeetingScheduler

__all__ = [
    "AppConfig",
    "Meeting",
    "MeetingScheduler",
    "RecorderConfig",
    "RecordingResult",
    "TranscriptionConfig",
    "load_config",
]
