"""Async scheduler responsible for joining and recording meetings."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable, Iterable, List, Optional

from .automation import (
    FFmpegRecorder,
    RecorderConfig,
    RecorderError,
    TranscriptionConfig,
    TranscriptionError,
    run_transcription,
)
from .models import Meeting, RecordingResult


Logger = Callable[[str], None]


def _safe_decode(data: bytes, limit: int = 400) -> str:
    text = data.decode(errors="ignore").strip()
    if len(text) > limit:
        return text[:limit] + "…"
    return text


@dataclass(slots=True)
class SchedulerConfig:
    recordings_dir: Path
    transcripts_dir: Optional[Path]
    recorder: RecorderConfig
    logger: Logger
    transcription: Optional[TranscriptionConfig] = None
    pre_record_lead_seconds: int = 0
    abort_on_pre_record_failure: bool = True


class MeetingScheduler:
    def __init__(self, config: SchedulerConfig) -> None:
        self._config = config
        self._tasks: List[asyncio.Task[RecordingResult]] = []

    async def schedule(self, meetings: Iterable[Meeting]) -> List[RecordingResult]:
        results: List[RecordingResult] = []
        self._tasks = []
        for meeting in meetings:
            task = asyncio.create_task(self._handle_meeting(meeting))
            self._tasks.append(task)
        for task in self._tasks:
            results.append(await task)
        return results

    async def _run_commands(
        self, meeting: Meeting, commands: Iterable[str], phase: str
    ) -> List[str]:
        logger = self._config.logger
        errors: List[str] = []
        for command in commands:
            logger(f"[{meeting.title}] Running {phase} command: {command}")
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if stdout:
                logger(f"[{meeting.title}] {phase} stdout: {_safe_decode(stdout)}")
            if stderr:
                logger(f"[{meeting.title}] {phase} stderr: {_safe_decode(stderr)}")
            if process.returncode != 0:
                error_message = (
                    f"{phase} command '{command}' exited with code {process.returncode}"
                )
                errors.append(error_message)
                logger(f"[{meeting.title}] {error_message}")
        return errors

    async def _handle_meeting(self, meeting: Meeting) -> RecordingResult:
        logger = self._config.logger
        recordings_dir = self._config.recordings_dir
        transcripts_dir = self._config.transcripts_dir
        recordings_dir.mkdir(parents=True, exist_ok=True)
        if transcripts_dir:
            transcripts_dir.mkdir(parents=True, exist_ok=True)

        start_time_utc = meeting.start_time.astimezone(timezone.utc)
        lead_seconds = meeting.pre_record_lead_seconds
        if lead_seconds is None:
            lead_seconds = max(self._config.pre_record_lead_seconds, 0)
        else:
            lead_seconds = max(lead_seconds, 0)

        now_utc = datetime.now(timezone.utc)
        pre_hook_start = start_time_utc - timedelta(seconds=lead_seconds)
        if now_utc < pre_hook_start:
            wait_before_hooks = (pre_hook_start - now_utc).total_seconds()
            logger(
                "Waiting {seconds:.0f}s before running pre-record hooks for '{title}'...".format(
                    seconds=wait_before_hooks, title=meeting.title
                )
            )
            await asyncio.sleep(wait_before_hooks)

        timestamp = meeting.start_time.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S")
        base_name = f"{timestamp}-{meeting.slug()}"
        record_path = recordings_dir / f"{base_name}{self._config.recorder.extension}"
        transcript_path = (
            transcripts_dir / f"{base_name}.txt" if transcripts_dir is not None else None
        )

        recorder = FFmpegRecorder(self._config.recorder)
        errors: List[str] = []
        started_at: Optional[datetime] = None
        record_started = False

        try:
            pre_errors = await self._run_commands(meeting, meeting.pre_record, "pre-record")
            errors.extend(pre_errors)

            abort_on_failure = (
                meeting.abort_on_pre_record_failure
                if meeting.abort_on_pre_record_failure is not None
                else self._config.abort_on_pre_record_failure
            )

            if pre_errors and abort_on_failure:
                skip_message = "Skipped recording because a pre-record command failed."
                errors.append(skip_message)
                logger(f"[{meeting.title}] {skip_message}")
            else:
                now_utc = datetime.now(timezone.utc)
                if now_utc < start_time_utc:
                    wait_until_start = (start_time_utc - now_utc).total_seconds()
                    logger(
                        "Waiting {seconds:.0f}s to begin recording '{title}'...".format(
                            seconds=wait_until_start, title=meeting.title
                        )
                    )
                    await asyncio.sleep(wait_until_start)
                await recorder.start(record_path)
                record_started = True
                started_at = datetime.now(timezone.utc)
                logger(f"[{meeting.title}] Recording started -> {record_path}")
                await asyncio.sleep(meeting.duration.total_seconds())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - capture runtime failures
            errors.append(str(exc))
            logger(f"[{meeting.title}] Error: {exc}")
        finally:
            try:
                await recorder.ensure_stopped()
                if record_started:
                    logger(f"[{meeting.title}] Recording stopped")
            except RecorderError as exc:
                errors.append(f"Recorder shutdown error: {exc}")
                logger(f"[{meeting.title}] Recorder shutdown error: {exc}")

            post_errors = await self._run_commands(meeting, meeting.post_record, "post-record")
            errors.extend(post_errors)

            if (
                self._config.transcription
                and transcript_path is not None
                and record_path.exists()
                and not self._config.recorder.dry_run
                and record_started
            ):
                try:
                    await run_transcription(
                        record_path, transcript_path, self._config.transcription
                    )
                    logger(
                        f"[{meeting.title}] Transcript saved -> {transcript_path}"
                    )
                except TranscriptionError as exc:
                    errors.append(f"Transcription failed: {exc}")
                    logger(f"[{meeting.title}] Transcription failed: {exc}")

        ended_at = datetime.now(timezone.utc)

        result_started_at = started_at or datetime.now(timezone.utc)

        return RecordingResult(
            meeting=meeting,
            media_path=record_path,
            transcript_path=transcript_path if transcript_path and transcript_path.exists() else None,
            started_at=result_started_at,
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
