import os
import logging
import threading
import asyncio
from datetime import datetime, timedelta
from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import DeleteBusinessMessages

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
WARN_LIMIT = 5
WARN_MUTE_MINUTES = 5

BANNER_PATH = os.path.join(os.path.dirname(__file__), "IMG_20260918_155302_695.jpg")

business_owners = {}
subscriptions = {}
pending_payments = {}
message_cache = {}  # chat_id -> {msg_id: {"text", "time", "sender"}}

# ================== FLASK ==================
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
    except:
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

def plans_kb():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"{v['label']} — {v['rub']}₽", callback_data=f"pay_{k}")] for k, v in PRICES.items()
    ] + [[types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]])

# ================== /START ==================
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
        "`.mute N` — замутить на N минут\n"
        "`.unmute` — снять мут\n"
        "`.warn N` — предупреждения\n"
        "`.unwarn` — сбросить\n"
        "`.spam N текст` — отправить N раз\n"
        "`.st текст` — по словам\n"
        "`.clone on/off` — автоповтор\n"
        "`.history N` — последние N сообщений",
        parse_mode="Markdown", reply_markup=back_kb())

@dp.callback_query(F.data == "sub_menu")
async def cb_sub(call: types.CallbackQuery):
    await call.message.answer(
        "💎 *Подписка AntiSpam Defender*\n\n"
        "🎁 Новым — пробный период 7 дней!\n\n"
        "Выбери тариф 👇",
        parse_mode="Markdown", reply_markup=plans_kb())

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
        f"📸 После перевода нажми кнопку «Я оплатил» и пришли скриншот.",
        parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data.startswith("paid_"))
async def cb_paid(call: types.CallbackQuery):
    plan = call.data.split("_")[1]
    pending_payments[call.from_user.id] = {"plan": plan}
    logging.info(f"Ожидаю скриншот от {call.from_user.id}, тариф {plan}")
    await call.message.answer("📸 Пришли скриншот оплаты одним сообщением-фото.")

# ================== ПРИЁМ СКРИНШОТА ==================
@dp.message(F.photo)
async def on_screenshot(message: types.Message):
    user_id = message.from_user.id
    logging.info(f"Получено фото от {user_id}, в pending: {user_id in pending_payments}")

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
        await message.answer("✅ Скриншот отправлен! Ожидай подтверждения оплаты.")
        pending_payments.pop(user_id, None)
    except Exception as e:
        logging.error(f"Не смог переслать скриншот: {e}")
        await message.answer("⚠️ Ошибка при отправке. Свяжитесь с @ysorn.")

# ================== ПОДТВЕРЖДЕНИЕ ОПЛАТЫ ==================
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
    except Exception as e:
        logging.error(f"Не смог уведомить покупателя: {e}")

    try:
        await call.message.edit_caption(caption="✅ Оплата подтверждена")
    except:
        pass
    await call.answer("Подписка активирована ✅")

@dp.callback_query(F.data.startswith("reject_"))
async def cb_reject(call: types.CallbackQuery):
    if call.from_user.id != OWNER_ID:
        await call.answer("Только владелец может отклонять!", show_alert=True)
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

# ================== РЕФЕРАЛКА ==================
@dp.callback_query(F.data == "ref")
async def cb_ref(call: types.CallbackQuery):
    uname = bot.username or "my_bot"
    link = f"https://t.me/{uname}?start=ref_{call.from_user.id}"
    await call.message.answer(f"👥 *Рефералка*\n🔗 `{link}`", parse_mode="Markdown", reply_markup=back_kb())

@dp.callback_query(F.data == "howto")
async def cb_howto(call: types.CallbackQuery):
    await call.message.answer("📚 Настройки → Аккаунт → Автоматизация чатов → Подключить бота", reply_markup=back_kb())

# ================== BUSINESS КОМАНДЫ ==================
@dp.business_message(F.text.startswith(".mute"))
async def b_mute(message: types.Message):
    if not await is_owner(message):
        return
    parts = message.text.split()
    m = int(parts[1]) if len(parts) > 1 else 10
    mutes[message.chat.id] = datetime.now() + timedelta(minutes=m)
    await message.answer(f"🔇 Мут {m} мин")

@dp.business_message(F.text.startswith(".unmute"))
async def b_unmute(message: types.Message):
    if not await is_owner(message):
        return
    mutes.pop(message.chat.id, None)
    await message.answer("🔊 Мут снят")

@dp.business_message(F.text.startswith(".warn"))
async def b_warn(message: types.Message):
    if not await is_owner(message):
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
    if not await is_owner(message):
        return
    warns.pop(message.chat.id, None)
    mutes.pop(message.chat.id, None)
    await message.answer("✅ Сброшено")

@dp.business_message(F.text.startswith(".spam"))
async def b_spam(message: types.Message):
    if not await is_owner(message):
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
    if not await is_owner(message):
        return
    parts = message.text.split()
    state = parts[1].lower() if len(parts) > 1 else "on"
    clone[message.chat.id] = (state == "on")
    await message.answer(f"🔄 Автоповтор {'включён' if state == 'on' else 'выключен'}")

@dp.business_message(F.text.startswith(".st"))
async def b_st(message: types.Message):
    if not await is_owner(message):
        return
    text = message.text.replace(".st", "", 1).strip()
    if text:
        for word in text.split():
            await message.answer(word)

@dp.business_message(F.text.startswith(".history"))
async def b_history(message: types.Message):
    if not await is_owner(message):
        return
    t = message.chat.id
    parts = message.text.split()
    n = int(parts[1]) if len(parts) > 1 else 10

    if t not in message_cache or not message_cache[t]:
        await message.answer("📭 История пуста.")
        return

    items = sorted(message_cache[t].items(), key=lambda x: x[1]["time"])[-n:]
    owner_id = await get_owner_id(message.business_connection_id)

    text = f"📜 *Последние {len(items)} сообщений:*\n\n"
    for msg_id, data in items:
        sender = "Ты" if data["sender"] == owner_id else "Собеседник"
        text += f"*{sender}* ({data['time']}):\n`{data['text'][:200]}`\n\n"

    if len(text) > 4000:
        text = text[:4000] + "\n...(обрезано)"
    await message.answer(text, parse_mode="Markdown")

# ================== ОБРАБОТКА СООБЩЕНИЙ ==================
@dp.business_message()
async def b_default(message: types.Message):
    t = message.chat.id
    owner_id = await get_owner_id(message.business_connection_id)
    msg_from = message.from_user.id if message.from_user else 0

    # ---------- 1. Проверка изменений ----------
    if t in message_cache and message.message_id in message_cache[t]:
        old = message_cache[t][message.message_id]
        new_text = message.text or "[медиа]"
        if old["text"] != new_text:
            try:
                await bot.send_message(
                    OWNER_ID,
                    f"✏️ *Сообщение изменено*\n\n"
                    f"👤 От: @{message.from_user.username or message.from_user.first_name}\n"
                    f"📝 Было: `{old['text'][:200]}`\n"
                    f"📝 Стало: `{new_text[:200]}`\n"
                    f"🕐 {datetime.now().strftime('%H:%M:%S')}",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"Не смог уведомить об изменении: {e}")
        message_cache[t][message.message_id]["text"] = new_text

    # ---------- 2. Сохраняем сообщение в кэш ----------
    if t not in message_cache:
        message_cache[t] = {}
    message_cache[t][message.message_id] = {
        "text": message.text or "[медиа]",
        "time": message.date.strftime("%Y-%m-%d %H:%M:%S"),
        "sender": msg_from,
    }
    if len(message_cache[t]) > 200:
        oldest = sorted(message_cache[t].keys())[0]
        message_cache[t].pop(oldest, None)

    # ---------- 3. Мут — удаляем сообщения собеседника ----------
    if t in mutes and mutes[t] > datetime.now():
        if msg_from != owner_id:
            try:
                await bot(DeleteBusinessMessages(
                    business_connection_id=message.business_connection_id,
                    message_ids=[message.message_id],
                ))
                # Уведомляем владельца, что удалили сообщение
                try:
                    await bot.send_message(
                        OWNER_ID,
                        f"🗑 *Удалено (мут)*\n\n"
                        f"👤 От: @{message.from_user.username or message.from_user.first_name}\n"
                        f"📝 Текст: `{(message.text or '[медиа]')[:200]}`\n"
                        f"🕐 {datetime.now().strftime('%H:%M:%S')}",
                        parse_mode="Markdown"
                    )
                except:
                    pass
            except Exception as e:
                logging.error(f"Ошибка удаления: {e}")
            return

    if t in mutes and mutes[t] <= datetime.now():
        mutes.pop(t, None); warns.pop(t, None)

    # ---------- 4. Автоповтор ----------
    if clone.get(t) and message.text and msg_from != owner_id:
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
