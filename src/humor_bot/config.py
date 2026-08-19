from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    openrouter_key: str
    model: str
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    port: int
    database_path: Path


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not token or not key:
        raise RuntimeError("Нужны TELEGRAM_BOT_TOKEN и OPENROUTER_API_KEY в .env")
    return Settings(
        telegram_token=token,
        openrouter_key=key,
        model=os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free"),
        whisper_model=os.getenv("WHISPER_MODEL", "base"),
        whisper_device=os.getenv("WHISPER_DEVICE", "cpu"),
        whisper_compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
        port=int(os.getenv("PORT", "10000")),
        database_path=Path(os.getenv("DATABASE_PATH", "data/humor.sqlite3")),
    )
