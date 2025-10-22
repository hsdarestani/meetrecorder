# Meet Recorder

Meet Recorder is a Python toolkit that automates joining Google Meet sessions, simulates
recording, and forwards the captured output to a Telegram chat. It ships with a flexible
configuration system and an asynchronous scheduler that makes it straightforward to define
multiple meetings, durations, and notifications.

> ⚠️ The automation layer included in this repository is a **simulation**. It demonstrates
> the architecture and flow required to integrate with Google Meet, but it does not launch a
> real browser or capture actual audio/video. Replace the code in `meetrecorder/automation.py`
> with Playwright/Selenium integration and real recording logic to use it in production.

## Features

- YAML-based configuration for meetings (`meetrecorder.config`).
- Async scheduler that launches a simulated browser session, joins meetings, and captures
  recordings/transcripts (`meetrecorder.scheduler`).
- Optional Telegram notifications with document uploads (`meetrecorder.telegram`).
- Typer-based CLI for generating configuration templates, validating schedules, and running
  the worker (`meetrecorder.cli`).
- Automated tests covering the configuration loader and scheduler logic.

## Getting started

### Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Generate a configuration template

```bash
meetrecorder generate-config config.yaml
```

Edit the generated YAML file to include your meetings. Each meeting entry should contain the
meeting title, Google Meet URL, ISO 8601 start time, duration, timezone, and optional
participants list.

### Validate your configuration

```bash
meetrecorder validate config.yaml
```

### Run the scheduler

```bash
MEET_RECORDER_TELEGRAM_TOKEN=123:ABC MEET_RECORDER_TELEGRAM_CHAT_ID=999 \
    meetrecorder run config.yaml --recordings-dir ./recordings --transcripts-dir ./transcripts
```

The command loads the configuration, waits for the meeting start time, simulates the browser
interaction, and writes recording/transcript placeholders. If Telegram credentials are
provided, the artefacts are uploaded to the configured chat.

## Development

Install the project in editable mode and run tests via `pytest`.

```bash
pip install -e .[dev]
pytest
```

## Next steps

The repository is structured to make it easy to drop in real automation:

1. Replace the simulated automation functions in `meetrecorder/automation.py` with a
   Playwright/Selenium implementation that logs into Google Meet, manages microphone/camera
   states, and captures the session using your preferred recording backend.
2. Extend `meetrecorder.scheduler` to manage authentication, retries, and error handling for
   long-running meetings.
3. Integrate with a cloud storage provider to persist recordings beyond the local filesystem.
