# -*- coding: utf-8 -*-
"""
AntiSpam Defender Bot — Business-бот с командами в чате с людьми.
"""

import os
import logging
import threading
import asyncio
from datetime import datetime, timedelta
from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CARD_NUMBER = "2204320449407461"
OWNER_USERNAME = "ysorn"
OWNER_ID = 8502858396

CHANNEL_LINK = "https://t.me/+MV9rTn9A6L1hNGNi"
CHANNEL_ID = -1004412177691

PRICES = {
    "1month": {"rub": 100, "days": 30, "label": "1 месяц"},
    "6months": {"rub": 599, "days": 180, "label": "6 месяцев"},
    "1year": {"rub": 1199, "days": 365, "label": "1 год"},
}
TRIAL_DAYS = 7
WARN_LIMIT = 5
WARN_MUTE_MINUTES = 5

BANNER_PATH = os.path.join(os.path.dirname(__file__), "IMG_20260918_155302_695.jpg")

# Хранилища
business_owners = {}
subscriptions = {}
pending_payments = {}
used_trials = set()
message_cache = {}
warns = {}
mutes = {}
clone = {}
warn_messages = {}
referrals = {}

# ================== FLASK ==================
flask_app = Flask(__name__)


@flask_app.route('/')
def home():
    return "Bot is running"


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)


# ================== ИНИЦИАЛИЗАЦИЯ ==================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ================== УТИЛИТЫ ==================
async def bot_api(method: str, data: dict):
    """Прямой вызов любого метода Bot API (для aiogram 3.15, где нет deleteBusinessMessages)."""
    try:
        result = await bot.session.make_request(method=method, data=data)
        return result
    except Exception as e:
        logging.error(f"❌ bot_api({method}): {type(e).__name__}: {e}")
        return None


async def delete_business_msg(conn_id, message_ids):
    """Удаляет бизнес-сообщения через прямой вызов Bot API."""
    if not isinstance(message_ids, list):
        message_ids = [message_ids]
    return await bot_api(
        "deleteBusinessMessages",
        {
            "business_connection_id": conn_id,
            "message_ids": message_ids,
        },
    )


async def auto_delete(chat_id, message_id, conn_id, seconds=3):
    await asyncio.sleep(seconds)
    try:
        await delete_business_msg(conn_id, [message_id])
    except Exception as e:
        logging.error(f"auto_delete failed: {e}")


async def delete_cmd(message: types.Message):
    try:
        await delete_business_msg(
            message.business_connection_id,
            [message.message_id],
        )
        logging.info(f"✅ Удалена команда: {(message.text or '')[:30]}")
    except Exception as e:
        logging.error(f"❌ Ошибка удаления команды: {type(e).__name__}: {e}")


async def delete_silent(chat_id, message_id, conn_id):
    try:
        result = await delete_business_msg(conn_id, [message_id])
        return result is not None
    except Exception as e:
        logging.error(f"❌ delete_silent: {type(e).__name__}: {e}")
        return False


async def send_confirm(chat_id, text, conn_id, seconds=3):
    try:
        msg = await bot.send_message(
            chat_id,
            text,
            business_connection_id=conn_id,
            parse_mode="HTML",
        )
        asyncio.create_task(auto_delete(chat_id, msg.message_id, conn_id, seconds))
        return msg
    except Exception as e:
        logging.error(f"send_confirm failed: {e}")
        return None


# ================== ПРОВЕРКА ПОДПИСКИ ==================
async def check_subscription(user_id):
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status not in ("left", "kicked")
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return True


def subscribe_kb():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📢 Подписаться на канал", url=CHANNEL_LINK)],
        [types.InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")],
    ])


# ================== ВЛАДЕЛЕЦ ==================
async def get_owner_id(business_connection_id):
    if not business_connection_id:
        return None
    if business_connection_id in business_owners:
        return business_owners[business_connection_id]
    try:
        conn = await bot.get_business_connection(business_connection_id)
        owner_id = conn.user.id
        business_owners[business_connection_id] = owner_id
        return owner_id
    except Exception as e:
        logging.error(f"get_owner_id error: {e}")
        return None


async def is_owner(message: types.Message):
    owner_id = await get_owner_id(message.business_connection_id)
    return owner_id is not None and message.from_user.id == owner_id


async def check_business_subscription(message: types.Message):
    owner_id = await get_owner_id(message.business_connection_id)
    if owner_id is None:
        return False
    if not await check_subscription(owner_id):
        try:
            await message.answer(
                f"⚠️ <b>Для использования бота подпишись на канал:</b>\n{CHANNEL_LINK}",
                parse_mode="HTML"
            )
        except:
            pass
        return False
    return True


# ================== КЛАВИАТУРЫ ==================
def main_menu():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📖 Команды бота", callback_data="cmd_list")],
        [types.InlineKeyboardButton(text="💎 Подписка", callback_data="sub_menu")],
        [types.InlineKeyboardButton(text="👥 Пригласить друга", callback_data="ref")],
        [types.InlineKeyboardButton(text="📚 Как подключить", callback_data="howto")],
    ])


def back_kb():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔙 В меню", callback_data="back_main")]
    ])


def plans_kb(user_id=None):
    rows = []
    if user_id is not None and user_id not in used_trials:
        rows.append([types.InlineKeyboardButton(text=f"🎁 Пробный период ({TRIAL_DAYS} дней)", callback_data="trial")])
    for k, v in PRICES.items():
        rows.append([types.InlineKeyboardButton(text=f"{v['label']} — {v['rub']}₽", callback_data=f"pay_{k}")])
    rows.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


# ================== /START ==================
@dp.message(F.text == "/start")
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1][4:])
            if referrer_id != user_id:
                referrals.setdefault(referrer_id, set()).add(user_id)
                now = datetime.now()
                current = subscriptions.get(referrer_id, now)
                subscriptions[referrer_id] = max(current, now) + timedelta(days=3)
                try:
                    await bot.send_message(
                        referrer_id,
                        "🎁 <b>Новый друг присоединился!</b>\n+3 дня к подписке.",
                        parse_mode="HTML"
                    )
                except:
                    pass
        except ValueError:
            pass

    if not await check_subscription(user_id):
        await message.answer(
            "⚠️ <b>Для использования бота нужно подписаться на наш канал.</b>\n\n"
            "📢 Подпишись и нажми «✅ Я подписался».",
            parse_mode="HTML",
            reply_markup=subscribe_kb()
        )
        return
    try:
        await message.answer_photo(
            photo=types.FSInputFile(BANNER_PATH),
            caption="🏠 <b>Главное меню</b>\n\nВыбери, что тебя интересует 👇",
            parse_mode="HTML",
            reply_markup=main_menu()
        )
    except Exception as e:
        logging.error(f"Баннер: {e}")
        await message.answer("🏠 <b>Главное меню</b>\n\nВыбери 👇", parse_mode="HTML", reply_markup=main_menu())


@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(call: types.CallbackQuery):
    if await check_subscription(call.from_user.id):
        try:
            await call.message.delete()
        except:
            pass
        try:
            await call.message.answer_photo(
                photo=types.FSInputFile(BANNER_PATH),
                caption="🏠 <b>Главное меню</b>\n\nВыбери 👇",
                parse_mode="HTML",
                reply_markup=main_menu()
            )
        except:
            await call.message.answer("🏠 <b>Главное меню</b>\n\nВыбери 👇", parse_mode="HTML", reply_markup=main_menu())
    else:
        await call.answer("❌ Ты ещё не подписался на канал!", show_alert=True)


@dp.callback_query(F.data == "back_main")
async def cb_back(call: types.CallbackQuery):
    try:
        await call.message.delete()
    except:
        pass
    try:
        await call.message.answer_photo(
            photo=types.FSInputFile(BANNER_PATH),
            caption="🏠 <b>Главное меню</b>\n\nВыбери 👇",
            parse_mode="HTML",
            reply_markup=main_menu()
        )
    except:
        await call.message.answer("🏠 <b>Главное меню</b>\n\nВыбери 👇", parse_mode="HTML", reply_markup=main_menu())


@dp.callback_query(F.data == "cmd_list")
async def cb_cmds(call: types.CallbackQuery):
    await call.message.answer(
        "📖 <b>Команды:</b>\n\n"
        "<code>.mute N</code> — замутить на N минут\n"
        "<code>.unmute</code> — снять мут\n"
        "<code>.warn N</code> — предупреждения\n"
        "<code>.unwarn</code> — сбросить\n"
        "<code>.spam N текст</code> — отправить N раз\n"
        "<code>.st текст</code> — по словам\n"
        "<code>.clone on/off</code> — автоповтор\n"
        "<code>.history N</code> — последние N сообщений",
        parse_mode="HTML", reply_markup=back_kb())


@dp.callback_query(F.data == "sub_menu")
async def cb_sub(call: types.CallbackQuery):
    user_id = call.from_user.id
    now = datetime.now()
    current = subscriptions.get(user_id)
    status = "не активна"
    if current and current > now:
        days_left = (current - now).days
        status = f"активна до {current.strftime('%d.%m.%Y')} (осталось {days_left} дн.)"
    trial_text = ""
    if user_id not in used_trials:
        trial_text = f"🎁 Пробный период — {TRIAL_DAYS} дней (только 1 раз)\n\n"
    await call.message.answer(
        f"💎 <b>Подписка AntiSpam Defender</b>\n\n"
        f"📌 Статус: <b>{status}</b>\n\n"
        f"{trial_text}"
        f"Выбери действие 👇",
        parse_mode="HTML",
        reply_markup=plans_kb(user_id)
    )


@dp.callback_query(F.data == "trial")
async def cb_trial(call: types.CallbackQuery):
    user_id = call.from_user.id
    now = datetime.now()
    if user_id in used_trials:
        await call.answer("❌ Ты уже использовал пробный период!", show_alert=True)
        return
    current = subscriptions.get(user_id)
    if current and current > now:
        await call.answer("❌ У тебя уже есть активная подписка!", show_alert=True)
        return
    used_trials.add(user_id)
    until = now + timedelta(days=TRIAL_DAYS)
    subscriptions[user_id] = until
    await call.message.answer(
        f"🎁 <b>Пробный период активирован!</b>\n\n"
        f"💎 Тебе доступно <b>{TRIAL_DAYS} дней</b> бесплатно.\n"
        f"📅 Действует до: <b>{until.strftime('%d.%m.%Y %H:%M')}</b>",
        parse_mode="HTML"
    )
    await call.answer("Пробный период активирован ✅")


@dp.callback_query(F.data == "ref")
async def cb_ref(call: types.CallbackQuery):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{call.from_user.id}"
    invited = len(referrals.get(call.from_user.id, set()))
    await call.message.answer(
        f"👥 <b>Пригласить друга</b>\n\n"
        f"Отправь другу свою ссылку:\n"
        f"<code>{link}</code>\n\n"
        f"🎁 За каждого друга — <b>+3 дня</b> к подписке!\n"
        f"📊 Приглашено: <b>{invited}</b>",
        parse_mode="HTML",
        reply_markup=back_kb()
    )
    await call.answer()


@dp.callback_query(F.data == "howto")
async def cb_howto(call: types.CallbackQuery):
    await call.message.answer(
        "📚 <b>Как подключить бота:</b>\n\n"
        "1️⃣ Открой <b>Настройки</b> Telegram\n"
        "2️⃣ Перейди в <b>Аккаунт</b> → <b>Автоматизация чатов</b>\n"
        "3️⃣ Выбери <b>AntiSpam Defender</b>\n"
        "4️⃣ Дай разрешения:\n"
        "   • ✅ Чтение сообщений\n"
        "   • ✅ Ответы на сообщения\n"
        "   • ✅ Удаление входящих\n"
        "   • ✅ Удаление исходящих\n\n"
        "5️⃣ Готово! Бот начнёт управлять чатами.",
        parse_mode="HTML",
        reply_markup=back_kb()
    )
    await call.answer()


@dp.callback_query(F.data.startswith("pay_"))
async def cb_pay(call: types.CallbackQuery):
    plan = call.data.split("_")[1]
    p = PRICES[plan]
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{plan}")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="sub_menu")],
    ])
    await call.message.answer(
        f"💳 <b>Оплата «{p['label']}»</b>\n\n"
        f"💰 Сумма: <b>{p['rub']}₽</b>\n"
        f"💳 Карта: <code>{CARD_NUMBER}</code>\n\n"
        f"📸 После перевода нажми «Я оплатил» и пришли скриншот.",
        parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("paid_"))
async def cb_paid(call: types.CallbackQuery):
    plan = call.data.split("_")[1]
    pending_payments[call.from_user.id] = {"plan": plan}
    await call.message.answer("📸 Пришли скриншот оплаты одним сообщением-фото.")


@dp.message(F.photo)
async def on_screenshot(message: types.Message):
    user_id = message.from_user.id
    if user_id not in pending_payments:
        return
    plan = pending_payments[user_id].get("plan", "1month")
    user = message.from_user
    owner_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"approve_{user.id}_{plan}")],
        [types.InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{user.id}")],
    ])
    try:
        await bot.send_photo(
            chat_id=OWNER_ID,
            photo=message.photo[-1].file_id,
            caption=(
                f"💰 <b>Новая оплата</b>\n\n"
                f"👤 Покупатель: @{user.username or user.first_name} (ID: <code>{user.id}</code>)\n"
                f"📦 Тариф: <b>{PRICES[plan]['label']}</b> — {PRICES[plan]['rub']}₽"
            ),
            parse_mode="HTML",
            reply_markup=owner_kb
        )
        await message.answer("✅ Скриншот отправлен! Ожидай подтверждения.")
        pending_payments.pop(user_id, None)
    except Exception as e:
        logging.error(f"Ошибка пересылки: {e}")
        await message.answer("⚠️ Ошибка. Свяжитесь с @ysorn.")


@dp.callback_query(F.data.startswith("approve_"))
async def cb_approve(call: types.CallbackQuery):
    if call.from_user.id != OWNER_ID:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    parts = call.data.split("_")
    user_id = int(parts[1])
    plan = parts[2]
    now = datetime.now()
    days = PRICES[plan]["days"]
    current = subscriptions.get(user_id, now)
    subscriptions[user_id] = max(current, now) + timedelta(days=days)
    try:
        await bot.send_message(
            user_id,
            f"✅ <b>Оплата подтверждена!</b>\n\n"
            f"💎 Подписка активирована на <b>{days} дней</b>.\n"
            f"📅 До: <b>{subscriptions[user_id].strftime('%d.%m.%Y')}</b>",
            parse_mode="HTML"
        )
    except:
        pass
    await call.message.edit_caption(
        caption=f"{call.message.caption}\n\n✅ <b>Подтверждено</b>",
        parse_mode="HTML"
    )
    await call.answer("Подписка активирована")


@dp.callback_query(F.data.startswith("reject_"))
async def cb_reject(call: types.CallbackQuery):
    if call.from_user.id != OWNER_ID:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    user_id = int(call.data.split("_")[1])
    try:
        await bot.send_message(user_id, "❌ Оплата отклонена. Свяжитесь с @ysorn.")
    except:
        pass
    await call.message.edit_caption(
        caption=f"{call.message.caption}\n\n❌ <b>Отклонено</b>",
        parse_mode="HTML"
    )
    await call.answer("Отклонено")


# ================== ЛС ВЛАДЕЛЬЦУ ==================
@dp.message()
async def forward_to_owner(message: types.Message):
    if message.chat.type != "private":
        return
    if message.from_user.id == OWNER_ID:
        return
    if message.text and message.text.startswith("/"):
        return
    try:
        text = message.text or "[медиа]"
        user = message.from_user
        await bot.send_message(
            OWNER_ID,
            f"📩 <b>Сообщение от пользователя</b>\n\n"
            f"👤 От: @{user.username or user.first_name} (ID: <code>{user.id}</code>)\n"
            f"📝 Текст: <code>{text[:500]}</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Не смог переслать ЛС: {e}")


# ================== BUSINESS КОМАНДЫ ==================
@dp.business_message(F.text.startswith(".mute"))
async def b_mute(message: types.Message):
    logging.info(f"🔵 B_MUTE: chat={message.chat.id}")
    if not await is_owner(message):
        return
    if not await check_business_subscription(message):
        return
    await delete_cmd(message)
    parts = message.text.split()
    m = int(parts[1]) if len(parts) > 1 else 10
    mutes[message.chat.id] = datetime.now() + timedelta(minutes=m)
    logging.info(f"🔇 Мут установлен: chat={message.chat.id} до {mutes[message.chat.id]}")
    await send_confirm(message.chat.id, f"🔇 <b>Мут на {m} мин</b>", message.business_connection_id)


@dp.business_message(F.text.startswith(".unmute"))
async def b_unmute(message: types.Message):
    logging.info(f"🔵 B_UNMUTE: chat={message.chat.id}")
    if not await is_owner(message):
        return
    if not await check_business_subscription(message):
        return
    was_muted = message.chat.id in mutes
    mutes.pop(message.chat.id, None)
    warns.pop(message.chat.id, None)
    await delete_cmd(message)
    if was_muted:
        await send_confirm(message.chat.id, "🔊 <b>Мут снят</b>", message.business_connection_id)
    else:
        await send_confirm(message.chat.id, "ℹ️ <b>Мут не был активен</b>", message.business_connection_id)


@dp.business_message(F.text.startswith(".warn"))
async def b_warn(message: types.Message):
    logging.info(f"🔵 B_WARN: chat={message.chat.id}")
    if not await is_owner(message):
        return
    if not await check_business_subscription(message):
        return
    parts = message.text.split()
    n = int(parts[1]) if len(parts) > 1 else 1
    t = message.chat.id
    await delete_cmd(message)
    warns[t] = min(warns.get(t, 0) + n, WARN_LIMIT)
    text = f"⚠️ <b>Предупреждений: {warns[t]}/{WARN_LIMIT}</b>"
    msg_id = warn_messages.get(t)
    if msg_id:
        try:
            await bot.edit_message_text(
                business_connection_id=message.business_connection_id,
                chat_id=message.chat.id,
                message_id=msg_id,
                text=text,
                parse_mode="HTML",
            )
        except:
            new_msg = await bot.send_message(
                message.chat.id, text,
                business_connection_id=message.business_connection_id,
                parse_mode="HTML",
            )
            warn_messages[t] = new_msg.message_id
    else:
        new_msg = await bot.send_message(
            message.chat.id, text,
            business_connection_id=message.business_connection_id,
            parse_mode="HTML",
        )
        warn_messages[t] = new_msg.message_id
    if warns[t] >= WARN_LIMIT:
        mutes[t] = datetime.now() + timedelta(minutes=WARN_MUTE_MINUTES)


@dp.business_message(F.text.startswith(".unwarn"))
async def b_unwarn(message: types.Message):
    logging.info(f"🔵 B_UNWARN: chat={message.chat.id}")
    if not await is_owner(message):
        return
    if not await check_business_subscription(message):
        return
    t = message.chat.id
    warns.pop(t, None)
    mutes.pop(t, None)
    await delete_cmd(message)
    await send_confirm(message.chat.id, "✅ <b>Предупреждения сняты</b>", message.business_connection_id)


@dp.business_message(F.text.startswith(".spam"))
async def b_spam(message: types.Message):
    logging.info(f"🔵 B_SPAM: chat={message.chat.id}")
    if not await is_owner(message):
        return
    if not await check_business_subscription(message):
        return
    await delete_cmd(message)
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        return
    try:
        n = min(int(parts[1]), 50)
    except:
        n = 1
    for _ in range(n):
        try:
            await bot.send_message(
                message.chat.id, parts[2],
                business_connection_id=message.business_connection_id,
            )
            await asyncio.sleep(0.15)
        except Exception as e:
            logging.error(f"spam send: {e}")
            await asyncio.sleep(0.4)


@dp.business_message(F.text.startswith(".clone"))
async def b_clone(message: types.Message):
    logging.info(f"🔵 B_CLONE: chat={message.chat.id}")
    if not await is_owner(message):
        return
    if not await check_business_subscription(message):
        return
    parts = message.text.split()
    state = parts[1].lower() if len(parts) > 1 else "on"
    is_on = (state == "on")
    clone[message.chat.id] = is_on
    await delete_cmd(message)
    await send_confirm(
        message.chat.id,
        f"🔄 <b>Автоповтор {'включён' if is_on else 'выключен'}</b>",
        message.business_connection_id,
    )


@dp.business_message(F.text.startswith(".st"))
async def b_st(message: types.Message):
    logging.info(f"🔵 B_ST: chat={message.chat.id}")
    if not await is_owner(message):
        return
    if not await check_business_subscription(message):
        return
    await delete_cmd(message)
    text = message.text[3:].strip()
    if not text:
        return
    for word in text.split():
        try:
            await bot.send_message(
                message.chat.id, word,
                business_connection_id=message.business_connection_id,
            )
            await asyncio.sleep(0.15)
        except Exception as e:
            logging.error(f"st send: {e}")
            await asyncio.sleep(0.4)


@dp.business_message(F.text.startswith(".history"))
async def b_history(message: types.Message):
    logging.info(f"🔵 B_HISTORY: chat={message.chat.id}")
    if not await is_owner(message):
        return
    if not await check_business_subscription(message):
        return
    t = message.chat.id
    parts = message.text.split()
    n = int(parts[1]) if len(parts) > 1 else 10
    await delete_cmd(message)
    if t not in message_cache or not message_cache[t]:
        return
    items = sorted(message_cache[t].items(), key=lambda x: x[1]["time"])[-n:]
    owner_id = await get_owner_id(message.business_connection_id)
    text = f"📜 <b>Последние {len(items)} сообщений:</b>\n\n"
    for msg_id, data in items:
        sender = "Ты" if data["sender"] == owner_id else "Собеседник"
        text += f"<b>{sender}</b> ({data['time']}):\n<code>{data['text'][:200]}</code>\n\n"
    if len(text) > 4000:
        text = text[:4000] + "\n...(обрезано)"
    try:
        msg = await bot.send_message(
            message.chat.id, text,
            parse_mode="HTML",
            business_connection_id=message.business_connection_id,
        )
        asyncio.create_task(auto_delete(message.chat.id, msg.message_id, message.business_connection_id, 30))
    except:
        pass


# ================== ГЛАВНЫЙ ОБРАБОТЧИК ==================
@dp.business_message()
async def b_default(message: types.Message):
    try:
        print(f"🔵 B_DEFAULT: chat={message.chat.id} from={message.from_user.id if message.from_user else '?'} text={(message.text or '')[:40]!r}")
        logging.info(f"🔵 B_DEFAULT: chat={message.chat.id} from={message.from_user.id if message.from_user else '?'} text={(message.text or '')[:40]!r}")
    except Exception as e:
        logging.error(f"log error: {e}")

    t = message.chat.id
    owner_id = await get_owner_id(message.business_connection_id)
    msg_from = message.from_user.id if message.from_user else 0
    text = message.text or ""

    if t not in message_cache:
        message_cache[t] = {}
    message_cache[t][message.message_id] = {
        "text": text or "[медиа]",
        "time": message.date.strftime("%Y-%m-%d %H:%M:%S"),
        "sender": msg_from,
    }
    if len(message_cache[t]) > 200:
        oldest = sorted(message_cache[t].keys())[0]
        message_cache[t].pop(oldest, None)

    # МУТ
    if t in mutes:
        if mutes[t] > datetime.now():
            if msg_from != owner_id:
                logging.info(f"🔇 Собеседник замучен, удаляю {message.message_id}")
                ok = await delete_silent(t, message.message_id, message.business_connection_id)
                logging.info(f"🔇 Удаление: {'OK' if ok else 'FAIL'}")
            return
        else:
            mutes.pop(t, None)
            warns.pop(t, None)

    # CLONE
    if clone.get(t) and text and msg_from != owner_id and not text.startswith("."):
        try:
            await bot.send_message(
                t, text,
                business_connection_id=message.business_connection_id,
            )
        except Exception as e:
            logging.error(f"clone: {e}")


# ================== ЗАПУСК ==================
async def main():
    me = await bot.get_me()
    bot.username = me.username
    print(f"✅ Bot started: @{me.username}")
    logging.info(f"✅ Bot started: @{me.username}")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(
        bot,
        drop_pending_updates=True,
        allowed_updates=[
            "message",
            "callback_query",
            "business_connection",
            "business_message",
            "edited_business_message",
            "deleted_business_messages",
        ],
    )


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
