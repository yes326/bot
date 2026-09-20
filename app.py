import os
import logging
import threading
import asyncio
import random
from datetime import datetime, timedelta
from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import DeleteBusinessMessages, EditMessageText

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8632065717:AAEYC3ciYv-W7PHzMrWFaX7FyRYNlZJ5_rE")
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
dp = Dispatcher(storage=MemoryStorage())

warns = {}
mutes = {}
clone = {}
warn_messages = {}
stats = {}
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
    except:
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
                f"⚠️ *Для использования бота подпишись на канал:*\n{CHANNEL_LINK}",
                parse_mode="Markdown"
            )
        except:
            pass
        return False
    return True

def get_stats(chat_id):
    if chat_id not in stats:
        stats[chat_id] = {"deleted": 0, "warns": 0, "mutes": 0}
    return stats[chat_id]

async def try_delete(message: types.Message):
    try:
        await bot(DeleteBusinessMessages(
            business_connection_id=message.business_connection_id,
            message_ids=[message.message_id],
        ))
    except:
        pass

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
    @dp.message(F.text == "/start")
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.answer(
            "⚠️ *Для использования бота нужно подписаться на наш канал.*\n\n"
            "📢 Подпишись и нажми «✅ Я подписался».",
            parse_mode="Markdown",
            reply_markup=subscribe_kb()
        )
        return
    try:
        await message.answer_photo(
            photo=types.FSInputFile(BANNER_PATH),
            caption="🏠 *Главное меню*\n\nВыбери, что тебя интересует 👇",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
    except Exception as e:
        logging.error(f"Баннер: {e}")
        await message.answer("🏠 *Главное меню*\n\nВыбери 👇", parse_mode="Markdown", reply_markup=main_menu())

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
                caption="🏠 *Главное меню*\n\nВыбери 👇",
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
        except:
            await call.message.answer("🏠 *Главное меню*\n\nВыбери 👇", parse_mode="Markdown", reply_markup=main_menu())
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
            caption="🏠 *Главное меню*\n\nВыбери 👇",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
    except:
        await call.message.answer("🏠 *Главное меню*\n\nВыбери 👇", parse_mode="Markdown", reply_markup=main_menu())

@dp.callback_query(F.data == "cmd_list")
async def cb_cmds(call: types.CallbackQuery):
    await call.message.answer(
        "📖 *Команды:*\n\n"
        "*Модерация:*\n"
        "`.mute N`\n`.unmute`\n`.warn N`\n`.unwarn`\n`.kick`\n`.del`\n`.clear N`\n`.pin`\n\n"
        "*Развлечения:*\n"
        "`.st текст`\n`.spam N текст`\n`.echo текст`\n`.say текст`\n`.roll N`\n`.flip`\n`.calc выражение`\n`.tag`\n\n"
        "*Настройки:*\n"
        "`.clone on/off`\n`.silent on/off`\n`.history N`\n`.stats`\n`.info`",
        parse_mode="Markdown", reply_markup=back_kb())

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
        f"💎 *Подписка AntiSpam Defender*\n\n"
        f"📌 Статус: *{status}*\n\n"
        f"{trial_text}"
        f"Выбери действие 👇",
        parse_mode="Markdown",
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
        f"🎁 *Пробный период активирован!*\n\n"
        f"💎 Тебе доступно *{TRIAL_DAYS} дней* бесплатно.\n"
        f"📅 Действует до: *{until.strftime('%d.%m.%Y %H:%M')}*",
        parse_mode="Markdown"
    )
    await call.answer("Пробный период активирован ✅")

@dp.callback_query(F.data.startswith("pay_"))
async def cb_pay(call: types.CallbackQuery):
    plan = call.data.split("_")[1]
    p = PRICES[plan]
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{plan}")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="sub_menu")],
    ])
    await call.message.answer(
        f"💳 *Оплата «{p['label']}»*\n\n"
        f"💰 Сумма: *{p['rub']}₽*\n"
        f"💳 Карта: `{CARD_NUMBER}`\n\n"
        f"📸 После перевода нажми «Я оплатил» и пришли скриншот.",
        parse_mode="Markdown", reply_markup=kb)

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
                f"💰 *Новая оплата*\n\n"
                f"👤 Покупатель: @{user.username or user.first_name} (ID: `{user.id}`)\n"
                f"📦 Тариф: *{PRICES[plan]['label']}* — {PRICES[plan]['rub']}₽"
            ),
            parse_mode="Markdown",
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
        await call.answer("Только владелец может подтверждать!", show_alert=True)
        return
    parts = call.data.split("_")
    user_id = int(parts[1])
    plan = parts[2]
    days = PRICES[plan]["days"]
    now = datetime.now()
    current = subscriptions.get(user_id)
    new_until = (current + timedelta(days=days)) if (current and current > now) else (now + timedelta(days=days))
    subscriptions[user_id] = new_until
    try:
        await bot.send_message(
            user_id,
            f"✅ *Оплата подтверждена!*\n\n"
            f"💎 Подписка «{PRICES[plan]['label']}» активирована.\n"
            f"📅 Действует до: *{new_until.strftime('%d.%m.%Y %H:%M')}*",
            parse_mode="Markdown"
        )
    except:
        pass
    try:
        await call.message.edit_caption(caption="✅ Оплата подтверждена")
    except:
        pass
    await call.answer("Подписка активирована ✅")

@dp.callback_query(F.data.startswith("reject_"))
async def cb_reject(call: types.CallbackQuery):
    if call.from_user.id != OWNER_ID:
        await call.answer("Только владелец!", show_alert=True)
        return
    user_id = int(call.data.split("_")[1])
    try:
        await bot.send_message(user_id, "❌ Оплата отклонена. Свяжитесь с @ysorn.")
    except:
        pass
    try:
        await call.message.edit_caption(caption="❌ Оплата отклонена")
    except:
        pass
    await call.answer("Отклонено")

@dp.callback_query(F.data == "ref")
async def cb_ref(call: types.CallbackQuery):
    uname = bot.username or "my_bot"
    link = f"https://t.me/{uname}?start=ref_{call.from_user.id}"
    await call.message.answer(f"👥 *Рефералка*\n🔗 `{link}`", parse_mode="Markdown", reply_markup=back_kb())

@dp.callback_query(F.data == "howto")
async def cb_howto(call: types.CallbackQuery):
    await call.message.answer("📚 Настройки → Аккаунт → Автоматизация чатов → Подключить бота", reply_markup=back_kb())

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
            f"📩 *Сообщение от пользователя*\n\n"
            f"👤 От: @{user.username or user.first_name} (ID: `{user.id}`)\n"
            f"📝 Текст: `{text[:500]}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Не смог переслать ЛС: {e}")
