"""Async scheduler responsible for joining and recording meetings."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Iterable, List, Optional

from .automation import (
    AutomationConfig,
    capture_transcript,
    join_meeting,
    launch_browser,
    start_recording,
    stop_recording,
)
from .models import Meeting, RecordingResult


Logger = Callable[[str], None]


@dataclass(slots=True)
class SchedulerConfig:
    recordings_dir: Path
    transcripts_dir: Path
    automation: AutomationConfig
    logger: Logger


class MeetingScheduler:
    def __init__(self, config: SchedulerConfig) -> None:
        self._config = config
        self._tasks: List[asyncio.Task[RecordingResult]] = []

    async def schedule(self, meetings: Iterable[Meeting]) -> List[RecordingResult]:
        results: List[RecordingResult] = []
        for meeting in meetings:
            task = asyncio.create_task(self._handle_meeting(meeting))
            self._tasks.append(task)
        for task in self._tasks:
            results.append(await task)
        return results

    async def _handle_meeting(self, meeting: Meeting) -> RecordingResult:
        logger = self._config.logger
        recordings_dir = self._config.recordings_dir
        transcripts_dir = self._config.transcripts_dir
        recordings_dir.mkdir(parents=True, exist_ok=True)
        transcripts_dir.mkdir(parents=True, exist_ok=True)

        wait_seconds = (
            meeting.start_time.astimezone(timezone.utc) - datetime.now(timezone.utc)
        ).total_seconds()
        if wait_seconds > 0:
            logger(f"Waiting {wait_seconds:.0f}s for meeting '{meeting.title}' to start...")
            await asyncio.sleep(wait_seconds)

        record_path = recordings_dir / f"{meeting.start_time:%Y%m%dT%H%M%S}-{meeting.title}.txt"
        transcript_path = transcripts_dir / (
            f"{meeting.start_time:%Y%m%dT%H%M%S}-{meeting.title}-transcript.txt"
        )

        started_at = datetime.now(timezone.utc)
        errors: List[str] = []

        try:
            async with launch_browser(self._config.automation) as session_id:
                logger(f"[{meeting.title}] Browser session {session_id} launched")
                await join_meeting(session_id, meeting.meet_url)
                logger(f"[{meeting.title}] Joined meeting")
                await start_recording(session_id, record_path)
                logger(f"[{meeting.title}] Recording started -> {record_path}")
                await asyncio.sleep(meeting.duration.total_seconds())
                await stop_recording(session_id)
                logger(f"[{meeting.title}] Recording stopped")
                await capture_transcript(session_id, transcript_path)
                logger(f"[{meeting.title}] Transcript saved -> {transcript_path}")
        except Exception as exc:  # pragma: no cover - we still want to capture errors
            errors.append(str(exc))
            logger(f"[{meeting.title}] Error: {exc}")
        finally:
            ended_at = datetime.now(timezone.utc)

        return RecordingResult(
            meeting=meeting,
            media_path=record_path,
            transcript_path=transcript_path if transcript_path.exists() else None,
            started_at=started_at,
            ended_at=ended_at,
            errors=errors,
        )

    async def run(self, meetings: Iterable[Meeting]) -> List[RecordingResult]:
        return await self.schedule(meetings)


async def run_scheduler(
    meetings: Iterable[Meeting],
    scheduler: MeetingScheduler,
    progress_callback: Optional[Callable[[RecordingResult], Awaitable[None]]] = None,
) -> List[RecordingResult]:
    results = await scheduler.run(meetings)
    if progress_callback:
        for result in results:
            await progress_callback(result)
    return results
