"""Command line interface for Meet Recorder."""

from __future__ import annotations

import asyncio
from datetime import timezone
from pathlib import Path
from typing import Optional

import typer

from .automation import AutomationConfig
from .config import dump_template, load_config
from .models import RecordingResult
from .scheduler import MeetingScheduler, SchedulerConfig
from .telegram import TelegramConfig, TelegramNotifier

app = typer.Typer(add_completion=False)


def _print(message: str) -> None:
    typer.echo(message)


def _setup_scheduler(
    recordings_dir: Path, transcripts_dir: Path, headless: bool
) -> MeetingScheduler:
    automation = AutomationConfig(download_dir=recordings_dir, headless=headless)
    scheduler_config = SchedulerConfig(
        recordings_dir=recordings_dir,
        transcripts_dir=transcripts_dir,
        automation=automation,
        logger=_print,
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

    meetings = load_config(config)
    typer.echo(f"Loaded {len(meetings)} meeting(s):")
    for meeting in meetings:
        typer.echo(
            f" - {meeting.title} @ {meeting.start_time.astimezone(timezone.utc).isoformat()} "
            f"for {meeting.duration}"
        )


@app.command()
def run(
    config: Path = typer.Argument(..., help="Config file path"),
    recordings_dir: Path = typer.Option(Path("recordings")),
    transcripts_dir: Path = typer.Option(Path("transcripts")),
    headless: bool = typer.Option(True, help="Whether to run the browser headless"),
    telegram_token: Optional[str] = typer.Option(None, envvar="MEET_RECORDER_TELEGRAM_TOKEN"),
    telegram_chat_id: Optional[str] = typer.Option(
        None, envvar="MEET_RECORDER_TELEGRAM_CHAT_ID"
    ),
) -> None:
    """Run the scheduler for the provided configuration."""

    meetings = load_config(config)
    scheduler = _setup_scheduler(recordings_dir, transcripts_dir, headless=headless)

    notifier: Optional[TelegramNotifier] = None
    if telegram_token and telegram_chat_id:
        notifier = TelegramNotifier(
            TelegramConfig(bot_token=telegram_token, chat_id=telegram_chat_id)
        )

    async def _progress(result: RecordingResult) -> None:
        await _notify_result(result, notifier)

    async def _main() -> None:
        results = await scheduler.run(meetings)
        for result in results:
            await _progress(result)

    asyncio.run(_main())


if __name__ == "__main__":
    app()
