from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    openai_api_key: str
    openai_model: str
    database_path: Path
    pack_price_stars: int
    pack_credits: int
    support_username: str
    input_usd_per_million: float
    output_usd_per_million: float
    max_output_tokens: int


def load_settings() -> Settings:
    load_dotenv()
    settings = Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip(),
        database_path=Path(os.getenv("DATABASE_PATH", "data/student_ai_bot.db")),
        pack_price_stars=int(os.getenv("PACK_PRICE_STARS", "100")),
        pack_credits=int(os.getenv("PACK_CREDITS", "5")),
        support_username=os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@"),
        input_usd_per_million=float(os.getenv("MODEL_INPUT_USD_PER_MILLION", "0.20")),
        output_usd_per_million=float(os.getenv("MODEL_OUTPUT_USD_PER_MILLION", "1.20")),
        max_output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS", "1800")),
    )
    missing = []
    if not settings.telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not settings.openai_api_key:
        missing.append("OPENAI_API_KEY")
    if missing:
        raise RuntimeError(f"Заполните в .env: {', '.join(missing)}")
    if settings.pack_price_stars <= 0 or settings.pack_credits <= 0:
        raise RuntimeError("PACK_PRICE_STARS и PACK_CREDITS должны быть больше нуля")
    return settings

