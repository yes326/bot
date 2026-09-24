# -*- coding: utf-8 -*-
"""
AntiSpam Defender Bot — Business-бот с командами в бизнес-чате.
Хранилища: warns, mutes, clone, warn_messages — по chat_id (стабильный).
"""

import os
import logging
import threading
import asyncio
import aiohttp
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
WARN_MUTE_MINUTES = 60

BANNER_PATH = os.path.join(os.path.dirname(__file__), "IMG_20260918_155302_695.jpg")

# ================== ХРАНИЛИЩА ==================
business_owners = {}      # conn_id -> owner_id
subscriptions = {}        # user_id -> datetime
pending_payments = {}
used_trials = set()
message_cache = {}        # chat_id -> {msg_id: {...}}
warns = {}                # chat_id -> count
mutes = {}                # chat_id -> datetime
clone = {}                # chat_id -> bool
warn_messages = {}        # chat_id -> message_id
referrals = {}
username_cache = {}
last_conn_by_chat = {}    # chat_id -> conn_id

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
    """Прямой вызов Bot API через aiohttp."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data) as resp:
                result = await resp.json()
                if not result.get("ok"):
                    logging.error(f"❌ bot_api({method}): {result}")
                    return None
                return result
    except Exception as e:
        logging.error(f"❌ bot_api({method}): {type(e).__name__}: {e}")
        return None


async def delete_business_msg(conn_id, message_ids):
    if not isinstance(message_ids, list):
        message_ids = [message_ids]
    return await bot_api("deleteBusinessMessages", {
        "business_connection_id": conn_id,
        "message_ids": message_ids,
    })


async def auto_delete(chat_id, message_id, conn_id, seconds=3):
    await asyncio.sleep(seconds)
    try:
        await delete_business_msg(conn_id, [message_id])
    except Exception as e:
        logging.error(f"auto_delete failed: {e}")


async def delete_cmd(message: types.Message):
    if not message.business_connection_id:
        return
    try:
        await delete_business_msg(message.business_connection_id, [message.message_id])
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


async def send_confirm(chat_id, text, conn_id, seconds=None):
    try:
        msg = await bot.send_message(
            chat_id, text,
            business_connection_id=conn_id,
            parse_mode="HTML",
        )
        if seconds is not None:
            asyncio.create_task(auto_delete(chat_id, msg.message_id, conn_id, seconds))
        return msg
    except Exception as e:
        logging.error(f"send_confirm failed: {e}")
        return None


async def delete_warn_msg(chat_id):
    """Удаляет предыдущее warn-сообщение для этого чата."""
    old_msg_id = warn_messages.get(chat_id)
    conn_id = last_conn_by_chat.get(chat_id)
    if old_msg_id and conn_id:
        try:
            await delete_business_msg(conn_id, [old_msg_id])
            logging.info(f"🗑 Удалено warn-сообщение {old_msg_id}")
        except Exception as e:
            logging.error(f"del warn msg: {e}")
    warn_messages.pop(chat_id, None)


# ================== ПОДПИСКА ==================
async def check_subscription(user_id):
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status not in ("left", "kicked")
    except Exception as e:
        logging.error(f"sub check: {e}")
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
        business_owners[business_connection_id] = conn.user.id
        return conn.user.id
    except Exception as e:
        logging.error(f"get_owner_id: {e}")
        return None


async def is_owner(message: types.Message):
    owner_id = await get_owner_id(message.business_connection_id)
    return owner_id is not None and message.from_user.id == owner_id


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
                    await bot.send_message(referrer_id,
                        "🎁 <b>Новый друг присоединился!</b>\n+3 дня к подписке.",
                        parse_mode="HTML")
                except: pass
        except ValueError: pass

    if not await check_subscription(user_id):
        await message.answer(
            "⚠️ <b>Для использования бота нужно подписаться на наш канал.</b>\n\n"
            "📢 Подпишись и нажми «✅ Я подписался».",
            parse_mode="HTML", reply_markup=subscribe_kb())
        return
    try:
        await message.answer_photo(
            photo=types.FSInputFile(BANNER_PATH),
            caption="🏠 <b>Главное меню</b>\n\nВыбери, что тебя интересует 👇",
            parse_mode="HTML", reply_markup=main_menu())
    except Exception as e:
        logging.error(f"Баннер: {e}")
        await message.answer("🏠 <b>Главное меню</b>\n\nВыбери 👇", parse_mode="HTML", reply_markup=main_menu())


@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(call: types.CallbackQuery):
    if await check_subscription(call.from_user.id):
        try: await call.message.delete()
        except: pass
        try:
            await call.message.answer_photo(
                photo=types.FSInputFile(BANNER_PATH),
                caption="🏠 <b>Главное меню</b>\n\nВыбери 👇",
                parse_mode="HTML", reply_markup=main_menu())
        except:
            await call.message.answer("🏠 <b>Главное меню</b>\n\nВыбери 👇", parse_mode="HTML", reply_markup=main_menu())
    else:
        await call.answer("❌ Ты ещё не подписался!", show_alert=True)


@dp.callback_query(F.data == "back_main")
async def cb_back(call: types.CallbackQuery):
    try: await call.message.delete()
    except: pass
    try:
        await call.message.answer_photo(
            photo=types.FSInputFile(BANNER_PATH),
            caption="🏠 <b>Главное меню</b>\n\nВыбери 👇",
            parse_mode="HTML", reply_markup=main_menu())
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
        status = f"активна до {current.strftime('%d.%m.%Y')} (осталось {(current-now).days} дн.)"
    trial_text = f"🎁 Пробный период — {TRIAL_DAYS} дней\n\n" if user_id not in used_trials else ""
    await call.message.answer(
        f"💎 <b>Подписка</b>\n\n📌 Статус: <b>{status}</b>\n\n{trial_text}Выбери 👇",
        parse_mode="HTML", reply_markup=plans_kb(user_id))


@dp.callback_query(F.data == "trial")
async def cb_trial(call: types.CallbackQuery):
    user_id = call.from_user.id
    now = datetime.now()
    if user_id in used_trials:
        await call.answer("❌ Ты уже использовал!", show_alert=True); return
    if subscriptions.get(user_id) and subscriptions[user_id] > now:
        await call.answer("❌ Уже есть подписка!", show_alert=True); return
    used_trials.add(user_id)
    until = now + timedelta(days=TRIAL_DAYS)
    subscriptions[user_id] = until
    await call.message.answer(
        f"🎁 <b>Пробный период активирован!</b>\n\n💎 {TRIAL_DAYS} дней.\n📅 До: <b>{until.strftime('%d.%m.%Y %H:%M')}</b>",
        parse_mode="HTML")
    await call.answer("Активировано ✅")


@dp.callback_query(F.data == "ref")
async def cb_ref(call: types.CallbackQuery):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{call.from_user.id}"
    invited = len(referrals.get(call.from_user.id, set()))
    await call.message.answer(
        f"👥 <b>Пригласить друга</b>\n\n<code>{link}</code>\n\n🎁 +3 дня за друга!\n📊 Приглашено: <b>{invited}</b>",
        parse_mode="HTML", reply_markup=back_kb())
    await call.answer()


@dp.callback_query(F.data == "howto")
async def cb_howto(call: types.CallbackQuery):
    await call.message.answer(
        "📚 <b>Как подключить:</b>\n\n"
        "1️⃣ Настройки → Аккаунт → Автоматизация чатов\n"
        "2️⃣ Выбери <b>AntiSpam Defender</b>\n"
        "3️⃣ Дай разрешения: ✅ Чтение, ✅ Ответы, ✅ Удаление входящих/исходящих\n\n"
        "4️⃣ Пиши команды <b>в бизнес-чате</b>:\n"
        "<code>.mute 10</code>",
        parse_mode="HTML", reply_markup=back_kb())
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
        f"💳 <b>Оплата «{p['label']}»</b>\n\n💰 {p['rub']}₽\n💳 Карта: <code>{CARD_NUMBER}</code>\n\n📸 После перевода нажми «Я оплатил».",
        parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("paid_"))
async def cb_paid(call: types.CallbackQuery):
    plan = call.data.split("_")[1]
    pending_payments[call.from_user.id] = {"plan": plan}
    await call.message.answer("📸 Пришли скриншот оплаты.")


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
        await bot.send_photo(chat_id=OWNER_ID, photo=message.photo[-1].file_id,
            caption=f"💰 <b>Оплата</b>\n\n👤 @{user.username or user.first_name} (<code>{user.id}</code>)\n📦 {PRICES[plan]['label']} — {PRICES[plan]['rub']}₽",
            parse_mode="HTML", reply_markup=owner_kb)
        await message.answer("✅ Скриншот отправлен!")
        pending_payments.pop(user_id, None)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await message.answer("⚠️ Ошибка. Свяжитесь с @ysorn.")


@dp.callback_query(F.data.startswith("approve_"))
async def cb_approve(call: types.CallbackQuery):
    if call.from_user.id != OWNER_ID:
        await call.answer("❌ Нет доступа", show_alert=True); return
    parts = call.data.split("_")
    user_id = int(parts[1]); plan = parts[2]
    days = PRICES[plan]["days"]; now = datetime.now()
    current = subscriptions.get(user_id, now)
    subscriptions[user_id] = max(current, now) + timedelta(days=days)
    try:
        await bot.send_message(user_id,
            f"✅ <b>Оплата подтверждена!</b>\n\n💎 {days} дней.\n📅 До: <b>{subscriptions[user_id].strftime('%d.%m.%Y')}</b>",
            parse_mode="HTML")
    except: pass
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n✅ <b>Подтверждено</b>", parse_mode="HTML")
    await call.answer("Активировано")


@dp.callback_query(F.data.startswith("reject_"))
async def cb_reject(call: types.CallbackQuery):
    if call.from_user.id != OWNER_ID:
        await call.answer("❌ Нет доступа", show_alert=True); return
    user_id = int(call.data.split("_")[1])
    try: await bot.send_message(user_id, "❌ Оплата отклонена.")
    except: pass
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n❌ <b>Отклонено</b>", parse_mode="HTML")
    await call.answer("Отклонено")


# ================== ЛС ВЛАДЕЛЬЦУ ==================
@dp.message(F.chat.type == "private", ~F.text.startswith("/"))
async def forward_to_owner(message: types.Message):
    if message.from_user.id == OWNER_ID:
        return
    if message.text and message.text.startswith("."):
        return
    try:
        text = message.text or "[медиа]"
        user = message.from_user
        await bot.send_message(OWNER_ID,
            f"📩 <b>Сообщение</b>\n\n👤 @{user.username or user.first_name} (<code>{user.id}</code>)\n📝 <code>{text[:500]}</code>",
            parse_mode="HTML")
    except Exception as e:
        logging.error(f"ЛС: {e}")


# ================== ОБРАБОТЧИК БИЗНЕС-КОМАНД ==================
async def handle_business_command(message: types.Message, text: str):
    conn_id = message.business_connection_id
    t = message.chat.id    # ← стабильный ключ
    logging.info(f"⚙️ Обрабатываю команду: {text[:40]!r} chat={t} conn={conn_id}")

    # .help — команда НЕ удаляется
    if text == ".help":
        await send_confirm(t,
            "📖 <b>Команды:</b>\n\n"
            "<code>.mute N</code> · <code>.unmute</code>\n"
            "<code>.warn N</code> · <code>.unwarn</code>\n"
            "<code>.spam N текст</code>\n"
            "<code>.st текст</code>\n"
            "<code>.clone on/off</code>\n"
            "<code>.history N</code>",
            conn_id)
        return

    # Удаляем саму команду
    await delete_cmd(message)

    parts = text.split()

    # ========== .mute N ==========
    if text.startswith(".mute"):
        try: m = int(parts[1]) if len(parts) > 1 else 10
        except ValueError: m = 10
        mutes[t] = datetime.now() + timedelta(minutes=m)
        logging.info(f"🔇 Мут установлен chat={t} до {mutes[t]}")
        await send_confirm(t, f"🔇 <b>Мут на {m} мин</b>", conn_id)
        return

    # ========== .unmute ==========
    if text.startswith(".unmute"):
        was = t in mutes
        mutes.pop(t, None)
        warns.pop(t, None)
        await delete_warn_msg(t)
        await send_confirm(t, "🔊 <b>Мут снят</b>" if was else "ℹ️ <b>Мут не активен</b>", conn_id)
        return

    # ========== .warn N ==========
    if text.startswith(".warn"):
        try: n = int(parts[1]) if len(parts) > 1 else 1
        except ValueError: n = 1
        warns[t] = min(warns.get(t, 0) + n, WARN_LIMIT)
        logging.info(f"⚠️ Warn: chat={t} → {warns[t]}/{WARN_LIMIT}")

        # Удаляем старое warn-сообщение
        await delete_warn_msg(t)

        # Отправляем новое
        text_warn = f"⚠️ <b>Предупреждений: {warns[t]}/{WARN_LIMIT}</b>"
        new_msg = await bot.send_message(t, text_warn,
            business_connection_id=conn_id, parse_mode="HTML")
        if new_msg:
            warn_messages[t] = new_msg.message_id
            logging.info(f"📩 Warn-сообщение {new_msg.message_id} ({warns[t]}/{WARN_LIMIT})")

        # Авто-мут при лимите
        if warns[t] >= WARN_LIMIT:
            mutes[t] = datetime.now() + timedelta(minutes=WARN_MUTE_MINUTES)
            logging.info(f"🔇 Warn-limit достигнут, авто-мут chat={t} на {WARN_MUTE_MINUTES} мин")

            await delete_warn_msg(t)
            text_muted = (
                f"⚠️ <b>Предупреждений: {WARN_LIMIT}/{WARN_LIMIT}</b>\n"
                f"🔇 <b>Мут на {WARN_MUTE_MINUTES} мин!</b>"
            )
            new_msg = await bot.send_message(t, text_muted,
                business_connection_id=conn_id, parse_mode="HTML")
            if new_msg:
                warn_messages[t] = new_msg.message_id
        return

    # ========== .unwarn ==========
    if text.startswith(".unwarn"):
        warns.pop(t, None)
        mutes.pop(t, None)
        await delete_warn_msg(t)
        await send_confirm(t, "✅ <b>Предупреждения сняты (0/5)</b>", conn_id)
        return

    # ========== .spam N текст ==========
    if text.startswith(".spam"):
        parts2 = text.split(maxsplit=2)
        if len(parts2) < 3:
            await send_confirm(t, "ℹ️ <code>.spam N текст</code>", conn_id)
            return
        try: n = min(int(parts2[1]), 50)
        except: n = 1
        for _ in range(n):
            try:
                await bot.send_message(t, parts2[2], business_connection_id=conn_id)
                await asyncio.sleep(0.15)
            except Exception as e:
                logging.error(f"spam: {e}")
                break
        return

    # ========== .clone on/off ==========
    if text.startswith(".clone"):
        state = parts[1].lower() == "on" if len(parts) > 1 else True
        clone[t] = state
        await send_confirm(t, f"🔄 <b>Автоповтор {'включён' if state else 'выключен'}</b>", conn_id)
        return

    # ========== .st текст ==========
    if text.startswith(".st"):
        body = text[3:].strip()
        if not body: return
        for word in body.split():
            try:
                await bot.send_message(t, word, business_connection_id=conn_id)
                await asyncio.sleep(0.15)
            except: break
        return

    # ========== .history N ==========
    if text.startswith(".history"):
        try: n = int(parts[1]) if len(parts) > 1 else 10
        except: n = 10
        cache = message_cache.get(t, {})
        if not cache:
            await send_confirm(t, "📭 История пуста", conn_id); return
        items = sorted(cache.items(), key=lambda x: x[1]["time"])[-n:]
        out = f"📜 <b>Последние {len(items)}:</b>\n\n"
        for _, data in items:
            out += f"<code>{data['time']}</code> <b>{data['sender']}</b>: {data['text'][:100]}\n"
        await send_confirm(t, out[:4000], conn_id)
        return


# ================== BUSINESS_MESSAGE ==================
@dp.business_message()
async def b_default(message: types.Message):
    conn_id = message.business_connection_id
    t = message.chat.id
    owner_id = await get_owner_id(conn_id)
    msg_from = message.from_user.id if message.from_user else 0
    text = message.text or ""

    logging.info(f"🔵 BUSINESS: chat={t} from={msg_from} owner={owner_id} mute={'YES' if t in mutes else 'no'} text={text[:40]!r}")

    if conn_id:
        last_conn_by_chat[t] = conn_id
    if message.from_user and message.from_user.username:
        username_cache[message.from_user.username.lower()] = msg_from

    if t not in message_cache:
        message_cache[t] = {}
    message_cache[t][message.message_id] = {
        "text": text or "[медиа]",
        "time": message.date.strftime("%H:%M:%S"),
        "sender": msg_from,
    }
    if len(message_cache[t]) > 200:
        oldest = sorted(message_cache[t].keys())[0]
        message_cache[t].pop(oldest, None)

    # КОМАНДА ОТ ВЛАДЕЛЬЦА
    if msg_from == owner_id and text.startswith("."):
        await handle_business_command(message, text)
        return

    # МУТ — проверяем по chat_id
    if t in mutes:
        if mutes[t] > datetime.now():
            if msg_from != owner_id:
                logging.info(f"🔇 Мут активен, удаляю {message.message_id}")
                ok = await delete_silent(t, message.message_id, conn_id)
                logging.info(f"🔇 Удаление: {'OK' if ok else 'FAIL'}")
            return
        else:
            mutes.pop(t, None)
            warns.pop(t, None)
            await delete_warn_msg(t)

    # КЛОН — по chat_id
    if clone.get(t) and text and msg_from != owner_id and not text.startswith("."):
        try:
            await bot.send_message(t, text, business_connection_id=conn_id)
        except Exception as e:
            logging.error(f"clone: {e}")


# ================== EDITED_BUSINESS_MESSAGE ==================
@dp.edited_business_message()
async def b_edited(message: types.Message):
    conn_id = message.business_connection_id
    t = message.chat.id
    owner_id = await get_owner_id(conn_id)
    msg_from = message.from_user.id if message.from_user else 0
    text = message.text or ""

    logging.info(f"🟡 EDITED: chat={t} from={msg_from} owner={owner_id} text={text[:40]!r}")

    if conn_id:
        last_conn_by_chat[t] = conn_id

    if msg_from == owner_id and text.startswith("."):
        await handle_business_command(message, text)
        return


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
            "message", "callback_query",
            "business_connection", "business_message",
            "edited_business_message", "deleted_business_messages",
        ],
    )


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
