"""Telegram bot integration for Meet Recorder."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests


@dataclass(slots=True)
class TelegramConfig:
    bot_token: str
    chat_id: str
    api_base: str = "https://api.telegram.org"


class TelegramNotifier:
    def __init__(self, config: TelegramConfig) -> None:
        self.config = config

    def _endpoint(self, method: str) -> str:
        return f"{self.config.api_base}/bot{self.config.bot_token}/{method}"

    def send_message(self, text: str, disable_notification: bool = False) -> None:
        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
            "disable_notification": disable_notification,
        }
        response = requests.post(self._endpoint("sendMessage"), json=payload, timeout=10)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to send Telegram message: {response.status_code} {response.text}"
            )

    def send_document(self, file_path: Path, caption: Optional[str] = None) -> None:
        files = {"document": file_path.open("rb")}
        data = {"chat_id": self.config.chat_id}
        if caption:
            data["caption"] = caption

        response = requests.post(
            self._endpoint("sendDocument"), data=data, files=files, timeout=30
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to upload Telegram document: {response.status_code} {response.text}"
            )

    def dump_state(self, path: Path) -> None:
        payload = {
            "bot_token": self.config.bot_token,
            "chat_id": self.config.chat_id,
            "api_base": self.config.api_base,
        }
        path.write_text(json.dumps(payload, indent=2))
