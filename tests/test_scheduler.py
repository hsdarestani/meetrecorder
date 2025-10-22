from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from meetrecorder.automation import RecorderConfig
from meetrecorder.models import Meeting
from meetrecorder.scheduler import MeetingScheduler, SchedulerConfig


@pytest.mark.asyncio
async def test_scheduler_runs_meeting(tmp_path: Path) -> None:
    meeting = Meeting(
        title="Quick Sync",
        meet_url="https://meet.google.com/test",
        start_time=datetime.now(timezone.utc) - timedelta(seconds=1),
        duration=timedelta(seconds=0.1),
        timezone="UTC",
        pre_record=[f"touch {tmp_path / 'pre-hook'}"],
        post_record=[f"touch {tmp_path / 'post-hook'}"],
    )

    logs: list[str] = []

    def _logger(message: str) -> None:
        logs.append(message)

    scheduler = MeetingScheduler(
        SchedulerConfig(
            recordings_dir=tmp_path / "recordings",
            transcripts_dir=None,
            recorder=RecorderConfig(dry_run=True),
            logger=_logger,
            transcription=None,
        )
    )

    results = await scheduler.run([meeting])
    assert len(results) == 1
    result = results[0]
    assert result.media_path.exists()
    assert result.succeeded
    assert any("Recording started" in entry for entry in logs)
    assert (tmp_path / "pre-hook").exists()
    assert (tmp_path / "post-hook").exists()


@pytest.mark.asyncio
async def test_pre_record_lead_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start_time = datetime.now(timezone.utc) + timedelta(seconds=0.6)
    meeting = Meeting(
        title="Future Meeting",
        meet_url="https://meet.google.com/test",
        start_time=start_time,
        duration=timedelta(seconds=0.2),
        timezone="UTC",
        pre_record=[
            "python -c 'import pathlib, time; pathlib.Path(\"{marker}\").write_text(\"ok\"); time.sleep(0.2)'".format(
                marker=tmp_path / "pre-marker"
            )
        ],
        pre_record_lead_seconds=5,
    )

    class StubRecorder:
        def __init__(self, *_: object, **__: object) -> None:
            self.extension = ".mp4"

        async def start(self, output: Path) -> None:
            output.write_text("stub")

        async def ensure_stopped(self) -> None:
            pass

    monkeypatch.setattr("meetrecorder.scheduler.FFmpegRecorder", StubRecorder)

    logs: list[str] = []

    def _logger(message: str) -> None:
        logs.append(message)

    scheduler = MeetingScheduler(
        SchedulerConfig(
            recordings_dir=tmp_path / "recordings",
            transcripts_dir=None,
            recorder=RecorderConfig(dry_run=True),
            logger=_logger,
            transcription=None,
            pre_record_lead_seconds=1,
        )
    )

    results = await scheduler.run([meeting])
    result = results[0]

    assert (tmp_path / "pre-marker").exists()
    delay = (result.started_at - start_time).total_seconds()
    assert delay < 0.3  # commands should finish before start and wait until start
