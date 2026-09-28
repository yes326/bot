# -*- coding: utf-8 -*-
"""
AntiSpam Defender Bot — Business-бот.
Обход мута работает для любых не-бот сообщений.
"""

import os
import logging
import threading
import asyncio
import aiohttp
import time
import aiosqlite
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SetMyName

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

BOT_RATE_LIMIT = 5
BOT_RATE_WINDOW = 60

ZWSP = "\u200b"
ZWNJ = "\u200c"
ZWJ  = "\u200d"
INVISIBLES = [ZWSP, ZWNJ, ZWJ]

SIMILAR = {
    'а': 'a', 'е': 'e', 'о': 'o', 'р': 'p', 'с': 'c', 'у': 'y',
    'х': 'x', 'А': 'A', 'В': 'B', 'Е': 'E', 'К': 'K', 'М': 'M',
    'Н': 'H', 'О': 'O', 'Р': 'P', 'С': 'C', 'Т': 'T', 'У': 'Y',
    'Х': 'X', 'і': 'i', 'ї': 'i', 'ё': 'e', 'й': 'u',
}

DB_PATH = "bot.db"
NAME_UPDATE_INTERVAL = 3600

BANNER_PATH = os.path.join(os.path.dirname(__file__), "IMG_20260918_155302_695.jpg")

# ================== ХРАНИЛИЩА ==================
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
username_cache = {}
last_conn_by_chat = {}
nonmute_active = {}
bot_rate = defaultdict(list)

# ================== БАЗА ==================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TEXT
            )
        """)
        await db.commit()


async def register_user(user_id, username, first_name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at) VALUES (?,?,?,?)",
            (user_id, username, first_name, datetime.now().isoformat()),
        )
        await db.commit()


async def get_total_users():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        row = await cur.fetchone()
        return row[0] if row else 0


async def get_last_users(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users ORDER BY joined_at DESC LIMIT ?", (limit,))
        return await cur.fetchall()


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
async def bot_api(method, data):
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


async def delete_cmd(message):
    if not message.business_connection_id:
        return
    try:
        await delete_business_msg(message.business_connection_id, [message.message_id])
        logging.info(f"✅ Удалена команда: {(message.text or '')[:30]}")
    except Exception as e:
        logging.error(f"❌ Ошибка удаления: {type(e).__name__}: {e}")


async def delete_silent(chat_id, message_id, conn_id):
    try:
        result = await delete_business_msg(conn_id, [message_id])
        return result is not None
    except Exception as e:
        logging.error(f"❌ delete_silent: {type(e).__name__}: {e}")
        return False


async def send_confirm(chat_id, text, conn_id, seconds=None):
    try:
        msg = await bot.send_message(chat_id, text, business_connection_id=conn_id, parse_mode="HTML")
        if seconds is not None:
            asyncio.create_task(auto_delete(chat_id, msg.message_id, conn_id, seconds))
        return msg
    except Exception as e:
        logging.error(f"send_confirm failed: {e}")
        return None


async def delete_warn_msg(chat_id):
    old_msg_id = warn_messages.get(chat_id)
    conn_id = last_conn_by_chat.get(chat_id)
    if old_msg_id and conn_id:
        try:
            await delete_business_msg(conn_id, [old_msg_id])
        except Exception as e:
            logging.error(f"del warn msg: {e}")
    warn_messages.pop(chat_id, None)


def check_bot_rate(bot_id):
    now = time.time()
    history = bot_rate[bot_id]
    history[:] = [t for t in history if now - t < BOT_RATE_WINDOW]
    if len(history) >= BOT_RATE_LIMIT:
        return False
    history.append(now)
    return True


def distort(text, level=3):
    if not text:
        return text
    result = []
    for i, ch in enumerate(text):
        if ch in SIMILAR:
            result.append(SIMILAR[ch])
        else:
            result.append(ch)
        if i % 2 == 0:
            result.append(INVISIBLES[i % len(INVISIBLES)])
    distorted = "".join(result)
    if len(distorted) > 4000:
        distorted = distorted[:4000]
    return distorted


# ================== ФОНОВАЯ ЗАДАЧА ==================
async def update_bot_name():
    try:
        total = await get_total_users()
        new_name = f"AntiSpam Defender | {total}"
        if len(new_name) > 64:
            new_name = f"AntiSpam | {total}"
        await bot(SetMyName(name=new_name))
        logging.info(f"🏷 Имя бота: {new_name}")
    except Exception as e:
        logging.error(f"❌ Ошибка обновления имени: {e}")


async def background_name_updater():
    await asyncio.sleep(30)
    await update_bot_name()
    while True:
        await asyncio.sleep(NAME_UPDATE_INTERVAL)
        await update_bot_name()


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
async def get_owner_id(conn_id):
    if not conn_id:
        return None
    if conn_id in business_owners:
        return business_owners[conn_id]
    try:
        conn = await bot.get_business_connection(conn_id)
        business_owners[conn_id] = conn.user.id
        return conn.user.id
    except Exception as e:
        logging.error(f"get_owner_id: {e}")
        return None


async def find_connection_by_target(target):
    target = target.strip().lstrip("@").lower()
    if target in username_cache:
        uid = username_cache[target]
        conn = last_conn_by_chat.get(uid)
        if conn:
            return conn, uid
    try:
        target_id = int(target)
        conn = last_conn_by_chat.get(target_id)
        if conn:
            return conn, target_id
    except ValueError:
        pass
    return None, None


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
async def start_cmd(message):
    user_id = message.from_user.id
    await register_user(user_id, message.from_user.username or "", message.from_user.first_name or "")
    total = await get_total_users()
    logging.info(f"👤 /start от {user_id} | всего: {total}")

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
                        "🎁 <b>Новый друг присоединился!</b>\n+3 дня к подписке.", parse_mode="HTML")
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


# ================== /STATS ==================
@dp.message(F.text == "/stats", F.from_user.id == OWNER_ID)
async def stats_cmd(message):
    total = await get_total_users()
    with_sub = sum(1 for u in subscriptions if subscriptions[u] > datetime.now())
    trials = len(used_trials)
    last_users = await get_last_users(10)
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Юзеров: <b>{total}</b>\n"
        f"💎 Подписок: <b>{with_sub}</b>\n"
        f"🎁 Триалов: <b>{trials}</b>\n\n🕐 <b>Последние 10:</b>\n"
    )
    for row in last_users:
        name = row["first_name"] or row["username"] or str(row["user_id"])
        uname = f"@{row['username']}" if row["username"] else ""
        text += f"• {name} {uname} (<code>{row['user_id']}</code>)\n"
    await message.answer(text, parse_mode="HTML")


# ================== CALLBACKS ==================
@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(call):
    if await check_subscription(call.from_user.id):
        try: await call.message.delete()
        except: pass
        try:
            await call.message.answer_photo(photo=types.FSInputFile(BANNER_PATH),
                caption="🏠 <b>Главное меню</b>\n\nВыбери 👇",
                parse_mode="HTML", reply_markup=main_menu())
        except:
            await call.message.answer("🏠 <b>Главное меню</b>\n\nВыбери 👇", parse_mode="HTML", reply_markup=main_menu())
    else:
        await call.answer("❌ Ты ещё не подписался!", show_alert=True)


@dp.callback_query(F.data == "back_main")
async def cb_back(call):
    try: await call.message.delete()
    except: pass
    try:
        await call.message.answer_photo(photo=types.FSInputFile(BANNER_PATH),
            caption="🏠 <b>Главное меню</b>\n\nВыбери 👇",
            parse_mode="HTML", reply_markup=main_menu())
    except:
        await call.message.answer("🏠 <b>Главное меню</b>\n\nВыбери 👇", parse_mode="HTML", reply_markup=main_menu())


@dp.callback_query(F.data == "cmd_list")
async def cb_cmds(call):
    await call.message.answer(
        "📖 <b>Команды:</b>\n\n"
        "<code>.mute N</code> · <code>.unmute</code>\n"
        "<code>.warn N</code> · <code>.unwarn</code>\n"
        "<code>.spam N текст</code>\n"
        "<code>.st текст</code>\n"
        "<code>.clone on/off</code>\n"
        "<code>.nonmute on/off</code>",
        parse_mode="HTML", reply_markup=back_kb())


@dp.callback_query(F.data == "sub_menu")
async def cb_sub(call):
    user_id = call.from_user.id
    now = datetime.now()
    current = subscriptions.get(user_id)
    status = "не активна"
    if current and current > now:
        status = f"активна до {current.strftime('%d.%m.%Y')}"
    trial_text = f"🎁 Пробный период — {TRIAL_DAYS} дней\n\n" if user_id not in used_trials else ""
    await call.message.answer(
        f"💎 <b>Подписка</b>\n\n📌 Статус: <b>{status}</b>\n\n{trial_text}Выбери 👇",
        parse_mode="HTML", reply_markup=plans_kb(user_id))


@dp.callback_query(F.data == "trial")
async def cb_trial(call):
    user_id = call.from_user.id
    now = datetime.now()
    if user_id in used_trials:
        await call.answer("❌ Уже использовал!", show_alert=True); return
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
async def cb_ref(call):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{call.from_user.id}"
    invited = len(referrals.get(call.from_user.id, set()))
    await call.message.answer(
        f"👥 <b>Пригласить друга</b>\n\n<code>{link}</code>\n\n🎁 +3 дня!\n📊 Приглашено: <b>{invited}</b>",
        parse_mode="HTML", reply_markup=back_kb())
    await call.answer()


@dp.callback_query(F.data == "howto")
async def cb_howto(call):
    await call.message.answer(
        "📚 <b>Как подключить:</b>\n\n"
        "1️⃣ Настройки → Аккаунт → Автоматизация чатов\n"
        "2️⃣ Выбери <b>AntiSpam Defender</b>\n"
        "3️⃣ Дай разрешения: ✅ Чтение, ✅ Ответы, ✅ Удаление\n\n"
        "4️⃣ Пиши команды <b>в бизнес-чате</b>.",
        parse_mode="HTML", reply_markup=back_kb())
    await call.answer()


@dp.callback_query(F.data.startswith("pay_"))
async def cb_pay(call):
    plan = call.data.split("_")[1]
    p = PRICES[plan]
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{plan}")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="sub_menu")],
    ])
    await call.message.answer(
        f"💳 <b>Оплата «{p['label']}»</b>\n\n💰 {p['rub']}₽\n💳 Карта: <code>{CARD_NUMBER}</code>",
        parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("paid_"))
async def cb_paid(call):
    plan = call.data.split("_")[1]
    pending_payments[call.from_user.id] = {"plan": plan}
    await call.message.answer("📸 Пришли скриншот оплаты.")


@dp.message(F.photo)
async def on_screenshot(message):
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
        await message.answer("✅ Отправлено!")
        pending_payments.pop(user_id, None)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await message.answer("⚠️ Ошибка. Свяжитесь с @ysorn.")


@dp.callback_query(F.data.startswith("approve_"))
async def cb_approve(call):
    if call.from_user.id != OWNER_ID:
        await call.answer("❌ Нет доступа", show_alert=True); return
    parts = call.data.split("_")
    user_id = int(parts[1]); plan = parts[2]
    days = PRICES[plan]["days"]; now = datetime.now()
    current = subscriptions.get(user_id, now)
    subscriptions[user_id] = max(current, now) + timedelta(days=days)
    try:
        await bot.send_message(user_id, f"✅ <b>Оплата подтверждена!</b>\n\n💎 {days} дней.", parse_mode="HTML")
    except: pass
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n✅ <b>Подтверждено</b>", parse_mode="HTML")
    await call.answer("Активировано")


@dp.callback_query(F.data.startswith("reject_"))
async def cb_reject(call):
    if call.from_user.id != OWNER_ID:
        await call.answer("❌ Нет доступа", show_alert=True); return
    user_id = int(call.data.split("_")[1])
    try: await bot.send_message(user_id, "❌ Оплата отклонена.")
    except: pass
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n❌ <b>Отклонено</b>", parse_mode="HTML")
    await call.answer("Отклонено")


# ================== ЛС ВЛАДЕЛЬЦУ ==================
@dp.message(F.chat.type == "private", ~F.text.startswith("/"))
async def forward_to_owner(message):
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


# ================== КОМАНДЫ В ЛИЧКЕ ==================
@dp.message(F.chat.type == "private", F.text.startswith("."))
async def pm_commands(message):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Только владелец может использовать команды.")
        return

    text = message.text.strip()
    parts = text.split()

    if text == ".help":
        await message.answer(
            "📖 <b>Команды (в личке):</b>\n\n"
            "<code>.mute @user N</code>\n"
            "<code>.unmute @user</code>\n"
            "<code>.warn @user N</code>\n"
            "<code>.unwarn @user</code>\n"
            "<code>.nonmute @user on/off</code>\n"
            "<code>.spam @user N текст</code>\n"
            "<code>.clone @user on/off</code>",
            parse_mode="HTML")
        return

    if parts[0] == ".mute" and len(parts) >= 3:
        target = parts[1].lstrip("@")
        try: m = int(parts[2])
        except: m = 10
        conn_id, chat_id = await find_connection_by_target(target)
        if not conn_id:
            await message.answer(f"❌ Не нашёл <b>{target}</b>", parse_mode="HTML"); return
        mutes[chat_id] = datetime.now() + timedelta(minutes=m)
        await bot_api("sendMessage", {"chat_id": chat_id, "text": f"🔇 Мут на {m} мин", "business_connection_id": conn_id})
        await message.answer(f"✅ Мут <b>{target}</b> на {m} мин", parse_mode="HTML")
        return

    if parts[0] == ".unmute" and len(parts) >= 2:
        target = parts[1].lstrip("@")
        conn_id, chat_id = await find_connection_by_target(target)
        if not conn_id:
            await message.answer(f"❌ Не нашёл <b>{target}</b>", parse_mode="HTML"); return
        was = chat_id in mutes
        mutes.pop(chat_id, None); warns.pop(chat_id, None)
        await delete_warn_msg(chat_id)
        await message.answer("✅ Мут снят" if was else "ℹ️ Мут не активен", parse_mode="HTML")
        return

    if parts[0] == ".warn" and len(parts) >= 2:
        target = parts[1].lstrip("@")
        try: n = int(parts[2]) if len(parts) > 2 else 1
        except: n = 1
        conn_id, chat_id = await find_connection_by_target(target)
        if not conn_id:
            await message.answer(f"❌ Не нашёл <b>{target}</b>", parse_mode="HTML"); return
        warns[chat_id] = min(warns.get(chat_id, 0) + n, WARN_LIMIT)
        await delete_warn_msg(chat_id)
        if warns[chat_id] >= WARN_LIMIT:
            mutes[chat_id] = datetime.now() + timedelta(minutes=WARN_MUTE_MINUTES)
            text_warn = (f"⚠️ <b>Предупреждений: {WARN_LIMIT}/{WARN_LIMIT}</b>\n🔇 <b>Мут на {WARN_MUTE_MINUTES} мин!</b>")
        else:
            text_warn = f"⚠️ <b>Предупреждений: {warns[chat_id]}/{WARN_LIMIT}</b>"
        result = await bot_api("sendMessage", {"chat_id": chat_id, "text": text_warn, "parse_mode": "HTML", "business_connection_id": conn_id})
        if result and result.get("ok"):
            warn_messages[chat_id] = result["result"]["message_id"]
        await message.answer(f"✅ Warn <b>{target}</b>: {warns[chat_id]}/{WARN_LIMIT}", parse_mode="HTML")
        return

    if parts[0] == ".unwarn" and len(parts) >= 2:
        target = parts[1].lstrip("@")
        conn_id, chat_id = await find_connection_by_target(target)
        if not conn_id:
            await message.answer(f"❌ Не нашёл <b>{target}</b>", parse_mode="HTML"); return
        warns.pop(chat_id, None); mutes.pop(chat_id, None)
        await delete_warn_msg(chat_id)
        await message.answer("✅ Warn сброшен", parse_mode="HTML")
        return

    if parts[0] == ".nonmute" and len(parts) >= 3:
        target = parts[1].lstrip("@")
        arg = parts[2].lower()
        conn_id, chat_id = await find_connection_by_target(target)
        if not conn_id:
            await message.answer(f"❌ Не нашёл <b>{target}</b>", parse_mode="HTML"); return
        state = arg == "on"
        nonmute_active[chat_id] = state
        if state:
            await bot_api("sendMessage", {"chat_id": chat_id,
                "text": "🛡 <b>Обход мута включён</b>\n\n✅ Теперь вы можете писать, даже когда вас замутили.",
                "parse_mode": "HTML", "business_connection_id": conn_id})
        else:
            await bot_api("sendMessage", {"chat_id": chat_id, "text": "🛡 <b>Обход мута выключен</b>",
                "parse_mode": "HTML", "business_connection_id": conn_id})
        await message.answer(f"🛡 NonMute <b>{target}</b>: {'ВКЛ' if state else 'ВЫКЛ'}", parse_mode="HTML")
        return

    if parts[0] == ".spam" and len(parts) >= 4:
        target = parts[1].lstrip("@")
        try: n = min(int(parts[2]), 50)
        except: n = 1
        body = text.split(maxsplit=3)[3]
        conn_id, chat_id = await find_connection_by_target(target)
        if not conn_id:
            await message.answer(f"❌ Не нашёл <b>{target}</b>", parse_mode="HTML"); return
        for _ in range(n):
            await bot_api("sendMessage", {"chat_id": chat_id, "text": body, "business_connection_id": conn_id})
            await asyncio.sleep(0.15)
        await message.answer(f"✅ Спам в <b>{target}</b> ({n})", parse_mode="HTML")
        return

    if parts[0] == ".clone" and len(parts) >= 3:
        target = parts[1].lstrip("@")
        state = parts[2].lower() == "on"
        conn_id, chat_id = await find_connection_by_target(target)
        if not conn_id:
            await message.answer(f"❌ Не нашёл <b>{target}</b>", parse_mode="HTML"); return
        clone[chat_id] = state
        await message.answer(f"🔄 Клон <b>{target}</b>: {'ВКЛ' if state else 'ВЫКЛ'}", parse_mode="HTML")
        return

    await message.answer("❓ Неизвестная команда. Напиши .help")


# ================== BUSINESS_MESSAGE ==================
@dp.business_message()
async def b_default(message):
    conn_id = message.business_connection_id
    t = message.chat.id
    owner_id = await get_owner_id(conn_id)
    msg_from = message.from_user.id if message.from_user else 0
    is_bot = message.from_user.is_bot if message.from_user else False
    text = message.text or ""

    logging.info(f"🔵 BUSINESS: chat={t} from={msg_from} bot={is_bot} owner={owner_id} "
                 f"mute={'YES' if t in mutes else 'no'} "
                 f"nonmute={'ON' if nonmute_active.get(t) else 'off'} "
                 f"text={text[:40]!r}")

    if conn_id:
        last_conn_by_chat[t] = conn_id
    if message.from_user and message.from_user.username:
        username_cache[message.from_user.username.lower()] = msg_from

    # ============ NONMUTE — без проверки msg_from == owner_id ============
    if (not is_bot and text and not text.startswith(".")
            and nonmute_active.get(t)):
        try:
            distorted = distort(text, level=3)
            r1 = await bot_api("sendMessage", {"chat_id": t, "text": distorted})
            logging.info(f"🛡 NonMute 1: {r1.get('ok') if r1 else False}")

            await asyncio.sleep(0.1)
            distorted2 = distort(text, level=2)
            r2 = await bot_api("sendMessage", {"chat_id": t, "text": distorted2})
            logging.info(f"🛡 NonMute 2: {r2.get('ok') if r2 else False}")
        except Exception as e:
            logging.error(f"nonmute: {e}")

    # КОМАНДА
    if msg_from == owner_id and text.startswith("."):
        await handle_business_command(message, text)
        return

    # ОТ БОТА
    if is_bot and msg_from != bot.id:
        if not check_bot_rate(msg_from):
            return
        if t in mutes and mutes[t] > datetime.now():
            await delete_silent(t, message.message_id, conn_id)
        return

    # КЭШ
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

    # МУТ
    if t in mutes:
        if mutes[t] > datetime.now():
            if msg_from != owner_id:
                await delete_silent(t, message.message_id, conn_id)
            return
        else:
            mutes.pop(t, None); warns.pop(t, None)
            await delete_warn_msg(t)

    # КЛОН
    if clone.get(t) and text and msg_from != owner_id and not text.startswith("."):
        try:
            await bot.send_message(t, text, business_connection_id=conn_id)
        except Exception as e:
            logging.error(f"clone: {e}")


# ================== ОБРАБОТЧИК БИЗНЕС-КОМАНД ==================
async def handle_business_command(message, text):
    conn_id = message.business_connection_id
    t = message.chat.id
    logging.info(f"⚙️ Команда: {text[:40]!r} chat={t} conn={conn_id}")

    if text == ".help":
        await send_confirm(t,
            "📖 <b>Команды:</b>\n\n<code>.mute N</code> · <code>.unmute</code>\n"
            "<code>.warn N</code> · <code>.unwarn</code>\n"
            "<code>.spam N текст</code>\n<code>.st текст</code>\n"
            "<code>.clone on/off</code>\n<code>.nonmute on/off</code>", conn_id)
        return

    await delete_cmd(message)
    parts = text.split()

    if text.startswith(".mute"):
        try: m = int(parts[1]) if len(parts) > 1 else 10
        except ValueError: m = 10
        mutes[t] = datetime.now() + timedelta(minutes=m)
        await send_confirm(t, f"🔇 <b>Мут на {m} мин</b>", conn_id)
        return

    if text.startswith(".unmute"):
        was = t in mutes
        mutes.pop(t, None); warns.pop(t, None)
        await delete_warn_msg(t)
        await send_confirm(t, "🔊 <b>Мут снят</b>" if was else "ℹ️ <b>Мут не активен</b>", conn_id)
        return

    if text.startswith(".warn"):
        try: n = int(parts[1]) if len(parts) > 1 else 1
        except ValueError: n = 1
        warns[t] = min(warns.get(t, 0) + n, WARN_LIMIT)
        await delete_warn_msg(t)
        if warns[t] >= WARN_LIMIT:
            mutes[t] = datetime.now() + timedelta(minutes=WARN_MUTE_MINUTES)
            text_warn = f"⚠️ <b>Предупреждений: {WARN_LIMIT}/{WARN_LIMIT}</b>\n🔇 <b>Мут на {WARN_MUTE_MINUTES} мин!</b>"
        else:
            text_warn = f"⚠️ <b>Предупреждений: {warns[t]}/{WARN_LIMIT}</b>"
        result = await bot_api("sendMessage", {"chat_id": t, "text": text_warn, "parse_mode": "HTML", "business_connection_id": conn_id})
        if result and result.get("ok"):
            warn_messages[t] = result["result"]["message_id"]
        return

    if text.startswith(".unwarn"):
        warns.pop(t, None); mutes.pop(t, None)
        await delete_warn_msg(t)
        await send_confirm(t, "✅ <b>Предупреждения сняты (0/5)</b>", conn_id)
        return

    if text.startswith(".spam"):
        parts2 = text.split(maxsplit=2)
        if len(parts2) < 3:
            await send_confirm(t, "ℹ️ <code>.spam N текст</code>", conn_id); return
        try: n = min(int(parts2[1]), 50)
        except: n = 1
        for _ in range(n):
            await bot_api("sendMessage", {"chat_id": t, "text": parts2[2], "business_connection_id": conn_id})
            await asyncio.sleep(0.15)
        return

    if text.startswith(".clone"):
        state = parts[1].lower() == "on" if len(parts) > 1 else True
        clone[t] = state
        await send_confirm(t, f"🔄 <b>Автоповтор {'включён' if state else 'выключен'}</b>", conn_id)
        return

    if text.startswith(".st"):
        body = text[3:].strip()
        if not body: return
        for word in body.split():
            await bot_api("sendMessage", {"chat_id": t, "text": word, "business_connection_id": conn_id})
            await asyncio.sleep(0.15)
        return

    if text.startswith(".nonmute"):
        if len(parts) > 1:
            arg = parts[1].lower()
            if arg == "on": state = True
            elif arg == "off": state = False
            else:
                await send_confirm(t, "ℹ️ <code>.nonmute on</code> или <code>.nonmute off</code>", conn_id); return
        else:
            state = not nonmute_active.get(t, False)
        nonmute_active[t] = state
        if state:
            await send_confirm(t, "🛡 <b>Обход мута включён</b>\n\n✅ Теперь вы можете писать, даже когда вас замутили.", conn_id)
        else:
            await send_confirm(t, "🛡 <b>Обход мута выключен</b>", conn_id)
        return


# ================== EDITED_BUSINESS_MESSAGE ==================
@dp.edited_business_message()
async def b_edited(message):
    conn_id = message.business_connection_id
    t = message.chat.id
    owner_id = await get_owner_id(conn_id)
    msg_from = message.from_user.id if message.from_user else 0
    text = message.text or ""

    logging.info(f"🟡 EDITED: chat={t} from={msg_from} text={text[:40]!r}")

    if conn_id:
        last_conn_by_chat[t] = conn_id

    if msg_from == owner_id and text.startswith("."):
        await handle_business_command(message, text)
        return

    if t in mutes and mutes[t] > datetime.now():
        if msg_from != owner_id:
            await delete_silent(t, message.message_id, conn_id)
        return


# ================== ЗАПУСК ==================
async def main():
    await init_db()
    me = await bot.get_me()
    bot.username = me.username
    logging.info(f"✅ Bot started: @{me.username} (id={me.id})")
    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(background_name_updater())
    await dp.start_polling(bot, drop_pending_updates=True,
        allowed_updates=["message", "callback_query", "business_connection",
                         "business_message", "edited_business_message", "deleted_business_messages"])


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
