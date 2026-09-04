from __future__ import annotations

import os
from dataclasses import dataclass, field
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
    single_price_stars: int
    referral_reward_credits: int
    reactivation_days: int
    reactivation_credits: int
    owner_telegram_id: int
    support_username: str
    input_usd_per_million: float
    output_usd_per_million: float
    max_output_tokens: int
    student_os_bridge_enabled: bool = False
    student_os_api_url: str = ""
    student_os_bridge_secret: str = ""
    outbox_database_url: str = field(default="", repr=False)


def load_settings() -> Settings:
    load_dotenv()
    settings = Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip(),
        database_path=Path(os.getenv("DATABASE_PATH", "data/student_ai_bot.db")),
        pack_price_stars=int(os.getenv("PACK_PRICE_STARS", "100")),
        pack_credits=int(os.getenv("PACK_CREDITS", "5")),
        single_price_stars=int(os.getenv("SINGLE_PRICE_STARS", "25")),
        referral_reward_credits=int(os.getenv("REFERRAL_REWARD_CREDITS", "1")),
        reactivation_days=int(os.getenv("REACTIVATION_DAYS", "3")),
        reactivation_credits=int(os.getenv("REACTIVATION_CREDITS", "3")),
        owner_telegram_id=int(os.getenv("OWNER_TELEGRAM_ID", "0")),
        support_username=os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@"),
        input_usd_per_million=float(os.getenv("MODEL_INPUT_USD_PER_MILLION", "0.20")),
        output_usd_per_million=float(os.getenv("MODEL_OUTPUT_USD_PER_MILLION", "1.20")),
        max_output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS", "1800")),
        student_os_bridge_enabled=os.getenv("STUDENT_OS_BRIDGE_ENABLED", "false").lower() == "true",
        student_os_api_url=os.getenv("STUDENT_OS_API_URL", "").strip(),
        student_os_bridge_secret=os.getenv("STUDENT_OS_BRIDGE_SECRET", "").strip(),
        outbox_database_url=os.getenv("DATABASE_URL", "").strip(),
    )
    missing = []
    if not settings.telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not settings.openai_api_key and not settings.student_os_bridge_enabled:
        missing.append("OPENAI_API_KEY")
    if missing:
        raise RuntimeError(f"Заполните в .env: {', '.join(missing)}")
    if settings.student_os_bridge_enabled:
        if os.getenv("DYNO") and not settings.outbox_database_url:
            raise RuntimeError("Cloud bridge requires PostgreSQL outbox DATABASE_URL")
        from app.bridge_client import StudentOSBridgeClient
        StudentOSBridgeClient(settings.student_os_api_url, settings.student_os_bridge_secret)
    if (settings.pack_price_stars <= 0 or settings.pack_credits <= 0
            or settings.single_price_stars <= 0 or settings.referral_reward_credits <= 0):
        raise RuntimeError("Цены, размеры пакетов и реферальная награда должны быть больше нуля")
    if settings.reactivation_days <= 0 or settings.reactivation_credits <= 0:
        raise RuntimeError("Параметры возвратного бонуса должны быть больше нуля")
    return settings
