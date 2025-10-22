"""Command line interface for Meet Recorder."""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import timezone
from pathlib import Path
from typing import Optional

import typer

from .automation import TranscriptionConfig
from .config import AppConfig, dump_template, load_config
from .models import RecordingResult
from .scheduler import MeetingScheduler, SchedulerConfig
from .telegram import TelegramConfig, TelegramNotifier

app = typer.Typer(add_completion=False)


def _print(message: str) -> None:
    typer.echo(message)


def _prepare_scheduler(
    app_config: AppConfig,
    recordings_dir: Optional[Path],
    transcripts_dir: Optional[Path],
    dry_run_override: Optional[bool],
    transcription_config: Optional[TranscriptionConfig],
) -> MeetingScheduler:
    recorder_config = app_config.recorder
    if dry_run_override is not None and recorder_config.dry_run != dry_run_override:
        recorder_config = dataclasses.replace(recorder_config, dry_run=dry_run_override)

    resolved_recordings_dir = recordings_dir or app_config.recordings_dir
    resolved_transcripts_dir = (
        transcripts_dir if transcripts_dir is not None else app_config.transcripts_dir
    )

    scheduler_config = SchedulerConfig(
        recordings_dir=resolved_recordings_dir,
        transcripts_dir=resolved_transcripts_dir,
        recorder=recorder_config,
        transcription=transcription_config,
        logger=_print,
        pre_record_lead_seconds=app_config.pre_record_lead_seconds,
    )
    return MeetingScheduler(scheduler_config)


async def _notify_result(
    result: RecordingResult, notifier: Optional[TelegramNotifier]
) -> None:
    _print(result.summary())
    if notifier:
        notifier.send_message(result.summary())
        if result.media_path.exists():
            notifier.send_document(result.media_path, caption=result.meeting.title)
        if result.transcript_path and result.transcript_path.exists():
            notifier.send_document(
                result.transcript_path, caption=f"Transcript: {result.meeting.title}"
            )


@app.command()
def generate_config(output: Path = typer.Argument(..., help="Path to write the template")) -> None:
    """Generate a starter YAML configuration file."""

    dump_template(output)
    typer.echo(f"Template configuration written to {output}")


@app.command()
def validate(config: Path = typer.Argument(..., help="Config file path")) -> None:
    """Validate a configuration file and display the meetings."""

    app_config = load_config(config)
    typer.echo(
        "Loaded {count} meeting(s). Recorder display={display}, audio_source={audio}".format(
            count=len(app_config.meetings),
            display=app_config.recorder.display,
            audio=app_config.recorder.audio_source,
        )
    )
    typer.echo(f"Recordings directory -> {app_config.recordings_dir}")
    if app_config.transcripts_dir:
        typer.echo(f"Transcripts directory -> {app_config.transcripts_dir}")
    if app_config.recorder.dry_run:
        typer.echo("Recorder is in dry-run mode; no real media will be captured.")
    for meeting in app_config.meetings:
        typer.echo(
            f" - {meeting.title} @ {meeting.start_time.astimezone(timezone.utc).isoformat()} "
            f"for {meeting.duration}"
        )
        if meeting.pre_record:
            typer.echo(f"   pre-record commands: {len(meeting.pre_record)}")
        if meeting.post_record:
            typer.echo(f"   post-record commands: {len(meeting.post_record)}")


@app.command()
def run(
    config: Path = typer.Argument(..., help="Config file path"),
    recordings_dir: Optional[Path] = typer.Option(
        None, help="Override the recordings directory"
    ),
    transcripts_dir: Optional[Path] = typer.Option(
        None, help="Override the transcripts directory"
    ),
    no_transcripts: bool = typer.Option(
        False,
        "--no-transcripts",
        help="Disable transcript generation even if configured",
    ),
    dry_run: Optional[bool] = typer.Option(
        None,
        "--dry-run/--no-dry-run",
        help="Override the recorder dry-run flag",
        show_default=False,
    ),
    telegram_token: Optional[str] = typer.Option(None, envvar="MEET_RECORDER_TELEGRAM_TOKEN"),
    telegram_chat_id: Optional[str] = typer.Option(
        None, envvar="MEET_RECORDER_TELEGRAM_CHAT_ID"
    ),
) -> None:
    """Run the scheduler for the provided configuration."""

    app_config = load_config(config)

    effective_transcripts_dir = None if no_transcripts else transcripts_dir
    transcription_config = None if no_transcripts else app_config.transcription

    scheduler = _prepare_scheduler(
        app_config,
        recordings_dir=recordings_dir,
        transcripts_dir=effective_transcripts_dir,
        dry_run_override=dry_run,
        transcription_config=transcription_config,
    )

    notifier: Optional[TelegramNotifier] = None
    if telegram_token and telegram_chat_id:
        notifier = TelegramNotifier(
            TelegramConfig(bot_token=telegram_token, chat_id=telegram_chat_id)
        )

    async def _progress(result: RecordingResult) -> None:
        await _notify_result(result, notifier)

    async def _main() -> None:
        results = await scheduler.run(app_config.meetings)
        for result in results:
            await _progress(result)

    asyncio.run(_main())


if __name__ == "__main__":
    app()
