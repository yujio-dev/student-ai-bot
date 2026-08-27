from __future__ import annotations

import asyncio
import html
import logging
import re

from telegram import BotCommand, LabeledPrice, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler,
    PreCheckoutQueryHandler, filters,
)

from app.ai_service import AIService
from app.config import Settings, load_settings
from app.database import Database


logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
# httpx logs complete Telegram request URLs, which contain the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
PAYLOAD = "code_help_5_v1"


def markdown_to_telegram_html(text: str) -> str:
    """Convert the small Markdown subset requested from the model to Telegram HTML."""
    result: list[str] = []
    code_lines: list[str] = []
    in_code = False
    language = ""

    def flush_code() -> None:
        nonlocal code_lines
        code = html.escape("\n".join(code_lines))
        language_class = f' class="language-{html.escape(language)}"' if language else ""
        result.append(f"<pre><code{language_class}>{code}</code></pre>")
        code_lines = []

    for raw_line in text.strip().splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            if in_code:
                flush_code()
                in_code = False
                language = ""
            else:
                in_code = True
                language = stripped[3:].strip().lower()
            continue
        if in_code:
            code_lines.append(raw_line)
            continue

        line = html.escape(raw_line)
        line = re.sub(r"^#{1,4}\s+(.+)$", r"<b>\1</b>", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", line)
        line = re.sub(r"^\s*-\s+", "• ", line)
        result.append(line)

    if in_code:
        flush_code()
    return "\n".join(result)


def split_message(text: str, limit: int = 4000) -> list[str]:
    parts: list[str] = []
    remaining = text.strip()
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    if remaining:
        parts.append(remaining)
    return parts


def services(context: ContextTypes.DEFAULT_TYPE) -> tuple[Settings, Database, AIService]:
    data = context.application.bot_data
    return data["settings"], data["db"], data["ai"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, db, _ = services(context)
    user = update.effective_user
    db.ensure_user(user.id, user.username)
    await update.message.reply_text(
        "Привет! Пришли учебную задачу текстом — я определю предмет, разберу решение "
        "по шагам и помогу подготовить понятное объяснение.\n\n"
        "Первый разбор бесплатный. Важно: первое сообщение, которое бот распознает как "
        "конкретную учебную задачу, будет использовано как бесплатный разбор. Приветствия "
        "и вопросы о работе бота попытку не расходуют. Подробнее: /faq"
    )


async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, _, _ = services(context)
    await update.message.reply_text(
        "Частые вопросы\n\n"
        "Что умеет бот?\n"
        "Разбирает текстовые учебные задачи по разным предметам, объясняет ход решения, "
        "помогает проверить результат и подготовиться к защите.\n\n"
        "Что расходует попытку?\n"
        "Только сообщение, распознанное как конкретная учебная задача. Приветствия и "
        "вопросы о самом боте попытку не списывают.\n\n"
        "Сколько стоит?\n"
        f"Первый разбор бесплатный. Затем {settings.pack_credits} разборов стоят "
        f"{settings.pack_price_stars} Telegram Stars. Купить: /buy\n\n"
        "Какие ограничения?\n"
        "Сейчас бот принимает только текст до 6000 символов. Изображения и файлы будут "
        "рассматриваться после проверки спроса. Ответ AI стоит перепроверять.\n\n"
        "Где посмотреть остаток?\n/balance"
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, db, _ = services(context)
    trial_available, credits = db.balance(update.effective_user.id)
    trial = "доступен" if trial_available else "использован"
    await update.message.reply_text(f"Бесплатный разбор: {trial}. Оплаченных разборов: {credits}.")


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, _, _ = services(context)
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title=f"{settings.pack_credits} разборов задач",
        description="Пошаговое решение, понятное объяснение и проверка результата.",
        payload=PAYLOAD,
        currency="XTR",
        prices=[LabeledPrice(f"{settings.pack_credits} разборов", settings.pack_price_stars)],
        start_parameter="code-help-pack",
    )


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, _, _ = services(context)
    query = update.pre_checkout_query
    valid = (query.invoice_payload == PAYLOAD and query.currency == "XTR"
             and query.total_amount == settings.pack_price_stars)
    await query.answer(ok=valid, error_message=None if valid else "Цена изменилась. Открой /buy ещё раз.")


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, db, _ = services(context)
    payment = update.message.successful_payment
    if payment.invoice_payload != PAYLOAD or payment.currency != "XTR":
        logger.error("Unexpected payment payload for user %s", update.effective_user.id)
        return
    added = db.add_payment(update.effective_user.id, payment.telegram_payment_charge_id,
                           payment.total_amount, settings.pack_credits)
    if added:
        await update.message.reply_text(
            f"Оплата получена. Добавлено разборов: {settings.pack_credits}. Пришли задачу и код."
        )


async def terms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Бот помогает разбирать учебные задачи. Ответы AI могут содержать "
        "ошибки — проверяй код перед сдачей. Оплата даёт указанное число разборов. "
        "При технической ошибке кредит возвращается. Возврат Stars по спорной покупке "
        "рассматривается через /paysupport. Не отправляй персональные данные и секреты."
    )


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, _, _ = services(context)
    text = (f"По вопросам оплаты и работы бота: @{settings.support_username}"
            if settings.support_username else
            "Контакт поддержки пока не настроен. Владелец должен заполнить SUPPORT_USERNAME в .env.")
    await update.message.reply_text(text)


async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, db, ai = services(context)
    text = (update.message.text or "").strip()
    if not text:
        return
    if len(text) > 6000:
        await update.message.reply_text("Сейчас лимит — 6000 символов. Оставь условие и проблемный код.")
        return
    user = update.effective_user
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    try:
        route = await asyncio.to_thread(ai.route, text)
    except Exception:
        logger.exception("Routing request failed for user %s", user.id)
        await update.message.reply_text("Не удалось распознать сообщение. Попробуй ещё раз позже.")
        return

    if not route.is_task:
        db.log_request(user.id, "free_chat", route.input_tokens, route.output_tokens,
                       route.estimated_cost_usd, "completed")
        await update.message.reply_text(markdown_to_telegram_html(route.reply), parse_mode="HTML")
        return

    access = db.claim_access(user.id, user.username)
    if not access.allowed:
        db.log_request(user.id, "routing", route.input_tokens, route.output_tokens,
                       route.estimated_cost_usd, "unpaid")
        await update.message.reply_text("Бесплатный разбор уже использован. Пакет доступен по команде /buy.")
        await buy(update, context)
        return
    try:
        answer = await asyncio.to_thread(ai.answer, text)
        db.log_request(
            user.id, access.source,
            route.input_tokens + answer.input_tokens,
            route.output_tokens + answer.output_tokens,
            route.estimated_cost_usd + answer.estimated_cost_usd,
            "completed",
        )
        for part in split_message(answer.text, limit=3400):
            await update.message.reply_text(
                markdown_to_telegram_html(part), parse_mode="HTML"
            )
    except Exception:
        logger.exception("AI request failed for user %s", user.id)
        db.restore_access(user.id, access.source)
        db.log_request(user.id, access.source, 0, 0, 0, "failed")
        await update.message.reply_text(
            "Не удалось получить ответ. Бесплатный разбор или кредит возвращён — попробуй позже."
        )


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
            BotCommand("start", "Как пользоваться"), BotCommand("balance", "Остаток разборов"),
        BotCommand("faq", "Частые вопросы"), BotCommand("buy", "Купить пакет"),
        BotCommand("terms", "Условия"),
        BotCommand("paysupport", "Поддержка по оплате"),
    ])


def main() -> None:
    settings = load_settings()
    db = Database(settings.database_path)
    ai = AIService(settings.openai_api_key, settings.openai_model, settings.max_output_tokens,
                   settings.input_usd_per_million, settings.output_usd_per_million)
    application = Application.builder().token(settings.telegram_bot_token).post_init(post_init).build()
    application.bot_data.update(settings=settings, db=db, ai=ai)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("faq", faq))
    application.add_handler(CommandHandler("buy", buy))
    application.add_handler(CommandHandler("terms", terms))
    application.add_handler(CommandHandler(["support", "paysupport"], support))
    application.add_handler(PreCheckoutQueryHandler(precheckout))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question))
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
