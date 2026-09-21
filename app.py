import os
import logging
import threading
import asyncio
import random
from datetime import datetime, timedelta
from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = "8632065717:AAG5RRQJnVaDSGK7TfHtmuQ4IQT5elLE0w0"
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
dp = Dispatcher()

warns = {}
mutes = {}
clone = {}
stats = {}

async def check_subscription(user_id):
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status not in ("left", "kicked")
    except:
        return True

def subscribe_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться", url=CHANNEL_LINK)],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")],
    ])

async def get_owner_id(bcid):
    if not bcid:
        return OWNER_ID
    if bcid in business_owners:
        return business_owners[bcid]
    try:
        conn = await bot.get_business_connection(bcid)
        oid = conn.user.id
        business_owners[bcid] = oid
        return oid
    except:
        return OWNER_ID

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
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Команды", callback_data="cmd_list")],
        [InlineKeyboardButton(text="💎 Подписка", callback_data="sub_menu")],
        [InlineKeyboardButton(text="👥 Друг", callback_data="ref")],
        [InlineKeyboardButton(text="📚 Как подключить", callback_data="howto")],
    ])

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
    ])

def plans_kb(user_id=None):
    rows = []
    if user_id is not None and user_id not in used_trials:
        rows.append([InlineKeyboardButton(text=f"🎁 Пробный период ({TRIAL_DAYS} дней)", callback_data="trial")])
    for k, v in PRICES.items():
        rows.append([InlineKeyboardButton(text=f"{v['label']} — {v['rub']}₽", callback_data=f"pay_{k}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# Меню бота в ЛС самого бота
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    uid = message.from_user.id
    if not await check_subscription(uid):
        await message.answer("⚠️ Для использования бота подпишитесь на канал:", reply_markup=subscribe_kb())
        return
    try:
        await message.answer_photo(FSInputFile(BANNER_PATH), caption="🏠 Главное меню", reply_markup=main_menu())
    except:
        await message.answer("🏠 Главное меню", reply_markup=main_menu())

@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(call: types.CallbackQuery):
    if await check_subscription(call.from_user.id):
        try:
            await call.message.delete()
        except:
            pass
        await call.message.answer("🏠 Главное меню", reply_markup=main_menu())
    else:
        await call.answer("❌ Не подписан!", show_alert=True)

@dp.callback_query(F.data == "back_main")
async def cb_back(call: types.CallbackQuery):
    await call.message.edit_text("🏠 Главное меню", reply_markup=main_menu())

@dp.callback_query(F.data == "cmd_list")
async def cb_cmds(call: types.CallbackQuery):
    await call.message.answer(
        "📖 Команды:\n.mute N — Замутить собеседника\n.unmute — Снять мут\n.warn N — Выдать варн\n.unwarn — Снять варны\n.del — Удалить последнее сообщение собеседника\n.clear N — Очистить N сообщений\n.st текст\n.spam N текст\n.echo текст\n.say текст\n.roll N\n.flip\n.calc выражение\n.clone on/off\n.silent on/off\n.history N\n.stats\n.info",
        reply_markup=back_kb())

# --- Обработка команд и сообщений в Telegram Business ---

async def handle_business_logic(message: types.Message):
    t = message.chat.id
    reply = message.reply_to_message
    owner_id = await get_owner_id(message.business_connection_id)
    msg_from = message.from_user.id if message.from_user else 0

    # Если отправлена команда от владельца бизнес-аккаунта
    if message.text and message.text.startswith("."):
        parts = message.text.split()
        cmd = parts[0].lower()

        if cmd == ".mute":
            m = int(parts[1]) if len(parts) > 1 else 10
            mutes[t] = datetime.now() + timedelta(minutes=m)
            get_stats(t)["mutes"] += 1
            await try_delete(message)
            await message.answer(f"🔇 Собеседник замучен на {m} мин")
            return

        elif cmd == ".unmute":
            mutes.pop(t, None)
            await try_delete(message)
            await message.answer("🔊 Мут снят")
            return

        elif cmd == ".warn":
            n = int(parts[1]) if len(parts) > 1 else 1
            warns[t] = min(warns.get(t, 0) + n, WARN_LIMIT)
            get_stats(t)["warns"] += n
            await try_delete(message)
            await message.answer(f"⚠️ Предупреждений у собеседника: {warns[t]}/{WARN_LIMIT}")
            if warns[t] >= WARN_LIMIT:
                mutes[t] = datetime.now() + timedelta(minutes=WARN_MUTE_MINUTES)
                await message.answer(f"🔇 Достигнут лимит варнов! Мут на {WARN_MUTE_MINUTES} мин")
            return

        elif cmd == ".unwarn":
            warns.pop(t, None)
            mutes.pop(t, None)
            await try_delete(message)
            await message.answer("✅ Предупреждения и мут сброшены")
            return

        elif cmd == ".del":
            if reply:
                await try_delete(reply)
            else:
                if t in message_cache and message_cache[t]:
                    last_msg_id = list(message_cache[t].keys())[-1]
                    try:
                        await bot.delete_message(t, last_msg_id)
                    except:
                        pass
            await try_delete(message)
            return

        elif cmd == ".clear":
            n = int(parts[1]) if len(parts) > 1 else 5
            if t in message_cache:
                ids = sorted(message_cache[t].keys())[-n:]
                for mid in ids:
                    try:
                        await bot.delete_message(t, mid)
                    except:
                        pass
            await try_delete(message)
            return

        elif cmd == ".spam":
            p = message.text.split(maxsplit=2)
            if len(p) >= 3:
                try:
                    n = min(int(p[1]), 50)
                except:
                    n = 1
                await try_delete(message)
                for _ in range(n):
                    try:
                        await message.answer(p[2])
                        await asyncio.sleep(0.2)
                    except:
                        await asyncio.sleep(0.4)
            return

        elif cmd == ".st":
            text = message.text[3:].strip()
            if text:
                await try_delete(message)
                for word in text.split():
                    try:
                        await message.answer(word)
                        await asyncio.sleep(0.2)
                    except:
                        await asyncio.sleep(0.4)
            return

        elif cmd == ".echo" or cmd == ".say":
            text = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""
            await try_delete(message)
            if text:
                await message.answer(text)
            return

        elif cmd == ".roll":
            n = int(parts[1]) if len(parts) > 1 else 100
            await try_delete(message)
            await message.answer(f"🎲 {random.randint(1, n)}")
            return

        elif cmd == ".flip":
            await try_delete(message)
            await message.answer(random.choice(["🦅 Орёл", "🪙 Решка"]))
            return

        elif cmd == ".calc":
            expr = message.text[5:].strip()
            try:
                res = eval(expr, {"__builtins__": None}, {})
            except:
                res = "ошибка"
            await try_delete(message)
            await message.answer(f"🧮 {expr} = {res}")
            return

        elif cmd == ".clone":
            state = parts[1].lower() if len(parts) > 1 else "on"
            clone[t] = (state == "on")
            await try_delete(message)
            await message.answer(f"🔄 Автоповтор {'вкл' if state == 'on' else 'выкл'}")
            return

        elif cmd == ".silent":
            state = parts[1].lower() if len(parts) > 1 else "on"
            silent_mode[t] = (state == "on")
            await try_delete(message)
            if state == "off":
                await message.answer("🔊 Тихий режим выкл")
            return

        elif cmd == ".stats":
            s = get_stats(t)
            await try_delete(message)
            await message.answer(f"📊 Варнов: {warns.get(t, 0)}/{WARN_LIMIT}\nМут: {'да' if t in mutes else 'нет'}\nУдалено: {s['deleted']}")
            return

        elif cmd == ".info":
            await try_delete(message)
            await message.answer(f"🆔 Чат: {t}\nВладелец: {owner_id}\nВ кэше сообщений: {len(message_cache.get(t, {}))}")
            return

    # --- Кэширование и удаление при муте ---
    if t not in message_cache:
        message_cache[t] = {}
    message_cache[t][message.message_id] = {
        "text": message.text or "[медиа]",
        "time": message.date.strftime("%Y-%m-%d %H:%M:%S"),
        "sender": msg_from
    }

    if t in mutes:
        if mutes[t] > datetime.now():
            if msg_from != owner_id:
                try:
                    await message.delete()
                    get_stats(t)["deleted"] += 1
                except:
                    pass
                return
        else:
            mutes.pop(t, None)
            warns.pop(t, None)

    if clone.get(t) and message.text and msg_from != owner_id:
        await message.answer(message.text)


@dp.business_message()
async def on_business_message(message: types.Message):
    await handle_business_logic(message)

@dp.message()
async def on_regular_message(message: types.Message):
    if message.chat.type != "private":
        await handle_business_logic(message)

async def main():
    threading.Thread(target=run_flask, daemon=True).start()
    logging.info("Starting bot...")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
  
