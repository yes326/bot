# -*- coding: utf-8 -*-
"""
AntiSpam Defender Bot — Business-бот с удалением и мут-системой.
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice, Message, PreCheckoutQuery,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from dotenv import load_dotenv

# ============================================================
# КОНФИГ
# ============================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

CHANNEL_ID = -1004412177691
CHANNEL_LINK = "https://t.me/+MV9rTn9A6L1hNGNi"
CARD_NUMBER = "2204320449407461"
SUPPORT_USERNAME = "ysorn"

PERMANENT_USERNAMES = {"ysorn", "null_aspect"}

TARIFFS = {
    "1m": (30,  100,  50),
    "6m": (180, 599,  250),
    "1y": (365, 1199, 550),
}

FREE_TRIAL_DAYS = 7
REFERRAL_TARGET = 5
REFERRAL_REWARD_DAYS = 7

DB_PATH = "bot.db"

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000") + WEBHOOK_PATH
PORT = int(os.getenv("PORT", 8000))

MAX_DELETE_PER_CALL = 100
SPAM_DELAY = 0.15   # секунд между сообщениями в .spam и .st

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("bot")


# ============================================================
# БАЗА ДАННЫХ
# ============================================================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                sub_until TEXT,
                is_permanent INTEGER DEFAULT 0,
                trial_used INTEGER DEFAULT 0,
                referrer_id INTEGER,
                ref_count INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                tariff TEXT,
                method TEXT,
                amount INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS warns (
                chat_id INTEGER,
                target_user_id INTEGER,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (chat_id, target_user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mutes (
                chat_id INTEGER,
                target_user_id INTEGER,
                until TEXT,
                PRIMARY KEY (chat_id, target_user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS clones (
                chat_id INTEGER PRIMARY KEY,
                is_on INTEGER DEFAULT 0
            )
        """)
        await db.commit()


async def get_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        return await cur.fetchone()


async def create_user(user_id, username, referrer_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, referrer_id) VALUES (?,?,?)",
            (user_id, username, referrer_id),
        )
        await db.commit()
    if referrer_id and referrer_id != user_id:
        await add_referral(referrer_id)


async def add_referral(referrer_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET ref_count = ref_count + 1 WHERE user_id=?",
            (referrer_id,),
        )
        await db.commit()
    u = await get_user(referrer_id)
    if u and u["ref_count"] and u["ref_count"] % REFERRAL_TARGET == 0:
        await extend_subscription(referrer_id, REFERRAL_REWARD_DAYS)
        return True
    return False


async def activate_trial(user_id):
    until = (datetime.utcnow() + timedelta(days=FREE_TRIAL_DAYS)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET sub_until=?, trial_used=1 WHERE user_id=?",
            (until, user_id),
        )
        await db.commit()


async def extend_subscription(user_id, days):
    u = await get_user(user_id)
    now = datetime.utcnow()
    if u and u["sub_until"]:
        base = max(datetime.fromisoformat(u["sub_until"]), now)
    else:
        base = now
    until = (base + timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET sub_until=? WHERE user_id=?", (until, user_id))
        await db.commit()


async def set_permanent(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_permanent=1 WHERE user_id=?", (user_id,))
        await db.commit()


async def has_access(user_id):
    u = await get_user(user_id)
    if not u:
        return False
    if u["is_permanent"]:
        return True
    if not u["sub_until"]:
        return False
    return datetime.fromisoformat(u["sub_until"]) > datetime.utcnow()


async def days_left(user_id):
    u = await get_user(user_id)
    if not u or not u["sub_until"]:
        return 0
    d = datetime.fromisoformat(u["sub_until"]) - datetime.utcnow()
    return max(0, d.days)


async def add_payment(user_id, tariff, method, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO payments (user_id, tariff, method, amount, created_at) VALUES (?,?,?,?,?)",
            (user_id, tariff, method, amount, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cur.lastrowid


async def confirm_payment(pid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM payments WHERE id=?", (pid,))
        p = await cur.fetchone()
        if not p:
            return None
        await db.execute("UPDATE payments SET status='confirmed' WHERE id=?", (pid,))
        await db.commit()
    await extend_subscription(p["user_id"], TARIFFS[p["tariff"]][0])
    return p


# ---------- Warn ----------
async def add_warns(chat_id, target_user_id, n):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO warns (chat_id, target_user_id, count) VALUES (?,?,?) "
            "ON CONFLICT(chat_id, target_user_id) DO UPDATE SET count = count + ?",
            (chat_id, target_user_id, n, n),
        )
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT count FROM warns WHERE chat_id=? AND target_user_id=?",
            (chat_id, target_user_id),
        )
        row = await cur.fetchone()
        return row["count"] if row else n


async def reset_warns(chat_id, target_user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE warns SET count=0 WHERE chat_id=? AND target_user_id=?",
            (chat_id, target_user_id),
        )
        await db.commit()


# ---------- Mute ----------
async def set_mute(chat_id, target_user_id, minutes):
    until = (datetime.utcnow() + timedelta(minutes=minutes)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO mutes (chat_id, target_user_id, until) VALUES (?,?,?) "
            "ON CONFLICT(chat_id, target_user_id) DO UPDATE SET until=?",
            (chat_id, target_user_id, until, until),
        )
        await db.commit()
    return until


async def clear_mute(chat_id, target_user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM mutes WHERE chat_id=? AND target_user_id=?",
            (chat_id, target_user_id),
        )
        await db.commit()


async def is_muted(chat_id, target_user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT until FROM mutes WHERE chat_id=? AND target_user_id=?",
            (chat_id, target_user_id),
        )
        row = await cur.fetchone()
        if not row:
            return False
        return datetime.fromisoformat(row["until"]) > datetime.utcnow()


# ---------- Clone ----------
async def set_clone(chat_id, on):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO clones (chat_id, is_on) VALUES (?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET is_on=?",
            (chat_id, 1 if on else 0, 1 if on else 0),
        )
        await db.commit()


async def is_clone_on(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT is_on FROM clones WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return bool(row and row["is_on"])


# ============================================================
# ПРОВЕРКА ПОДПИСКИ
# ============================================================
async def is_subscribed(bot, user_id):
    try:
        m = await bot.get_chat_member(CHANNEL_ID, user_id)
        return m.status in ("member", "administrator", "creator")
    except Exception as e:
        log.warning(f"sub check failed: {e}")
        return False


# ============================================================
# ТЕКСТЫ
# ============================================================
SUB_REQUIRED_TEXT = (
    "👋 <b>Привет!</b>\n\n"
    "Чтобы пользоваться ботом, подпишись на наш канал:\n"
    f"👉 {CHANNEL_LINK}\n\n"
    "После подписки нажми <b>«Проверить подписку»</b>."
)

MAIN_MENU_TEXT = (
    "🎛 <b>Главное меню</b>\n\n"
    "Привет, <b>{name}</b>!\n\n"
    "📌 <b>Инструкция по подключению:</b>\n"
    "Настройки → Аккаунт → Автоматизация чатов → Подключаем бота\n\n"
    "После подключения придёт сообщение: <b>«бот подключен»</b>.\n\n"
    "Выбери действие ниже 👇"
)

PROFILE_TEXT = (
    "👤 <b>Профиль</b>\n\n"
    "Имя: <b>{name}</b>\n"
    "Подписка: {status}\n"
    "👥 Приглашено: <b>{refs}</b> / {target}\n\n"
    f"За каждые {REFERRAL_TARGET} приглашённых — <b>+{REFERRAL_REWARD_DAYS} дней</b>!"
)

COMMANDS_TEXT = (
    "📖 <b>Команды бота</b>\n\n"
    "<code>.spam N текст</code> — отправить N раз (без лимита)\n"
    "<code>.warn N</code> — выдать N предупреждений собеседнику\n"
    "<code>.mute N</code> — замутить собеседника на N минут\n"
    "<code>.unwarn</code> — снять предупреждения\n"
    "<code>.unmute</code> — снять мут\n"
    "<code>.st текст</code> — каждое слово отдельным сообщением\n"
    "<code>.clone on/off</code> — автоповтор собеседника\n"
    "<code>.help</code> — этот список"
)

TARIFFS_TEXT = "💎 <b>Выбери тариф:</b>"


# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def sub_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться", url=CHANNEL_LINK)],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")],
    ])


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Купить подписку", callback_data="buy")],
        [InlineKeyboardButton(text="👥 Реферальная система", callback_data="ref")],
        [InlineKeyboardButton(text="📖 Команды", callback_data="cmds")],
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")],
    ])


def tariffs_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 месяц — 100₽ / 50⭐", callback_data="tariff_1m")],
        [InlineKeyboardButton(text="6 месяцев — 599₽ / 250⭐", callback_data="tariff_6m")],
        [InlineKeyboardButton(text="1 год — 1199₽ / 550⭐", callback_data="tariff_1y")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")],
    ])


def pay_method_menu(tariff):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Оплатить звёздами", callback_data=f"stars_{tariff}")],
        [InlineKeyboardButton(text="💳 Оплатить картой", callback_data=f"card_{tariff}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy")],
    ])


def back_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="back_menu")],
    ])


# ============================================================
# РОУТЕР
# ============================================================
router = Router()


# ---------- Обработка всех бизнес-сообщений ----------
@router.business_message()
async def handle_business_message(msg: Message, bot: Bot):
    if not msg.business_connection_id:
        return

    chat_id = msg.chat.id
    sender_id = msg.from_user.id if msg.from_user else None
    text = msg.text or ""

    # 1. Замученный собеседник — удаляем его сообщение
    if sender_id and await is_muted(chat_id, sender_id):
        try:
            await bot.delete_business_messages(
                business_connection_id=msg.business_connection_id,
                message_ids=[msg.message_id],
            )
        except Exception as e:
            log.warning(f"failed to delete muted msg: {e}")
        return

    # 2. Клон — повторяем за собеседником
    if sender_id and text and await is_clone_on(chat_id):
        if not text.startswith("."):
            try:
                await bot.send_message(chat_id, text)
            except Exception as e:
                log.warning(f"clone failed: {e}")


# ---------- Команды в бизнес-чате ----------
@router.business_message(F.text.startswith("."))
async def business_commands(msg: Message, bot: Bot):
    if not await has_access(msg.from_user.id):
        await msg.answer("❌ Подписка неактивна. Купи подписку в меню.")
        return

    text = msg.text.strip()
    chat_id = msg.chat.id

    # .help
    if text == ".help":
        await msg.answer(COMMANDS_TEXT, parse_mode="HTML")
        return

    # .spam N текст — задержка 0.15 сек
    m = re.match(r"^\.spam\s+(\d+)\s+(.+)", text, re.DOTALL)
    if m:
        n = int(m.group(1))
        body = m.group(2)
        for _ in range(n):
            try:
                await bot.send_message(chat_id, body)
            except Exception as e:
                log.warning(f"spam error: {e}")
                break
            await asyncio.sleep(SPAM_DELAY)
        return

    # .st текст — задержка 0.15 сек
    m = re.match(r"^\.st\s+(.+)", text, re.DOTALL)
    if m:
        for w in m.group(1).split():
            await bot.send_message(chat_id, w)
            await asyncio.sleep(SPAM_DELAY)
        return

    # .warn N
    m = re.match(r"^\.warn\s+(\d+)", text)
    if m:
        n = int(m.group(1))
        total = await add_warns(chat_id, chat_id, n)
        try:
            await bot.send_message(chat_id, f"⚠️ Тебе выдано предупреждение ({n}). Всего: {total}.")
        except Exception:
            pass
        await msg.answer(f"✅ Выдано {n} предупреждений. Всего: {total}.")
        return

    # .unwarn
    if text == ".unwarn":
        await reset_warns(chat_id, chat_id)
        try:
            await bot.send_message(chat_id, "✅ Предупреждения сняты.")
        except Exception:
            pass
        return

    # .mute N (минуты)
    m = re.match(r"^\.mute\s+(\d+)", text)
    if m:
        n = int(m.group(1))
        if n <= 0:
            await clear_mute(chat_id, chat_id)
            await msg.answer("🔊 Мут снят.")
            return
        await set_mute(chat_id, chat_id, n)
        try:
            await bot.send_message(chat_id, f"🔇 Ты замучен на {n} мин.")
        except Exception:
            pass
        await msg.answer(f"✅ Мут на {n} мин.")
        return

    # .unmute
    if text == ".unmute":
        await clear_mute(chat_id, chat_id)
        try:
            await bot.send_message(chat_id, "🔊 Мут снят.")
        except Exception:
            pass
        return

    # .clone on/off
    m = re.match(r"^\.clone\s+(on|off)", text)
    if m:
        on = m.group(1) == "on"
        await set_clone(chat_id, on)
        await msg.answer(f"👥 Автоповтор: <b>{'включён' if on else 'выключен'}</b>", parse_mode="HTML")
        return

    await msg.answer("❓ Неизвестная команда. Напиши .help")


# ---------- Меню и /start ----------
async def send_main_menu(msg: Message):
    u = await get_user(msg.from_user.id)
    if u and not u["trial_used"]:
        await activate_trial(msg.from_user.id)
    await msg.answer(
        MAIN_MENU_TEXT.format(name=msg.from_user.full_name),
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


@router.message(CommandStart())
async def cmd_start(msg: Message, bot: Bot):
    args = msg.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1][4:])
        except ValueError:
            pass

    await create_user(msg.from_user.id, msg.from_user.username or "", referrer_id)

    if msg.from_user.username in PERMANENT_USERNAMES:
        await set_permanent(msg.from_user.id)

    if not await is_subscribed(bot, msg.from_user.id):
        await msg.answer(SUB_REQUIRED_TEXT, reply_markup=sub_keyboard())
        return

    await send_main_menu(msg)


@router.callback_query(F.data == "check_sub")
async def check_sub(cb: CallbackQuery, bot: Bot):
    if await is_subscribed(bot, cb.from_user.id):
        await cb.message.delete()
        await send_main_menu(cb.message)
    else:
        await cb.answer("❌ Ты ещё не подписался!", show_alert=True)


@router.callback_query(F.data == "back_menu")
async def back_menu_cb(cb: CallbackQuery):
    await cb.message.edit_text(
        MAIN_MENU_TEXT.format(name=cb.from_user.full_name),
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "profile")
async def profile(cb: CallbackQuery):
    u = await get_user(cb.from_user.id)
    if u["is_permanent"]:
        status = "♾ Вечная подписка"
    elif u["sub_until"] and await has_access(cb.from_user.id):
        status = f"✅ Активна ({await days_left(cb.from_user.id)} дн.)"
    else:
        status = "❌ Неактивна"
    await cb.message.edit_text(
        PROFILE_TEXT.format(
            name=cb.from_user.full_name,
            status=status,
            refs=u["ref_count"] or 0,
            target=REFERRAL_TARGET,
        ),
        reply_markup=back_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cmds")
async def cmds_cb(cb: CallbackQuery):
    await cb.message.edit_text(COMMANDS_TEXT, parse_mode="HTML", reply_markup=back_menu())


# ---------- Оплата ----------
@router.callback_query(F.data == "buy")
async def buy_menu(cb: CallbackQuery):
    await cb.message.edit_text(TARIFFS_TEXT, reply_markup=tariffs_menu(), parse_mode="HTML")


@router.callback_query(F.data.startswith("tariff_"))
async def choose_tariff(cb: CallbackQuery):
    t = cb.data.split("_")[1]
    days, rub, stars = TARIFFS[t]
    text = (
        f"💎 <b>Тариф</b>\n\n"
        f"Срок: <b>{days} дней</b>\n"
        f"Цена: <b>{rub}₽</b> или <b>{stars}⭐</b>\n\n"
        "Выбери способ оплаты:"
    
    await cb.message.edit_text(text, reply_markup=pay_method_menu(t), parse_mode="HTML")
