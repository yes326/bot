import os
import logging
import threading
import asyncio
from datetime import datetime, timedelta
from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import DeleteBusinessMessages
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
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

# ================== ИНИЦИАЛИЗАЦИЯ ==================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

warns = {}
mutes = {}
clone = {}

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

# ================== МЕНЮ ==================
@dp.message(F.text == "/start")
async def start_cmd(message: types.Message):
    await message.answer("🏠 *Главное меню*\n\nВыбери 👇", parse_mode="Markdown", reply_markup=main_menu())

@dp.callback_query(F.data == "back_main")
async def cb_back(call: types.CallbackQuery):
    await call.message.edit_text("🏠 *Главное меню*\n\nВыбери 👇", parse_mode="Markdown", reply_markup=main_menu())

@dp.callback_query(F.data == "cmd_list")
async def cb_cmds(call: types.CallbackQuery):
    await call.message.edit_text(
        "📖 *Команды:*\n\n"
        "`.mute N` — замутить на N минут\n"
        "`.unmute` — снять мут\n"
        "`.warn N` — предупреждения\n"
        "`.unwarn` — сбросить\n"
        "`.spam N текст` — отправить N раз\n"
        "`.st текст` — по словам\n"
        "`.clone on/off` — автоповтор",
        parse_mode="Markdown", reply_markup=back_kb())

@dp.callback_query(F.data == "sub_menu")
async def cb_sub(call: types.CallbackQuery):
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"{v['label']} — {v['rub']}₽/{v['stars']}⭐", callback_data=f"pay_{k}")] for k, v in PRICES.items()
    ] + [[types.InlineKeyboardButton(text="🔙 В меню", callback_data="back_main")]])
    await call.message.edit_text("💎 *Подписка*\n\n🎁 Пробный период 7 дней!\nВыбери тариф 👇", parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data.startswith("pay_"))
async def cb_pay(call: types.CallbackQuery):
    plan = call.data.split("_")[1]
    p = PRICES[plan]
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⭐ Звёздами", callback_data=f"stars_{plan}")],
        [types.InlineKeyboardButton(text="💳 Карта", callback_data=f"card_{plan}")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="sub_menu")]])
    await call.message.edit_text(f"💳 *{p['label']}*\n💰 {p['rub']}₽ или {p['stars']}⭐", parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data.startswith("card_"))
async def cb_card(call: types.CallbackQuery):
    plan = call.data.split("_")[1]
    p = PRICES[plan]
    await call.message.answer(f"💳 Оплата {p['label']} ({p['rub']}₽)\nКарта: `{CARD_NUMBER}`", parse_mode="Markdown")

@dp.callback_query(F.data.startswith("stars_"))
async def cb_stars(call: types.CallbackQuery):
    plan = call.data.split("_")[1]
    p = PRICES[plan]
    try:
        await bot.send_invoice(chat_id=call.from_user.id, title=f"Подписка {p['label']}", description=p['label'], payload=f"sub_{plan}", provider_token="", currency="XTR", prices=[LabeledPrice(label=p["label"], amount=p["stars"])])
    except Exception as e:
        logging.error(f"invoice: {e}")
        await call.message.answer(f"⭐ Отправьте {p['stars']}⭐ на @{OWNER_USERNAME}")

@dp.callback_query(F.data == "ref")
async def cb_ref(call: types.CallbackQuery):
    uname = bot.username or "my_bot"
    link = f"https://t.me/{uname}?start=ref_{call.from_user.id}"
    await call.message.edit_text(f"👥 *Рефералка*\n🔗 `{link}`", parse_mode="Markdown", reply_markup=back_kb())

@dp.callback_query(F.data == "howto")
async def cb_howto(call: types.CallbackQuery):
    await call.message.edit_text("📚 Настройки → Аккаунт → Автоматизация чатов → Подключить бота", reply_markup=back_kb())

# ================== BUSINESS КОМАНДЫ (только для владельца) ==================
@dp.business_message(F.text.startswith(".mute"))
async def b_mute(message: types.Message):
    if message.from_user.id != OWNER_USER_ID:
        return
    parts = message.text.split()
    m = int(parts[1]) if len(parts) > 1 else 10
    mutes[message.chat.id] = datetime.now() + timedelta(minutes=m)
    await message.answer(f"🔇 Мут {m} мин")

@dp.business_message(F.text.startswith(".unmute"))
async def b_unmute(message: types.Message):
    if message.from_user.id != OWNER_USER_ID:
        return
    mutes.pop(message.chat.id, None)
    await message.answer("🔊 Мут снят")

@dp.business_message(F.text.startswith(".warn"))
async def b_warn(message: types.Message):
    if message.from_user.id != OWNER_USER_ID:
        return
    parts = message.text.split()
    n = int(parts[1]) if len(parts) > 1 else 1
    t = message.chat.id
    warns[t] = min(warns.get(t, 0) + n, WARN_LIMIT)
    await message.answer(f"⚠️ {warns[t]}/{WARN_LIMIT}")
    if warns[t] >= WARN_LIMIT:
        mutes[t] = datetime.now() + timedelta(minutes=WARN_MUTE_MINUTES)

@dp.business_message(F.text.startswith(".unwarn"))
async def b_unwarn(message: types.Message):
    if message.from_user.id != OWNER_USER_ID:
        return
    warns.pop(message.chat.id, None)
    mutes.pop(message.chat.id, None)
    await message.answer("✅ Сброшено")

@dp.business_message(F.text.startswith(".spam"))
async def b_spam(message: types.Message):
    if message.from_user.id != OWNER_USER_ID:
        return
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

@dp.business_message(F.text.startswith(".clone"))
async def b_clone(message: types.Message):
    if message.from_user.id != OWNER_USER_ID:
        return
    parts = message.text.split()
    state = parts[1].lower() if len(parts) > 1 else "on"
    clone[message.chat.id] = (state == "on")
    await message.answer(f"🔄 Автоповтор {'включён' if state == 'on' else 'выключен'}")

@dp.business_message(F.text.startswith(".st"))
async def b_st(message: types.Message):
    if message.from_user.id != OWNER_USER_ID:
        return
    text = message.text.replace(".st", "", 1).strip()
    if text:
        for word in text.split():
            await message.answer(word)

# ================== ОБРАБОТКА СООБЩЕНИЙ ==================
@dp.business_message()
async def b_default(message: types.Message):
    t = message.chat.id
    msg_from = message.from_user.id if message.from_user else 0

    # Мут — удаляем сообщения собеседника
    if t in mutes and mutes[t] > datetime.now():
        if msg_from != OWNER_USER_ID:
            try:
                await bot(DeleteBusinessMessages(
                    business_connection_id=message.business_connection_id,
                    message_ids=[message.message_id],
                ))
            except Exception as e:
                logging.error(f"Ошибка удаления: {e}")
            return

    # Мут истёк — сброс
    if t in mutes and mutes[t] <= datetime.now():
        mutes.pop(t, None)
        warns.pop(t, None)

    # Автоповтор
    if clone.get(t) and message.text and msg_from != OWNER_USER_ID:
        await message.answer(message.text)

# ================== ЗАПУСК ==================
async def main():
    me = await bot.get_me()
    bot.username = me.username
    print(f"✅ Bot started: @{me.username}")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
