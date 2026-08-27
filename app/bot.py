from __future__ import annotations

import asyncio
import html
import logging
import re
from contextlib import suppress

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler,
    PreCheckoutQueryHandler, filters,
)

from app.ai_service import AIService
from app.config import Settings, load_settings
from app.database import Database


logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
# httpx logs complete Telegram request URLs, which contain the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
SINGLE_PAYLOAD = "task_help_1_v1"
PACK_PAYLOAD = "task_help_5_v1"
BOT_VERSION = "1.3.0"
FOUNDER_NAME = "Yujio (yujio-dev)"
GITHUB_URL = "https://github.com/yujio-dev/student-ai-bot"
PHOTO_PRICE_STARS = 100
PHOTO_CREDITS = 5


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


def format_about_message(solved_tasks: int) -> str:
    return (
        "<b>О Student AI Bot</b>\n\n"
        "Помогаю разбирать учебные задачи по шагам, проверять результат и готовить "
        "понятное объяснение для защиты.\n\n"
        f"<b>Версия:</b> {BOT_VERSION}\n"
        f"<b>Основатель:</b> {FOUNDER_NAME}\n"
        f"<b>Решено задач:</b> {solved_tasks}\n"
        f'<b>Открытый код:</b> <a href="{GITHUB_URL}">GitHub</a>'
    )


def services(context: ContextTypes.DEFAULT_TYPE) -> tuple[Settings, Database, AIService]:
    data = context.application.bot_data
    return data["settings"], data["db"], data["ai"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, db, _ = services(context)
    user = update.effective_user
    is_new_user = db.ensure_user(user.id, user.username)
    if is_new_user and context.args and context.args[0].startswith("ref_"):
        db.attach_referral(user.id, context.args[0][4:].upper())
    await update.message.reply_text(
        "Привет! Пришли учебную задачу текстом или одной фотографией — я определю "
        "предмет, разберу решение "
        "по шагам и помогу подготовить понятное объяснение.\n\n"
        "Первый разбор бесплатный. Важно: первое сообщение, которое бот распознает как "
        "конкретную учебную задачу, будет использовано как бесплатный разбор. Приветствия "
        "и вопросы о работе бота попытку не расходуют. Фоторазбор оплачивается отдельно: "
        f"{PHOTO_PRICE_STARS} Stars или {PHOTO_CREDITS} оплаченных попыток. Подробнее: /faq"
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
        f"Первый разбор бесплатный. Один дополнительный разбор стоит "
        f"{settings.single_price_stars} Stars. Выгодный пакет: {settings.pack_credits} "
        f"разборов за {settings.pack_price_stars} Stars вместо "
        f"{settings.single_price_stars * settings.pack_credits}. Купить: /buy\n\n"
        "Какие ограничения?\n"
        "Текст — до 6000 символов. Можно отправить одну фотографию задачи; перед обработкой "
        f"бот предупредит о цене и попросит подтверждение. Фоторазбор стоит {PHOTO_PRICE_STARS} "
        f"Stars или списывает {PHOTO_CREDITS} оплаченных попыток. PDF и другие файлы пока не "
        "принимаются. Ответ AI стоит перепроверять.\n\n"
        "Где посмотреть остаток?\n/balance\n\n"
        "Где узнать больше о проекте?\n/about"
    )


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, db, _ = services(context)
    await update.message.reply_text(
        format_about_message(db.solved_tasks_count()),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, db, _ = services(context)
    if db.has_unlimited_access(update.effective_user.id):
        await update.message.reply_text("Безлимитный доступ: активен. Попытки не списываются.")
        return
    trial_available, credits = db.balance(update.effective_user.id)
    trial = "доступен" if trial_available else "использован"
    await update.message.reply_text(f"Бесплатный разбор: {trial}. Оплаченных разборов: {credits}.")


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, _, _ = services(context)
    regular_pack_price = settings.single_price_stars * settings.pack_credits
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"1 разбор — {settings.single_price_stars} ⭐", callback_data="buy:1"
        )],
        [InlineKeyboardButton(
            f"{settings.pack_credits} разборов — {settings.pack_price_stars} ⭐ (вместо {regular_pack_price})",
            callback_data="buy:5",
        )],
    ])
    await update.effective_message.reply_text(
        "Выбери вариант",
        reply_markup=keyboard,
    )


async def send_product_invoice(
    update: Update, context: ContextTypes.DEFAULT_TYPE, product: str
) -> None:
    settings, _, _ = services(context)
    if product == "1":
        credits, stars, payload = 1, settings.single_price_stars, SINGLE_PAYLOAD
        title = "1 разбор учебной задачи"
        description = "Пошаговое решение, объяснение и проверка результата."
    else:
        credits, stars, payload = settings.pack_credits, settings.pack_price_stars, PACK_PAYLOAD
        title = f"{credits} разборов — выгодный пакет"
        description = (
            f"По одному: {settings.single_price_stars * credits} Stars. "
            f"Цена пакета: {stars} Stars."
        )
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title=title,
        description=description,
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(f"{credits} разборов", stars)],
        start_parameter=f"task-help-{credits}",
    )


async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await send_product_invoice(update, context, query.data.split(":", 1)[1])


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, _, _ = services(context)
    query = update.pre_checkout_query
    expected = {
        SINGLE_PAYLOAD: settings.single_price_stars,
        PACK_PAYLOAD: settings.pack_price_stars,
    }
    valid = (query.currency == "XTR"
             and expected.get(query.invoice_payload) == query.total_amount)
    await query.answer(ok=valid, error_message=None if valid else "Цена изменилась. Открой /buy ещё раз.")


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, db, _ = services(context)
    payment = update.message.successful_payment
    products = {
        SINGLE_PAYLOAD: (1, settings.single_price_stars),
        PACK_PAYLOAD: (settings.pack_credits, settings.pack_price_stars),
    }
    product = products.get(payment.invoice_payload)
    if (not product or payment.currency != "XTR"
            or payment.total_amount != product[1]):
        logger.error("Unexpected payment payload for user %s", update.effective_user.id)
        return
    credits = product[0]
    result = db.add_payment(
        update.effective_user.id, payment.telegram_payment_charge_id,
        payment.total_amount, credits, settings.referral_reward_credits,
    )
    if result.added:
        await update.message.reply_text(
            f"Оплата получена. Добавлено разборов: {credits}. Пришли учебную задачу."
        )
        if result.rewarded_referrer_id:
            try:
                await context.bot.send_message(
                    result.rewarded_referrer_id,
                    f"Твой приглашённый друг сделал первую покупку. Начислено бесплатных разборов: "
                    f"{settings.referral_reward_credits}.",
                )
            except Exception:
                logger.exception("Could not notify referrer %s", result.rewarded_referrer_id)


async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, db, _ = services(context)
    user = update.effective_user
    code = db.personal_referral_code(user.id, user.username)
    link = f"https://t.me/{context.bot.username}?start=ref_{code}"
    stats = db.referral_stats(user.id)[0]
    await update.message.reply_text(
        "<b>Твоя реферальная ссылка</b>\n"
        f"<code>{html.escape(link)}</code>\n\n"
        f"За первую покупку приглашённого ты получишь "
        f"<b>{settings.referral_reward_credits} бесплатный разбор</b>.\n"
        f"Переходов с запуском бота: {stats.joins}\n"
        f"Покупателей: {stats.buyers}",
        parse_mode="HTML",
    )


def normalize_partner_code(label: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9_]", "_", label.upper()).strip("_")
    return f"P_{cleaned[:24]}" if cleaned else ""


async def partner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, db, _ = services(context)
    if update.effective_user.id != settings.owner_telegram_id:
        await update.message.reply_text("Команда доступна только владельцу бота.")
        return
    if not context.args:
        await update.message.reply_text("Формат: /partner имя_партнёра")
        return
    label = " ".join(context.args).strip()
    code = normalize_partner_code(label)
    if not code or not db.create_cash_referral(code, label):
        await update.message.reply_text("Не удалось создать код. Выбери другое имя.")
        return
    link = f"https://t.me/{context.bot.username}?start=ref_{code}"
    await update.message.reply_text(
        f"Денежная партнёрская ссылка для <b>{html.escape(label)}</b>:\n"
        f"<code>{html.escape(link)}</code>\n\n"
        "Статистика появится в /refstats. Выплата рассчитывается вручную.",
        parse_mode="HTML",
    )


async def refstats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, db, _ = services(context)
    if update.effective_user.id == settings.owner_telegram_id:
        stats = db.referral_stats()
    else:
        db.personal_referral_code(update.effective_user.id, update.effective_user.username)
        stats = db.referral_stats(update.effective_user.id)
    if not stats:
        await update.message.reply_text("Реферальных ссылок пока нет.")
        return
    lines = ["<b>Статистика рефералов</b>"]
    for item in stats:
        kind = "деньги" if item.kind == "cash" else "бесплатные разборы"
        lines.append(
            f"\n<b>{html.escape(item.label)}</b> — {kind}\n"
            f"Код: <code>{item.code}</code>\n"
            f"Запустили бота: {item.joins}\n"
            f"Покупателей: {item.buyers}\n"
            f"Платежей: {item.payments}\n"
            f"Выручка: {item.stars} Stars"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def grant_reactivation_bonuses(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]
    db: Database = application.bot_data["db"]
    candidates = db.reactivation_candidates(settings.reactivation_days)
    for telegram_id in candidates:
        if not db.grant_reactivation_bonus(telegram_id, settings.reactivation_credits):
            continue
        try:
            await application.bot.send_message(
                telegram_id,
                "Давно не виделись 👋\n\n"
                f"Мы начислили тебе {settings.reactivation_credits} бесплатных разбора, "
                "чтобы ты мог попробовать бота ещё раз. Просто пришли следующую учебную задачу.",
            )
        except Exception:
            # The credits remain available if the user later returns or unblocks the bot.
            logger.exception("Could not send reactivation message to user %s", telegram_id)


async def reactivation_loop(application: Application) -> None:
    while True:
        try:
            await grant_reactivation_bonuses(application)
        except Exception:
            logger.exception("Reactivation scan failed")
        await asyncio.sleep(60 * 60)


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
        db.restore_access(user.id, access.source, access.credits_charged)
        db.log_request(user.id, access.source, 0, 0, 0, "failed")
        await update.message.reply_text(
            "Не удалось получить ответ. Бесплатный разбор или кредит возвращён — попробуй позже."
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    photo = update.message.photo[-1]
    if photo.file_size and photo.file_size > 10 * 1024 * 1024:
        await update.message.reply_text("Фото слишком большое. Пришли изображение до 10 МБ.")
        return
    context.user_data["pending_photo"] = {
        "file_id": photo.file_id,
        "caption": (update.message.caption or "").strip()[:2000],
    }
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"Подтвердить — {PHOTO_CREDITS} попыток",
            callback_data="photo:confirm",
        )],
        [InlineKeyboardButton("Отмена", callback_data="photo:cancel")],
    ])
    await update.message.reply_text(
        "Фоторазбор — отдельная функция. Он стоит 100 Telegram Stars или списывает "
        f"{PHOTO_CREDITS} оплаченных попыток. Бесплатный первый разбор для фото не действует.\n\n"
        "После подтверждения я распознаю условие и решу задачу. Если цена кажется "
        "завышенной или заниженной, напиши в поддержку: /paysupport.",
        reply_markup=keyboard,
    )


async def photo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "photo:cancel":
        context.user_data.pop("pending_photo", None)
        await query.edit_message_text("Фоторазбор отменён. Попытки не списаны.")
        return

    pending = context.user_data.pop("pending_photo", None)
    if not pending:
        await query.edit_message_text("Фото больше не доступно. Пришли его ещё раз.")
        return

    _, db, ai = services(context)
    user = update.effective_user
    access = db.claim_paid_credits(user.id, user.username, PHOTO_CREDITS, "photo_paid")
    if not access.allowed:
        _, credits = db.balance(user.id)
        await query.edit_message_text(
            f"Для фоторазбора нужно {PHOTO_CREDITS} оплаченных попыток, сейчас доступно: "
            f"{credits}. Пакет из {PHOTO_CREDITS} попыток стоит {PHOTO_PRICE_STARS} Stars. "
            "Купить: /buy"
        )
        return

    await query.edit_message_text(
        f"Принято. Списано попыток: {access.credits_charged}. Распознаю и решаю задачу…"
        if access.credits_charged else
        "Принято. Для безлимитного доступа попытки не списываются. Распознаю и решаю задачу…"
    )
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    try:
        telegram_file = await context.bot.get_file(pending["file_id"])
        image_bytes = bytes(await telegram_file.download_as_bytearray())
        answer = await asyncio.to_thread(ai.answer_image, image_bytes, pending["caption"])
        db.log_request(
            user.id, access.source, answer.input_tokens, answer.output_tokens,
            answer.estimated_cost_usd, "completed",
        )
        for part in split_message(answer.text, limit=3400):
            await update.effective_message.reply_text(
                markdown_to_telegram_html(part), parse_mode="HTML"
            )
    except Exception:
        logger.exception("Photo AI request failed for user %s", user.id)
        db.restore_access(user.id, access.source, access.credits_charged)
        db.log_request(user.id, access.source, 0, 0, 0, "failed")
        await update.effective_message.reply_text(
            f"Не удалось обработать фото. Все {PHOTO_CREDITS} попыток возвращены — "
            "пришли фотографию ещё раз."
        )


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "Как пользоваться"), BotCommand("balance", "Остаток разборов"),
        BotCommand("faq", "Частые вопросы"), BotCommand("buy", "Купить пакет"),
        BotCommand("referral", "Пригласить друга"),
        BotCommand("about", "О боте и открытом коде"),
        BotCommand("terms", "Условия"),
        BotCommand("paysupport", "Поддержка по оплате"),
    ])
    application.bot_data["reactivation_task"] = asyncio.create_task(
        reactivation_loop(application), name="reactivation-loop"
    )


async def post_shutdown(application: Application) -> None:
    task = application.bot_data.get("reactivation_task")
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def main() -> None:
    settings = load_settings()
    db = Database(settings.database_path)
    ai = AIService(settings.openai_api_key, settings.openai_model, settings.max_output_tokens,
                   settings.input_usd_per_million, settings.output_usd_per_million)
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.bot_data.update(settings=settings, db=db, ai=ai)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("faq", faq))
    application.add_handler(CommandHandler("about", about))
    application.add_handler(CommandHandler("buy", buy))
    application.add_handler(CommandHandler("referral", referral))
    application.add_handler(CommandHandler("partner", partner))
    application.add_handler(CommandHandler("refstats", refstats))
    application.add_handler(CommandHandler("terms", terms))
    application.add_handler(CommandHandler(["support", "paysupport"], support))
    application.add_handler(PreCheckoutQueryHandler(precheckout))
    application.add_handler(CallbackQueryHandler(buy_callback, pattern=r"^buy:(1|5)$"))
    application.add_handler(
        CallbackQueryHandler(photo_callback, pattern=r"^photo:(confirm|cancel)$")
    )
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question))
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
