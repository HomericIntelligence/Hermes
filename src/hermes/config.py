"""Configuration for ProjectHermes, loaded from environment variables / .env file."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Runtime settings resolved from environment variables."""

    maestro_url: str
    maestro_api_key: str
    nats_url: str
    hermes_port: int
    webhook_secret: str

    def __init__(self) -> None:
        self.maestro_url = os.environ.get("MAESTRO_URL", "http://172.20.0.1:23000")
        self.maestro_api_key = os.environ.get("MAESTRO_API_KEY", "")
        self.nats_url = os.environ.get("NATS_URL", "nats://localhost:4222")
        self.hermes_port = int(os.environ.get("HERMES_PORT", "8080"))
        self.webhook_secret = os.environ.get("WEBHOOK_SECRET", "")


settings = Settings()
