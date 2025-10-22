from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from meetrecorder.automation import AutomationConfig
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
    )

    logs: list[str] = []

    def _logger(message: str) -> None:
        logs.append(message)

    scheduler = MeetingScheduler(
        SchedulerConfig(
            recordings_dir=tmp_path / "recordings",
            transcripts_dir=tmp_path / "transcripts",
            automation=AutomationConfig(download_dir=tmp_path),
            logger=_logger,
        )
    )

    results = await scheduler.run([meeting])
    assert len(results) == 1
    result = results[0]
    assert result.media_path.exists()
    assert result.succeeded
    assert any("Joined meeting" in entry for entry in logs)
