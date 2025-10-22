from datetime import datetime
from pathlib import Path

import pytest

from meetrecorder.config import AppConfig, load_config
from meetrecorder.models import Meeting


def write_config(tmp_path: Path, data: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(data)
    return path


def test_load_config_parses_meeting(tmp_path: Path) -> None:
    now = datetime.now().replace(microsecond=0)
    config = f"""
settings:
  timezone: UTC
  recordings_dir: recordings
  pre_record_lead_seconds: 45
  recorder:
    display: ":0.0"
    audio_source: default
    dry_run: true
meetings:
  - title: Demo
    meet_url: https://meet.google.com/aaa-bbbb-ccc
    start_time: {now.isoformat()}
    duration: 45m
    timezone: UTC
    pre_record_lead_seconds: 15
    pre_record:
      - echo preparing
    post_record:
      - echo cleanup
"""
    path = write_config(tmp_path, config)
    app_config = load_config(path)
    assert isinstance(app_config, AppConfig)
    assert app_config.recorder.dry_run is True
    assert app_config.recordings_dir == (tmp_path / "recordings")
    assert app_config.pre_record_lead_seconds == 45
    assert len(app_config.meetings) == 1
    meeting = app_config.meetings[0]
    assert isinstance(meeting, Meeting)
    assert meeting.title == "Demo"
    assert meeting.duration.total_seconds() == 45 * 60
    assert meeting.pre_record == ["echo preparing"]
    assert meeting.post_record == ["echo cleanup"]
    assert meeting.pre_record_lead_seconds == 15


def test_invalid_config_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError):
        load_config(missing)
