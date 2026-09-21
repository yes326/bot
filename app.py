import os
import logging
import threading
import asyncio
import random
from datetime import datetime, timedelta
from flask import Flask
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor
from aiogram.types import InputFile

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8632065717:AAEw31UR7QX8H7I4hCL-ArPbHC5fpejxa_E"
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

business_owners = {}
subscriptions = {}
pending_payments = {}
used_trials = set()
message_cache = {}
silent_mode = {}

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot is running"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

warns = {}
mutes = {}
clone = {}
warn_messages = {}
stats = {}

async def check_subscription(user_id):
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status not in ("left", "kicked")
    except:
        return True

def subscribe_kb():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📢 Подписаться", url=CHANNEL_LINK)],
        [types.InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")],
    ])

async def get_owner_id(bcid):
    if not bcid:
        return None
    if bcid in business_owners:
        return business_owners[bcid]
    try:
        conn = await bot.get_business_connection(bcid)
        oid = conn.user.id
        business_owners[bcid] = oid
        return oid
    except:
        return None

async def is_owner(message):
    oid = await get_owner_id(message.business_connection_id)
    return oid is not None and message.from_user.id == oid

async def check_business_subscription(message):
    oid = await get_owner_id(message.business_connection_id)
    if oid is None:
        return False
    if not await check_subscription(oid):
        try:
            await message.answer(f"⚠️ Подпишись на канал:\n{CHANNEL_LINK}")
        except:
            pass
        return False
    return True

def get_stats(cid):
    if cid not in stats:
        stats[cid] = {"deleted": 0, "warns": 0, "mutes": 0}
    return stats[cid]

async def try_delete(message):
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except:
        pass

def main_menu():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📖 Команды", callback_data="cmd_list")],
        [types.InlineKeyboardButton(text="💎 Подписка", callback_data="sub_menu")],
        [types.InlineKeyboardButton(text="👥 Друг", callback_data="ref")],
        [types.InlineKeyboardButton(text="📚 Как подключить", callback_data="howto")],
    ])

def back_kb():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
    ])

def plans_kb(user_id=None):
    rows = []
    if user_id is not None and user_id not in used_trials:
        rows.append([types.InlineKeyboardButton(text=f"🎁 Пробный период ({TRIAL_DAYS} дней)", callback_data="trial")])
    for k, v in PRICES.items():
        rows.append([types.InlineKeyboardButton(text=f"{v['label']} — {v['rub']}₽", callback_data=f"pay_{k}")])
    rows.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)
    @dp.message_handler(commands=['start'])
async def start_cmd(message):
    uid = message.from_user.id
    if not await check_subscription(uid):
        await message.answer("⚠️ Подпишись на канал:", reply_markup=subscribe_kb())
        return
    try:
        await message.answer_photo(InputFile(BANNER_PATH), caption="🏠 Главное меню", reply_markup=main_menu())
    except:
        await message.answer("🏠 Главное меню", reply_markup=main_menu())

@dp.callback_query_handler(text="check_sub")
async def cb_check_sub(call):
    if await check_subscription(call.from_user.id):
        try:
            await call.message.delete()
        except:
            pass
        await call.message.answer("🏠 Главное меню", reply_markup=main_menu())
    else:
        await call.answer("❌ Не подписан!", show_alert=True)

@dp.callback_query_handler(text="back_main")
async def cb_back(call):
    await call.message.edit_text("🏠 Главное меню", reply_markup=main_menu())

@dp.callback_query_handler(text="cmd_list")
async def cb_cmds(call):
    await call.message.answer(
        "📖 Команды:\n.mute N\n.unmute\n.warn N\n.unwarn\n.kick\n.del\n.clear N\n.st текст\n.spam N текст\n.echo текст\n.say текст\n.roll N\n.flip\n.calc выражение\n.clone on/off\n.silent on/off\n.history N\n.stats\n.info",
        reply_markup=back_kb())

@dp.callback_query_handler(text="sub_menu")
async def cb_sub(call):
    uid = call.from_user.id
    now = datetime.now()
    current = subscriptions.get(uid)
    status = "не активна"
    if current and current > now:
        days_left = (current - now).days
        status = f"активна до {current.strftime('%d.%m.%Y')} ({days_left} дн.)"
    trial_text = ""
    if uid not in used_trials:
        trial_text = f"🎁 Пробный период — {TRIAL_DAYS} дней\n\n"
    await call.message.answer(f"💎 Подписка\n\n📌 Статус: {status}\n\n{trial_text}Выбери 👇", reply_markup=plans_kb(uid))

@dp.callback_query_handler(text="trial")
async def cb_trial(call):
    uid = call.from_user.id
    now = datetime.now()
    if uid in used_trials:
        await call.answer("Уже использовал!", show_alert=True)
        return
    current = subscriptions.get(uid)
    if current and current > now:
        await call.answer("Уже есть подписка!", show_alert=True)
        return
    used_trials.add(uid)
    until = now + timedelta(days=TRIAL_DAYS)
    subscriptions[uid] = until
    await call.message.answer(f"🎁 Пробный до {until.strftime('%d.%m.%Y %H:%M')}")

@dp.callback_query_handler(text_startswith="pay_")
async def cb_pay(call):
    plan = call.data.split("_")[1]
    p = PRICES[plan]
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{plan}")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="sub_menu")],
    ])
    await call.message.answer(f"💳 {p['label']} — {p['rub']}₽\nКарта: {CARD_NUMBER}\n\nНажми «Я оплатил» и пришли скриншот.", reply_markup=kb)

@dp.callback_query_handler(text_startswith="paid_")
async def cb_paid(call):
    plan = call.data.split("_")[1]
    pending_payments[call.from_user.id] = {"plan": plan}
    await call.message.answer("📸 Пришли скриншот.")

@dp.message_handler(content_types=['photo'])
async def on_screenshot(message):
    uid = message.from_user.id
    if uid not in pending_payments:
        return
    plan = pending_payments[uid].get("plan", "1month")
    user = message.from_user
    owner_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ Да", callback_data=f"approve_{user.id}_{plan}")],
        [types.InlineKeyboardButton(text="❌ Нет", callback_data=f"reject_{user.id}")],
    ])
    try:
        await bot.send_photo(OWNER_ID, message.photo[-1].file_id, caption=f"💰 Оплата от @{user.username}\nПлан: {PRICES[plan]['label']}", reply_markup=owner_kb)
        await message.answer("✅ Отправлено! Жди подтверждения.")
        pending_payments.pop(uid, None)
    except:
        await message.answer("⚠️ Ошибка.")

@dp.callback_query_handler(text_startswith="approve_")
async def cb_approve(call):
    if call.from_user.id != OWNER_ID:
        await call.answer("Только владелец!")
        return
    parts = call.data.split("_")
    uid = int(parts[1])
    plan = parts[2]
    days = PRICES[plan]["days"]
    now = datetime.now()
    current = subscriptions.get(uid)
    new_until = (current + timedelta(days=days)) if (current and current > now) else (now + timedelta(days=days))
    subscriptions[uid] = new_until
    try:
        await bot.send_message(uid, f"✅ Оплата подтверждена до {new_until.strftime('%d.%m.%Y %H:%M')}")
    except:
        pass
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("OK")

@dp.callback_query_handler(text_startswith="reject_")
async def cb_reject(call):
    if call.from_user.id != OWNER_ID:
        await call.answer("Только владелец!")
        return
    uid = int(call.data.split("_")[1])
    try:
        await bot.send_message(uid, "❌ Оплата отклонена.")
    except:
        pass
    await call.message.edit_reply_markup(reply_markup=None)

@dp.callback_query_handler(text="ref")
async def cb_ref(call):
    uname = bot.username or "my_bot"
    await call.message.answer(f"👥 Ссылка:\nhttps://t.me/{uname}?start=ref_{call.from_user.id}", reply_markup=back_kb())

@dp.callback_query_handler(text="howto")
async def cb_howto(call):
    await call.message.answer("📚 Настройки → Аккаунт → Автоматизация чатов", reply_markup=back_kb())
