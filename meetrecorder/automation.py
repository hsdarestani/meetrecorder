"""Media recording and transcription helpers for Meet Recorder."""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, List, Mapping, Optional, Sequence


class RecorderError(RuntimeError):
    """Raised when the recorder cannot start or stop cleanly."""


class RecorderNotRunningError(RecorderError):
    """Raised when attempting to stop a recorder that is not running."""


class TranscriptionError(RuntimeError):
    """Raised when the transcription command fails."""


@dataclass(slots=True)
class RecorderConfig:
    """Configuration options for the FFmpeg based recorder."""

    ffmpeg_path: Path = Path("ffmpeg")
    display: str = ":0.0"
    audio_source: str = "default"
    video_size: Optional[str] = None
    frame_rate: Optional[int] = 30
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    video_bitrate: Optional[str] = "4500k"
    audio_bitrate: Optional[str] = "128k"
    pixel_format: Optional[str] = "yuv420p"
    output_format: str = "mp4"
    x11_grab_args: Sequence[str] = field(default_factory=list)
    audio_args: Sequence[str] = field(default_factory=list)
    extra_output_args: Sequence[str] = field(default_factory=lambda: ["-preset", "veryfast"])
    pulse_server: Optional[str] = None
    env: Mapping[str, str] | None = None
    dry_run: bool = False
    log_level: str = "info"

    @property
    def extension(self) -> str:
        suffix = self.output_format.lstrip(".")
        return f".{suffix}" if suffix else ".mp4"


@dataclass(slots=True)
class RecordingHandle:
    """Holds references to an ongoing or completed recording."""

    media_path: Path
    log_path: Optional[Path]


@dataclass(slots=True)
class TranscriptionConfig:
    """Definition for running an external transcription command."""

    command: Sequence[str]
    timeout_seconds: Optional[int] = None
    env: Mapping[str, str] | None = None


class FFmpegRecorder:
    """Manage an FFmpeg process that records a display and audio source."""

    def __init__(self, config: RecorderConfig) -> None:
        self._config = config
        self._process: Optional[asyncio.subprocess.Process] = None
        self._stderr_file: Optional[IO[bytes]] = None
        self._log_path: Optional[Path] = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def _resolve_ffmpeg(self) -> str:
        ffmpeg_path = self._config.ffmpeg_path
        if ffmpeg_path.exists():
            return str(ffmpeg_path)
        resolved = shutil.which(str(ffmpeg_path))
        if resolved:
            return resolved
        raise RecorderError(f"FFmpeg binary not found: {ffmpeg_path}")

    def _build_command(self, output_path: Path) -> List[str]:
        cfg = self._config
        cmd: List[str] = [self._resolve_ffmpeg(), "-y", "-hide_banner", "-loglevel", cfg.log_level]
        if cfg.video_size:
            cmd += ["-video_size", cfg.video_size]
        if cfg.frame_rate:
            cmd += ["-framerate", str(cfg.frame_rate)]
        cmd += ["-f", "x11grab"]
        if cfg.x11_grab_args:
            cmd += list(cfg.x11_grab_args)
        cmd += ["-i", cfg.display]
        cmd += ["-f", "pulse"]
        if cfg.audio_args:
            cmd += list(cfg.audio_args)
        cmd += ["-i", cfg.audio_source]
        cmd += ["-c:v", cfg.video_codec]
        if cfg.video_bitrate:
            cmd += ["-b:v", cfg.video_bitrate]
        if cfg.pixel_format:
            cmd += ["-pix_fmt", cfg.pixel_format]
        cmd += ["-c:a", cfg.audio_codec]
        if cfg.audio_bitrate:
            cmd += ["-b:a", cfg.audio_bitrate]
        if cfg.extra_output_args:
            cmd += list(cfg.extra_output_args)
        cmd.append(str(output_path))
        return cmd

    async def start(self, output_path: Path) -> RecordingHandle:
        if self._process is not None and self._process.returncode is None:
            raise RecorderError("Recorder is already running")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self._config.dry_run:
            output_path.write_text(
                "Dry run enabled - this is a placeholder file instead of a real recording.\n"
            )
            log_path = output_path.with_suffix(output_path.suffix + ".log")
            log_path.write_text("Dry run - FFmpeg command not executed.\n")
            self._process = None
            self._stderr_file = None
            self._log_path = log_path
            return RecordingHandle(media_path=output_path, log_path=log_path)

        command = self._build_command(output_path)
        log_path = output_path.with_suffix(output_path.suffix + ".log")
        stderr_handle = open(log_path, "wb")

        env = os.environ.copy()
        if self._config.pulse_server:
            env["PULSE_SERVER"] = self._config.pulse_server
        if self._config.env:
            env.update({key: str(value) for key, value in self._config.env.items()})

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=stderr_handle,
            env=env,
        )
        self._process = process
        self._stderr_file = stderr_handle
        self._log_path = log_path
        return RecordingHandle(media_path=output_path, log_path=log_path)

    async def stop(self) -> None:
        if self._config.dry_run:
            self._process = None
            if self._stderr_file:
                self._stderr_file.close()  # type: ignore[call-arg]
                self._stderr_file = None
            return

        if self._process is None:
            raise RecorderNotRunningError("Recorder is not running")

        process = self._process
        if process.returncode is None:
            try:
                process.send_signal(signal.SIGINT)
            except ProcessLookupError:  # pragma: no cover - process already gone
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=15)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        if self._stderr_file:
            self._stderr_file.close()  # type: ignore[call-arg]
            self._stderr_file = None
        self._process = None

    async def ensure_stopped(self) -> None:
        if self.is_running:
            await self.stop()

    def command_preview(self, output_path: Path) -> List[str]:
        """Return the FFmpeg command that would be executed."""
        return self._build_command(output_path)


async def run_transcription(
    media_path: Path,
    transcript_path: Path,
    config: TranscriptionConfig,
) -> Path:
    """Execute the configured transcription command."""

    if not config.command:
        raise TranscriptionError("No transcription command configured")

    transcript_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        arg.replace("{input}", str(media_path))
        .replace("{output}", str(transcript_path))
        .replace("{output_dir}", str(transcript_path.parent))
        for arg in config.command
    ]

    env = os.environ.copy()
    if config.env:
        env.update({key: str(value) for key, value in config.env.items()})

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        if config.timeout_seconds:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=config.timeout_seconds
            )
        else:
            stdout, stderr = await process.communicate()
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise TranscriptionError("Transcription command timed out") from exc

    if process.returncode != 0:
        stderr_text = stderr.decode().strip()
        raise TranscriptionError(
            f"Transcription command failed with exit code {process.returncode}: {stderr_text}"
        )

    if not transcript_path.exists():
        transcript_path.write_text(stdout.decode())

    return transcript_path
