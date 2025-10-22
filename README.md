# Meet Recorder

Meet Recorder turns a Linux workstation into a scheduled Google Meet recorder. It wraps
FFmpeg for screen/audio capture, optional transcription, Telegram notifications, and a
configurable scheduler so that you can define meeting windows ahead of time and let the
recorder handle the rest.

## Highlights

- **Real media capture** – FFmpeg records an X11 display together with a PulseAudio source.
- **Command hooks** – run shell commands before/after each meeting (for example to launch
  Chromium, mute audio, or tidy up lingering browser processes).
- **Optional transcription** – execute any command-line transcriber (Whisper CLI, faster-whisper,
  etc.) once the recording finishes.
- **Telegram integration** – send summaries and upload media/transcripts to a chat.
- **Typer CLI** – generate config templates, validate schedules, and run the automation service.
- **Test suite** – exercises the configuration loader and scheduler using the dry-run mode.

## Requirements

The scheduler expects an X11 display and a PulseAudio source that already has the Google Meet
session running. On Ubuntu this usually means using `Xvfb` (virtual display) and a null audio
sink.

System packages you will typically need:

```bash
sudo apt update
sudo apt install -y python3-venv ffmpeg pulseaudio dbus-x11 xvfb xdotool x11vnc
# Install a browser (pick one):
sudo snap install chromium --classic  # or install Google Chrome from Google
```

Optional transcription (Whisper CLI):

```bash
pip install --upgrade openai-whisper
```

## Ubuntu quick start

1. **Create a dedicated user (recommended).**
   ```bash
   sudo adduser --disabled-password --gecos "Meet Recorder" meetrecorder
   sudo loginctl enable-linger meetrecorder
   sudo -iu meetrecorder
   ```

2. **Create a Python environment and install the package.**
   ```bash
   cd ~
   python3 -m venv .venv
   source .venv/bin/activate
   git clone https://github.com/your-org/meetrecorder.git
   cd meetrecorder
   pip install -e .
   ```

3. **Start the display and audio stack.** Run these in a persistent tmux screen or systemd user
   services.
   ```bash
   export DISPLAY=:99
   Xvfb :99 -screen 0 1920x1080x24 &
   sleep 2
   openbox-session &        # or any lightweight window manager
   pulseaudio --start
   pactl load-module module-null-sink sink_name=meetrecorder_sink \
       sink_properties=device.description=MeetRecorder
   pactl load-module module-loopback latency_msec=60
   pactl set-default-sink meetrecorder_sink
   pactl set-default-source meetrecorder_sink.monitor
   ```

   > Tip: use `pactl list short sources` to confirm the PulseAudio monitor name. Point the
   > recorder configuration’s `audio_source` field to the monitor (for example
   > `meetrecorder_sink.monitor`).

4. **Launch a browser on the virtual display and log in to Google Meet.**
   ```bash
   export DISPLAY=:99
   chromium --user-data-dir="$HOME/.config/meetrecorder-chrome" --profile-directory=Default &
   ```
   Use a VNC viewer (`x11vnc -display :99`) to connect to the session the first time so that you
   can sign in to Google and allow microphone/camera permissions. Keep the profile directory for
   reuse by the scheduler.

5. **Generate and edit the configuration.**
   ```bash
   meetrecorder generate-config config.yaml
   ```

   Update `config.yaml`:
   - Set `settings.recorder.display` to `":99"` (or whichever display you created).
   - Set `settings.recorder.audio_source` to your PulseAudio monitor (for example
     `meetrecorder_sink.monitor`).
   - Flip `settings.recorder.dry_run` to `false` once you have tested.
   - Add `pre_record` commands that open the meeting a little before the start time, for example:
     ```yaml
     pre_record:
       - export DISPLAY=:99 && chromium \
           --user-data-dir=$HOME/.config/meetrecorder-chrome \
           --profile-directory=Default \
           --app=https://meet.google.com/abc-defg-hij
       - sleep 30
       - export DISPLAY=:99 && xdotool search --onlyvisible --name "Weekly Sync" \
           windowactivate --sync key ctrl+d ctrl+e ctrl+j
     post_record:
       - pkill -f 'chromium --app=https://meet.google.com/abc-defg-hij'
     ```
   - If you enabled transcription, make sure the command writes a `.txt` file (the default template
     shows how to call Whisper CLI).

6. **Validate everything.**
   ```bash
   meetrecorder validate config.yaml
   ```

7. **Dry run first.** (Keeps `dry_run: true` in the config.)
   ```bash
   meetrecorder run config.yaml --dry-run
   ```
   The scheduler will create placeholder files so you can confirm paths, Telegram notifications,
   and command hooks.

8. **Record real meetings.** Disable dry run and start the scheduler for real captures.
   ```bash
   meetrecorder run config.yaml --no-dry-run \
       --recordings-dir /srv/meetrecorder/recordings \
       --transcripts-dir /srv/meetrecorder/transcripts
   ```

## Configuration overview

- `settings.recordings_dir` / `settings.transcripts_dir` – directories for output. Relative paths
  are resolved against the configuration file location.
- `settings.recorder` – FFmpeg options. Important keys are `display`, `audio_source`,
  `video_size`, and `dry_run`.
- `settings.transcription` – optional command to run after recording. Use `{input}` for the media
  path and `{output_dir}` for the transcript directory.
- `meetings[*]` – each meeting includes title, URL, timezone-aware start time, duration, and
  optional `pre_record`/`post_record` shell commands.

See [`example.config.yaml`](example.config.yaml) for a complete sample.

## Telegram notifications

Set the following environment variables before running the scheduler:

```bash
export MEET_RECORDER_TELEGRAM_TOKEN=123456:ABCDEF
export MEET_RECORDER_TELEGRAM_CHAT_ID=987654321
meetrecorder run config.yaml
```

The bot sends a summary message and uploads the media/transcript if present.

## Development

```bash
pip install -e .[dev]
pytest
```

The test suite executes the scheduler in dry-run mode so it does not require FFmpeg or a running
X11/PulseAudio stack.
