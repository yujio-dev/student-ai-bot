"""Default-off Telegram presentation adapter; no independent credits or AI engine."""
from __future__ import annotations

import asyncio
import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.ext import ApplicationHandlerStop, TypeHandler

from app.bridge_client import BridgeError, StudentOSBridgeClient
from app.payment_outbox import PaymentOutbox

logger = logging.getLogger(__name__)
UNAVAILABLE = "Student AI временно недоступен. Попробуй позже. Баланс: /balance"


def identity(user) -> dict:
    return {"telegram_user_id": user.id, "username": (user.username or "")[:80],
            "display_name": (getattr(user, "full_name", "") or "")[:160]}


def balance_text(entitlement: dict) -> str:
    if entitlement.get("unlimited"):
        return "Безлимитный доступ: активен. Попытки не списываются."
    trial = "доступен" if entitlement.get("free_trial_available") else "использован"
    return f"Бесплатный разбор: {trial}. Оплаченных разборов: {entitlement['balance']}."


def render_result(result: dict, *, defense: bool = False) -> str:
    fields = (("Как защитить", "how_to_defend"), ("Вопросы преподавателя", "defense_questions"),
              ("Возможные ошибки", "pitfalls")) if defense else (
        ("Понимание задания", "analysis"), ("Решение / объяснение", "explanation"),
        ("Подход", "approach"), ("Проверка", "checks"))
    sections = []
    for title, key in fields:
        value = result.get(key, "")
        if isinstance(value, list):
            value = "\n".join(f"• {item}" for item in value)
        if value:
            sections.append(f"{title}\n{value}")
    return "\n\n".join(sections)[:60000] or "Раздел отсутствует в ответе."


async def send_plain(message, text: str, reply_markup=None):
    # 1800 Unicode code points fit Telegram's UTF-16 limit even for emoji.
    for offset in range(0, len(text), 1800):
        await message.reply_text(text[offset:offset + 1800],
                                 reply_markup=reply_markup if offset + 1800 >= len(text) else None)


async def show_products(message, client):
    products = (await asyncio.to_thread(client.get_products))["products"]
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{p['title']} — {p['stars']} ⭐", callback_data=f"corebuy:{p['id']}")]
        for p in products[:10]
    ])
    await message.reply_text("Выбери разборы для общего баланса Student OS:", reply_markup=keyboard)


async def retry_loop(application):
    data = application.bot_data
    while True:
        try:
            await asyncio.to_thread(data["payment_outbox"].retry, data["bridge"], 20)
        except Exception:
            # Do not log payment payload or raw transport exceptions.
            logger.error("Payment outbox retry failed; durable records retained")
        await asyncio.sleep(60)


async def dispatch(update: Update, context):
    """Runs before legacy handlers and stops only bridge-owned updates."""
    data = context.application.bot_data
    client = data.get("bridge")
    if client is None or update.effective_user is None:
        return
    message = update.effective_message
    user = identity(update.effective_user)
    query = update.callback_query
    checkout = update.pre_checkout_query
    payment = getattr(message, "successful_payment", None)
    text = (getattr(message, "text", None) or "").strip()
    command = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
    try:
        if checkout:
            try:
                products = (await asyncio.to_thread(client.get_products))["products"]
                valid = checkout.currency == "XTR" and any(
                    p["id"] == checkout.invoice_payload and p["stars"] == checkout.total_amount for p in products)
            except (BridgeError, KeyError, TypeError):
                valid = False
            await checkout.answer(ok=valid, error_message=None if valid else "Покупка временно недоступна. Открой /buy позже.")
        elif payment:
            if payment.currency != "XTR":
                logger.error("Unexpected non-Stars payment; manual support required")
                await message.reply_text("Платёж требует проверки поддержки: /paysupport")
            else:
                payload = {"telegram": user, "charge_id": payment.telegram_payment_charge_id,
                           "product_id": payment.invoice_payload, "stars_paid": payment.total_amount}
                outbox = data["payment_outbox"]
                # FIRST durable commit, even if Core/catalog is currently unavailable.
                await asyncio.to_thread(outbox.enqueue, payload)
                await asyncio.to_thread(outbox.retry, client, 20)
                await message.reply_text("Платёж сохранён. Баланс: /balance. Если Core недоступен, начисление будет повторено автоматически.")
        elif query:
            action = query.data or ""
            if action.startswith(("corebuy:", "buy:")):
                await query.answer()
                product_id = action.split(":", 1)[1]
                product_id = {"1": "task_help_1_v1", "5": "task_help_5_v1"}.get(product_id, product_id)
                products = (await asyncio.to_thread(client.get_products))["products"]
                product = next((p for p in products if p["id"] == product_id), None)
                if product is None:
                    await show_products(message, client)
                else:
                    await context.bot.send_invoice(chat_id=update.effective_chat.id,
                        title=product["title"], description="Разборы на общем балансе Student OS и Telegram.",
                        payload=product["id"], currency="XTR", prices=[LabeledPrice(product["title"], product["stars"])])
            elif action.startswith("coredef:"):
                await query.answer()
                entry = context.user_data.get("core_defense", {}).get(action[8:])
                if entry and entry[0] > time.time():
                    await send_plain(message, entry[1])
                else:
                    await message.reply_text("Контекст защиты истёк. Он доступен час после ответа.")
            elif action.startswith(("photo:", "defense:", "admin:", "feedback:")):
                await query.answer()
                await message.reply_text("Эта старая кнопка недоступна в общем режиме. Управление балансом — в Student OS.")
            else:
                return
        elif command == "/balance":
            result = await asyncio.to_thread(client.get_entitlement, user)
            await message.reply_text(balance_text(result["entitlement"]))
        elif command == "/buy" or (command == "/start" and text.split()[1:] == ["buy"]):
            await show_products(message, client)
        elif command == "/start":
            await asyncio.to_thread(client.resolve_user, user)
            await message.reply_text("Student AI связан с общим аккаунтом Student OS. Пришли учебную задачу текстом.\nОдин общий пробный разбор; /balance — остаток, /buy — покупка.")
        elif command in {"/admin", "/referral", "/partner", "/refstats", "/funnel", "/funnelcsv"}:
            await message.reply_text("В общем режиме управление и статистика находятся в Student OS. Старый баланс не используется.")
        elif command == "/faq":
            await message.reply_text("Текст до 6000 символов. Один общий пробный разбор с Web; далее попытки с общего баланса. Цены: /buy. Проверяй ответы AI. Фото пока недоступно в общем режиме.")
        elif getattr(message, "photo", None):
            await message.reply_text("Фото ещё не подключено к общему балансу. Пришли условие текстом; попытка не списана.")
        elif text and not command:
            if not 3 <= len(text) <= 6000:
                await message.reply_text("Пришли условие длиной от 3 до 6000 символов.")
            else:
                key = f"telegram:{user['telegram_user_id']}:{update.effective_chat.id}:{message.message_id}"
                result = (await asyncio.to_thread(client.submit_text_task, user, text, key))["result"]
                defense_key = str(message.message_id)
                entries = context.user_data.setdefault("core_defense", {})
                while len(entries) >= 5:
                    entries.pop(next(iter(entries)))
                entries[defense_key] = (time.time() + 3600, render_result(result, defense=True))
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Как защитить", callback_data=f"coredef:{defense_key}")]])
                await send_plain(message, render_result(result), keyboard)
        else:
            return
    except BridgeError as exc:
        if message:
            await message.reply_text({402: "Попытки закончились. Купить: /buy", 409: "Этот запрос уже принят. Повторно попытка не списана."}.get(exc.status, UNAVAILABLE))
    except (KeyError, TypeError, ValueError):
        logger.error("Invalid bridge contract or conflicting payment; review required")
        if message:
            await message.reply_text("Не удалось подтвердить операцию. Обратись в /paysupport.")
    raise ApplicationHandlerStop


def install(application, settings):
    if not settings.student_os_bridge_enabled:
        return
    application.bot_data["bridge"] = StudentOSBridgeClient(settings.student_os_api_url, settings.student_os_bridge_secret)
    application.bot_data["payment_outbox"] = PaymentOutbox(settings.database_path.with_name("core_payment_outbox.db"))
    application.add_handler(TypeHandler(Update, dispatch), group=-1)
