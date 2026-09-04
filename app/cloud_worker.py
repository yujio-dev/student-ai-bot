"""Cloud-only entry point. No legacy database, no polling without cutover latch."""
import asyncio
import os
from contextlib import suppress

from telegram import BotCommand, Update
from telegram.ext import Application

from app.config import load_settings
from app.bridge_handlers import install, retry_loop


def validate(settings):
    if not settings.student_os_bridge_enabled:
        raise RuntimeError("Cloud worker requires Core bridge")
    if not settings.outbox_database_url.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("Cloud worker requires PostgreSQL outbox")
    if not settings.student_os_api_url.startswith("https://"):
        raise RuntimeError("Cloud worker requires HTTPS Core")
    if len(settings.student_os_bridge_secret) < 32:
        raise RuntimeError("Cloud worker requires strong bridge secret")


async def startup(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Как пользоваться"), BotCommand("balance", "Общий баланс"),
        BotCommand("buy", "Купить разборы"), BotCommand("newtask", "Новая задача"),
        BotCommand("paysupport", "Поддержка оплаты")])
    application.bot_data["retry_task"] = asyncio.create_task(retry_loop(application))


async def shutdown(application):
    task = application.bot_data.get("retry_task")
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def build(settings):
    validate(settings)
    application = Application.builder().token(settings.telegram_bot_token).post_init(startup).post_shutdown(shutdown).build()
    application.bot_data["settings"] = settings
    install(application, settings)
    return application


def main():
    # Independent of formation=0: accidental scaling must still not start polling.
    if os.getenv("CLOUD_POLLING_ENABLED", "false").lower() != "true":
        raise RuntimeError("Cloud polling disabled until explicit live cutover")
    from app.observability import initialize
    initialize("bot")
    build(load_settings()).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
