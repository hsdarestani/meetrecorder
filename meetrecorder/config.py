"""Configuration loading utilities for Meet Recorder."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import shlex
from typing import Dict, Iterable, List, Optional

from zoneinfo import ZoneInfo

import yaml

from .automation import RecorderConfig, TranscriptionConfig
from .models import Meeting, ensure_valid_meetings


def _expand_path(base: Path, value: object) -> Path:
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path
    return (base / path).expanduser()


@dataclass(slots=True)
class AppConfig:
    """Full application configuration returned by :func:`load_config`."""

    meetings: List[Meeting]
    recordings_dir: Path
    transcripts_dir: Optional[Path]
    recorder: RecorderConfig
    transcription: Optional[TranscriptionConfig]
    default_timezone: str
    pre_record_lead_seconds: int


def _coerce_duration(value: object) -> timedelta:
    if isinstance(value, timedelta):
        return value
    if isinstance(value, (int, float)):
        return timedelta(minutes=float(value))
    text = str(value).strip()
    if not text:
        raise ValueError("Duration cannot be empty")
    if text.endswith("m"):
        minutes = float(text[:-1])
    elif text.endswith("h"):
        minutes = float(text[:-1]) * 60
    elif ":" in text:
        hours_str, minutes_str = text.split(":", 1)
        minutes = float(hours_str) * 60 + float(minutes_str)
    else:
        minutes = float(text)
    return timedelta(minutes=minutes)


def _ensure_string_list(value: object, field: str) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise TypeError(f"{field} must be a string or list of strings")
    commands: List[str] = []
    for item in items:
        text = str(item).strip()
        if text:
            commands.append(text)
    return commands


def _deserialize_meeting(
    raw: Dict, default_timezone: str, default_lead_seconds: int
) -> Meeting:
    if "title" not in raw or "meet_url" not in raw or "start_time" not in raw:
        missing = {key for key in ("title", "meet_url", "start_time") if key not in raw}
        raise KeyError(f"Missing meeting fields: {', '.join(sorted(missing))}")

    raw_start = raw["start_time"]
    if isinstance(raw_start, datetime):
        start = raw_start
    else:
        start = datetime.fromisoformat(str(raw_start))
    tz_name = raw.get("timezone", default_timezone)
    tz = ZoneInfo(tz_name)
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    else:
        start = start.astimezone(tz)

    duration = _coerce_duration(raw.get("duration", 60))
    pre_record = _ensure_string_list(raw.get("pre_record"), "pre_record")
    post_record = _ensure_string_list(raw.get("post_record"), "post_record")

    lead_seconds_raw = raw.get("pre_record_lead_seconds")
    lead_seconds: Optional[int]
    if lead_seconds_raw is None:
        lead_seconds = None
    else:
        try:
            lead_seconds = int(lead_seconds_raw)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                "meetings[*].pre_record_lead_seconds must be an integer"
            ) from exc
        if lead_seconds < 0:
            raise ValueError("meetings[*].pre_record_lead_seconds must be zero or positive")

    return Meeting(
        title=str(raw["title"]),
        meet_url=str(raw["meet_url"]),
        start_time=start,
        duration=duration,
        timezone=str(tz_name),
        participants=list(raw.get("participants", [])),
        notes=raw.get("notes"),
        pre_record=pre_record,
        post_record=post_record,
        pre_record_lead_seconds=lead_seconds
        if lead_seconds is not None
        else default_lead_seconds,
    )


def _build_recorder(settings: Dict, base_dir: Path) -> RecorderConfig:
    recorder_settings = settings.get("recorder", {}) or {}
    env = recorder_settings.get("env") or {}
    if not isinstance(env, dict):
        raise TypeError("settings.recorder.env must be a mapping of environment variables")
    x11_raw = recorder_settings.get("x11_grab_args")
    audio_raw = recorder_settings.get("audio_args")
    extra_output_raw = recorder_settings.get("extra_output_args")

    def _optional_path(value: object | None) -> Optional[Path]:
        if value is None:
            return None
        return _expand_path(base_dir, value)

    frame_rate_value = recorder_settings.get("frame_rate")
    frame_rate: Optional[int]
    if frame_rate_value in (None, ""):
        frame_rate = None
    else:
        frame_rate = int(frame_rate_value)

    def _ensure_list(value: object | None) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return shlex.split(value)
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value]
        raise TypeError("Recorder list configuration values must be string or list")

    x11_args = _ensure_list(x11_raw)
    audio_args = _ensure_list(audio_raw)
    if "extra_output_args" in recorder_settings:
        extra_output = _ensure_list(extra_output_raw)
    else:
        extra_output = ["-preset", "veryfast"]

    return RecorderConfig(
        ffmpeg_path=_optional_path(recorder_settings.get("ffmpeg_path"))
        if recorder_settings.get("ffmpeg_path")
        else Path("ffmpeg"),
        display=str(recorder_settings.get("display", ":0.0")),
        audio_source=str(recorder_settings.get("audio_source", "default")),
        video_size=recorder_settings.get("video_size"),
        frame_rate=frame_rate,
        video_codec=str(recorder_settings.get("video_codec", "libx264")),
        audio_codec=str(recorder_settings.get("audio_codec", "aac")),
        video_bitrate=recorder_settings.get("video_bitrate", "4500k"),
        audio_bitrate=recorder_settings.get("audio_bitrate", "128k"),
        pixel_format=recorder_settings.get("pixel_format", "yuv420p"),
        output_format=str(recorder_settings.get("output_format", "mp4")),
        x11_grab_args=x11_args,
        audio_args=audio_args,
        extra_output_args=extra_output,
        pulse_server=recorder_settings.get("pulse_server"),
        env={str(k): str(v) for k, v in env.items()},
        dry_run=bool(recorder_settings.get("dry_run", False)),
        log_level=str(recorder_settings.get("log_level", "info")),
    )


def _build_transcription(settings: Dict) -> Optional[TranscriptionConfig]:
    transcription_settings = settings.get("transcription")
    if not transcription_settings:
        return None

    command_value = transcription_settings.get("command")
    if not command_value:
        return None
    if isinstance(command_value, str):
        command = shlex.split(command_value)
    elif isinstance(command_value, (list, tuple)):
        command = [str(part) for part in command_value]
    else:
        raise TypeError("settings.transcription.command must be a string or list of strings")

    env = transcription_settings.get("env") or {}
    if env and not isinstance(env, dict):
        raise TypeError("settings.transcription.env must be a mapping")

    timeout_raw = transcription_settings.get("timeout_seconds") or transcription_settings.get(
        "timeout"
    )
    timeout = int(timeout_raw) if timeout_raw is not None else None

    return TranscriptionConfig(
        command=command,
        timeout_seconds=timeout,
        env={str(k): str(v) for k, v in env.items()} if env else None,
    )


def load_config(path: str | Path) -> AppConfig:
    """Load a configuration file that enumerates the meetings to record."""

    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)

    data = yaml.safe_load(file_path.read_text()) or {}

    settings = data.get("settings", {}) or {}
    default_timezone = str(settings.get("timezone", "UTC"))
    base_dir = file_path.parent

    recordings_dir_value = settings.get("recordings_dir", "recordings")
    recordings_dir = _expand_path(base_dir, recordings_dir_value)
    transcripts_dir_value = settings.get("transcripts_dir")
    transcripts_dir = (
        _expand_path(base_dir, transcripts_dir_value) if transcripts_dir_value else None
    )

    lead_value = settings.get("pre_record_lead_seconds", 0)
    try:
        default_lead_seconds = int(lead_value)
    except (TypeError, ValueError) as exc:
        raise TypeError("settings.pre_record_lead_seconds must be an integer") from exc
    if default_lead_seconds < 0:
        raise ValueError("settings.pre_record_lead_seconds must be zero or positive")

    meetings_raw = data.get("meetings", []) or []
    if not isinstance(meetings_raw, Iterable):
        raise TypeError("meetings must be an iterable of mappings")
    meetings: List[Meeting] = []
    for entry in meetings_raw:
        if not isinstance(entry, dict):
            raise TypeError("Each meeting entry must be a mapping")
        meetings.append(_deserialize_meeting(entry, default_timezone, default_lead_seconds))
    meetings = ensure_valid_meetings(meetings)

    recorder = _build_recorder(settings, base_dir)
    transcription = _build_transcription(settings)

    return AppConfig(
        meetings=meetings,
        recordings_dir=recordings_dir,
        transcripts_dir=transcripts_dir,
        recorder=recorder,
        transcription=transcription,
        default_timezone=default_timezone,
        pre_record_lead_seconds=default_lead_seconds,
    )


def dump_template(path: str | Path) -> None:
    """Write an example configuration file for quick bootstrapping."""

    template = {
        "settings": {
            "timezone": "UTC",
            "recordings_dir": "recordings",
            "transcripts_dir": "transcripts",
            "pre_record_lead_seconds": 60,
            "recorder": {
                "ffmpeg_path": "ffmpeg",
                "display": ":0.0",
                "audio_source": "default",
                "video_size": "1920x1080",
                "frame_rate": 30,
                "video_bitrate": "4500k",
                "audio_bitrate": "128k",
                "output_format": "mp4",
                "dry_run": True,
            },
            "transcription": {
                "command": [
                    "whisper",
                    "{input}",
                    "--model",
                    "small",
                    "--output_dir",
                    "{output_dir}",
                ],
                "timeout_seconds": 900,
            },
        },
        "meetings": [
            {
                "title": "Daily Standup",
                "meet_url": "https://meet.google.com/abc-defg-hij",
                "start_time": datetime.now().replace(microsecond=0).isoformat(),
                "duration": "30m",
                "timezone": "UTC",
                "pre_record_lead_seconds": 60,
                "participants": ["alice@example.com", "bob@example.com"],
                "notes": "Discuss blockers and priorities.",
                "pre_record": [
                    "export DISPLAY=:0.0 && chromium --profile-directory=Default --app=https://meet.google.com/abc-defg-hij"
                ],
                "post_record": ["pkill -f 'chromium --app=https://meet.google.com/abc-defg-hij'"]
            }
        ],
    }
    Path(path).write_text(yaml.safe_dump(template, sort_keys=False))
