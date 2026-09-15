import os
import logging
import threading
from datetime import datetime, timedelta
from flask import Flask
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor
from aiogram.types import LabeledPrice

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8632065717:AAEYC3ciYv-W7PHzMrWFaX7FyRYNlZJ5_rE")
CARD_NUMBER = "2204320449407461"
OWNER_USERNAME = "ysorn"
OWNER_USER_ID = 8502858396

PRICES = {
    "1month": {"rub": 100, "stars": 50, "days": 30, "label": "1 месяц"},
    "6months": {"rub": 599, "stars": 250, "days": 180, "label": "6 месяцев"},
    "1year": {"rub": 1199, "stars": 550, "days": 365, "label": "1 год"},
}
WARN_LIMIT = 5
WARN_MUTE_MINUTES = 5

# ================== FLASK (для Render) ==================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot is running"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)

# ================== ИНИЦИАЛИЗАЦИЯ ==================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

warns = {}
mutes = {}
clone = {}

# ================== КЛАВИАТУРЫ ==================
def main_menu():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("📖 Команды бота", callback_data="cmd_list"),
        types.InlineKeyboardButton("💎 Подписка", callback_data="sub_menu"),
        types.InlineKeyboardButton("👥 Пригласить друга", callback_data="ref"),
        types.InlineKeyboardButton("📚 Как подключить", callback_data="howto"),
    )
    return kb

def back_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 В меню", callback_data="back_main"))
    return kb

# ================== /START ==================
@dp.message_handler(commands=['start'])
async def start_cmd(message: types.Message):
    await message.answer(
        "🏠 *Главное меню*\n\nВыбери 👇",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

@dp.callback_query_handler(lambda c: c.data == "back_main")
async def cb_back(call: types.CallbackQuery):
    await call.message.edit_text("🏠 *Главное меню*\n\nВыбери 👇", parse_mode="Markdown", reply_markup=main_menu())

@dp.callback_query_handler(lambda c: c.data == "cmd_list")
async def cb_cmds(call: types.CallbackQuery):
    text = (
        "📖 *Команды:*\n\n"
        "`.mute N` — замутить на N минут\n"
        "`.unmute` — снять мут\n"
        "`.warn N` — предупреждения\n"
        "`.unwarn` — сбросить\n"
        "`.spam N текст` — отправить N раз\n"
        "`.st текст` — по словам\n"
        "`.clone on/off` — автоповтор"
    )
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=back_kb())

@dp.callback_query_handler(lambda c: c.data == "sub_menu")
async def cb_sub(call: types.CallbackQuery):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for k, v in PRICES.items():
        kb.add(types.InlineKeyboardButton(
            f"{v['label']} — {v['rub']}₽ / {v['stars']}⭐",
            callback_data=f"pay_{k}"
        ))
    kb.add(types.InlineKeyboardButton("🔙 В меню", callback_data="back_main"))
    await call.message.edit_text("💎 *Подписка*\n\n🎁 Пробный период 7 дней!\nВыбери тариф 👇", parse_mode="Markdown", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("pay_"))
async def cb_pay(call: types.CallbackQuery):
    plan = call.data.split("_")[1]
    p = PRICES[plan]
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("⭐ Оплатить звёздами", callback_data=f"stars_{plan}"),
        types.InlineKeyboardButton("💳 Карта (рубли)", callback_data=f"card_{plan}"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="sub_menu"),
    )
    await call.message.edit_text(
        f"💳 *Оплата «{p['label']}»*\n\n💰 {p['rub']}₽ или {p['stars']}⭐",
        parse_mode="Markdown", reply_markup=kb
    )

@dp.callback_query_handler(lambda c: c.data.startswith("card_"))
async def cb_card(call: types.CallbackQuery):
    plan = call.data.split("_")[1]
    p = PRICES[plan]
    await call.message.answer(
        f"💳 *Оплата картой*\n\n💵 Сумма: *{p['rub']}₽*\n💳 Карта: `{CARD_NUMBER}`\n\n📸 Пришли скриншот после перевода.",
        parse_mode="Markdown"
    )
    try:
        await bot.send_message(f"@{OWNER_USERNAME}", f"💰 Оплата (карта)\nОт: @{call.from_user.username}\nТариф: {p['label']}")
    except:
        pass

@dp.callback_query_handler(lambda c: c.data.startswith("stars_"))
async def cb_stars(call: types.CallbackQuery):
    plan = call.data.split("_")[1]
    p = PRICES[plan]
    try:
        await bot.send_invoice(
            chat_id=call.from_user.id,
            title=f"Подписка {p['label']}",
            description=f"AntiSpam Defender — {p['label']}",
            payload=f"sub_{plan}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=p["label"], amount=p["stars"])],
        )
    except Exception as e:
        logging.error(f"invoice error: {e}")
        await call.message.answer(f"⭐ Отправьте {p['stars']}⭐ на @{OWNER_USERNAME}")
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "ref")
async def cb_ref(call: types.CallbackQuery):
    uname = (await bot.get_me()).username
    link = f"https://t.me/{uname}?start=ref_{call.from_user.id}"
    await call.message.edit_text(f"👥 *Рефералка*\n\n🔗 Твоя ссылка:\n`{link}`", parse_mode="Markdown", reply_markup=back_kb())

@dp.callback_query_handler(lambda c: c.data == "howto")
async def cb_howto(call: types.CallbackQuery):
    await call.message.edit_text(
        "📚 *Как подключить*\n\n1. Настройки\n2. Аккаунт\n3. Автоматизация чатов\n4. Подключить бота",
        parse_mode="Markdown", reply_markup=back_kb()
    )

# ================== BUSINESS-КОМАНДЫ ==================
# В aiogram 2.x нет business_message — обёрнем обычные сообщения из бизнес-чатов
@dp.message_handler(lambda m: m.text and m.text.startswith(".mute"))
async def b_mute(message: types.Message):
    parts = message.text.split()
    m = int(parts[1]) if len(parts) > 1 else 10
    mutes[message.chat.id] = datetime.now() + timedelta(minutes=m)
    await message.answer(f"🔇 Замучен на {m} мин.")

@dp.message_handler(lambda m: m.text and m.text.startswith(".unmute"))
async def b_unmute(message: types.Message):
    mutes.pop(message.chat.id, None)
    await message.answer("🔊 Мут снят.")

@dp.message_handler(lambda m: m.text and m.text.startswith(".warn"))
async def b_warn(message: types.Message):
    parts = message.text.split()
    n = int(parts[1]) if len(parts) > 1 else 1
    t = message.chat.id
    warns[t] = min(warns.get(t, 0) + n, WARN_LIMIT)
    await message.answer(f"⚠️ Предупреждений: {warns[t]}/{WARN_LIMIT}")
    if warns[t] >= WARN_LIMIT:
        mutes[t] = datetime.now() + timedelta(minutes=WARN_MUTE_MINUTES)
        await message.answer(f"🔇 Достигнут лимит! Мут на {WARN_MUTE_MINUTES} мин.")

@dp.message_handler(lambda m: m.text and m.text.startswith(".unwarn"))
async def b_unwarn(message: types.Message):
    warns.pop(message.chat.id, None)
    mutes.pop(message.chat.id, None)
    await message.answer("✅ Сброшено.")

@dp.message_handler(lambda m: m.text and m.text.startswith(".help"))
async def b_help(message: types.Message):
    await message.answer(
        "📋 Команды:\n.mute N\n.unmute\n.warn N\n.unwarn\n.spam N текст\n.st текст\n.clone on/off"
    )

@dp.message_handler(lambda m: m.text and m.text.startswith(".spam"))
async def b_spam(message: types.Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование: `.spam N текст`")
        return
    try:
        n = min(int(parts[1]), 50)
    except:
        n = 1
    for _ in range(n):
        await message.answer(parts[2])

@dp.message_handler(lambda m: m.text and m.text.startswith(".clone"))
async def b_clone(message: types.Message):
    parts = message.text.split()
    state = parts[1].lower() if len(parts) > 1 else "on"
    clone[message.chat.id] = (state == "on")
    await message.answer(f"🔄 Автоповтор {'включён' if state == 'on' else 'выключен'}")

@dp.message_handler(lambda m: m.text and m.text.startswith(".st"))
async def b_st(message: types.Message):
    text = message.text.replace(".st", "", 1).strip()
    if text:
        for word in text.split():
            await message.answer(word)

# ================== ОБРАБОТКА СООБЩЕНИЙ ==================
@dp.message_handler(content_types=types.ContentTypes.TEXT)
async def on_msg(message: types.Message):
    t = message.chat.id
    # Мут — просто игнорируем сообщения (в aiogram 2.x нет business API для удаления)
    if t in mutes and mutes[t] > datetime.now():
        return
    if t in mutes and mutes[t] <= datetime.now():
        mutes.pop(t, None)
        warns.pop(t, None)
    # Автоповтор
    if clone.get(t) and message.text:
        await message.answer(message.text)

# ================== ЗАПУСК ==================
async def on_startup(dp):
    me = await bot.get_me()
    print(f"✅ Бот запущен: @{me.username}")

if __name__ == "__main__":
    # Flask в фоне (для Render)
    threading.Thread(target=run_flask, daemon=True).start()
    # Polling
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
