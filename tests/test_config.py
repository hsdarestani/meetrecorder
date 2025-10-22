from datetime import datetime
from pathlib import Path

import pytest

from meetrecorder.config import load_config
from meetrecorder.models import Meeting


def write_config(tmp_path: Path, data: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(data)
    return path


def test_load_config_parses_meeting(tmp_path: Path) -> None:
    now = datetime.now().replace(microsecond=0)
    config = f"""
meetings:
  - title: Demo
    meet_url: https://meet.google.com/aaa-bbbb-ccc
    start_time: {now.isoformat()}
    duration: 45m
    timezone: UTC
    participants:
      - user@example.com
"""
    path = write_config(tmp_path, config)
    meetings = load_config(path)
    assert len(meetings) == 1
    meeting = meetings[0]
    assert isinstance(meeting, Meeting)
    assert meeting.title == "Demo"
    assert meeting.duration.total_seconds() == 45 * 60


def test_invalid_config_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError):
        load_config(missing)
