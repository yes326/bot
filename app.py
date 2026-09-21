import os
import logging
import threading
import asyncio
import random
from datetime import datetime, timedelta
from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8632065717:AAG5RRQJnVaDSGK7TfHtmuQ4IQT5elLE0w0")
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

# Хранилища данных
business_owners = {}
subscriptions = {}
pending_payments = {}
used_trials = set()
message_cache = {}
silent_mode = {}
warns = {}
mutes = {}
clone = {}
warn_messages = {}
stats = {}

# ================== FLASK (ДЛЯ РАБОТЫ НА ХОСТИНГЕ) ==================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot is running"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

# ================== ИНИЦИАЛИЗАЦИЯ AIOGRAM ==================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==================
async def check_subscription(user_id):
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status not in ("left", "kicked")
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
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

async def is_owner(message: types.Message):
    oid = await get_owner_id(message.business_connection_id)
    return oid is not None and message.from_user.id == oid

async def check_business_subscription(message: types.Message):
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

async def try_delete(message: types.Message):
    try:
        await message.delete()
    except:
        pass

async def send_photo_or_text(target, caption, reply_markup=None, parse_mode=None):
    """Отправляет или редактирует сообщение, добавляя изображение баннера"""
    try:
        photo_file = types.FSInputFile(BANNER_PATH)
        if isinstance(target, types.CallbackQuery):
            if target.message.photo:
                await target.message.edit_media(
                    media=types.InputMediaPhoto(media=photo_file, caption=caption, parse_mode=parse_mode),
                    reply_markup=reply_markup
                )
            else:
                await target.message.delete()
                await target.message.answer_photo(
                    photo=photo_file,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
        else:
            await target.answer_photo(
                photo=photo_file,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
    except Exception as e:
        logging.error(f"Ошибка работы с фото: {e}")
        if isinstance(target, types.CallbackQuery):
            try:
                await target.message.edit_text(caption, reply_markup=reply_markup, parse_mode=parse_mode)
            except:
                await target.message.answer(caption, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await target.answer(caption, reply_markup=reply_markup, parse_mode=parse_mode)

def main_menu():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📖 Команды", callback_data="cmd_list")],
        [types.InlineKeyboardButton(text="💎 Подписка", callback_data="sub_menu")],
        [types.InlineKeyboardButton(text="👥 Реферальная система", callback_data="ref")],
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

# ================== ЛИЧНЫЕ СООБЩЕНИЯ (ЛИЧКА БОТА) ==================
@dp.message(F.text == "/start")
async def start_cmd(message: types.Message):
    uid = message.from_user.id
    if not await check_subscription(uid):
        await message.answer("⚠️ Подпишись на канал:", reply_markup=subscribe_kb())
        return
    await send_photo_or_text(message, "🏠 Главное меню", reply_markup=main_menu())

@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(call: types.CallbackQuery):
    if await check_subscription(call.from_user.id):
        try:
            await call.message.delete()
        except:
            pass
        await send_photo_or_text(call, "🏠 Главное меню", reply_markup=main_menu())
    else:
        await call.answer("❌ Не подписан!", show_alert=True)

@dp.callback_query(F.data == "back_main")
async def cb_back(call: types.CallbackQuery):
    await send_photo_or_text(call, "🏠 Главное меню", reply_markup=main_menu())

@dp.callback_query(F.data == "cmd_list")
async def cb_cmds(call: types.CallbackQuery):
    text = (
        "📖 <b>Список доступных команд управления:</b>\n"
        "───────────────────────────────\n"
        "🔹 <code>.mute N</code> — замутить на N минут\n"
        "🔹 <code>.unmute</code> — снять мут с чата\n"
        "🔹 <code>.warn N</code> — выдать N предупреждений\n"
        "🔹 <code>.unwarn</code> — сбросить предупреждения\n"
        "🔹 <code>.kick</code> — кикнуть пользователя из чата\n"
        "🔹 <code>.del</code> — удалить сообщение (в ответ)\n"
        "🔹 <code>.clear N</code> — очистить последние N сообщений\n"
        "🔹 <code>.st текст</code> — отправить текст по буквам\n"
        "🔹 <code>.spam N текст</code> — заспамить текстом N раз\n"
        "🔹 <code>.echo текст</code> — повторить текст\n"
        "🔹 <code>.say текст</code> — отправить сообщение от бота\n"
        "🔹 <code>.roll N</code> — случайное число от 1 до N\n"
        "🔹 <code>.flip</code> — подбросить монетку (орёл/решка)\n"
        "🔹 <code>.calc выражение</code> — калькулятор\n"
        "🔹 <code>.clone on/off</code> — автоповтор сообщений\n"
        "🔹 <code>.silent on/off</code> — тихий режим\n"
        "🔹 <code>.history N</code> — история последних N сообщений\n"
        "🔹 <code>.stats</code> — статистика чата и нарушений\n"
        "🔹 <code>.info</code> — информация о чате и владельце\n"
        "───────────────────────────────"
    )
    await send_photo_or_text(call, text, reply_markup=back_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "sub_menu")
async def cb_sub(call: types.CallbackQuery):
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
    
    caption = f"💎 Подписка\n\n📌 Статус: {status}\n\n{trial_text}Выбери 👇"
    await send_photo_or_text(call, caption, reply_markup=plans_kb(uid))

@dp.callback_query(F.data == "trial")
async def cb_trial(call: types.CallbackQuery):
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
    await send_photo_or_text(call, f"🎁 Пробный период активирован до {until.strftime('%d.%m.%Y %H:%M')}")

@dp.callback_query(F.data.startswith("pay_"))
async def cb_pay(call: types.CallbackQuery):
    plan = call.data.split("_")[1]
    p = PRICES[plan]
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{plan}")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="sub_menu")],
    ])
    caption = f"💳 {p['label']} — {p['rub']}₽\nКарта: {CARD_NUMBER}\n\nНажми «Я оплатил» и пришли скриншот."
    await send_photo_or_text(call, caption, reply_markup=kb)

@dp.callback_query(F.data.startswith("paid_"))
async def cb_paid(call: types.CallbackQuery):
    plan = call.data.split("_")[1]
    pending_payments[call.from_user.id] = {"plan": plan}
    await send_photo_or_text(call, "📸 Пришли скриншот оплаты.")

@dp.message(F.photo)
async def on_screenshot(message: types.Message):
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
        await send_photo_or_text(message, "✅ Отправлено! Жди подтверждения.")
        pending_payments.pop(uid, None)
    except:
        await message.answer("⚠️ Ошибка отправки скриншота администратору.")

@dp.callback_query(F.data.startswith("approve_"))
async def cb_approve(call: types.CallbackQuery):
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

@dp.callback_query(F.data.startswith("reject_"))
async def cb_reject(call: types.CallbackQuery):
    if call.from_user.id != OWNER_ID:
        await call.answer("Только владелец!")
        return
    uid = int(call.data.split("_")[1])
    try:
        await bot.send_message(uid, "❌ Оплата отклонена.")
    except:
        pass
    await call.message.edit_reply_markup(reply_markup=None)

@dp.callback_query(F.data == "ref")
async def cb_ref(call: types.CallbackQuery):
    uname = bot.username or "my_bot"
    caption = f"👥 <b>Ваша реферальная ссылка:</b>\nhttps://t.me/{uname}?start=ref_{call.from_user.id}\n\nПриглашайте друзей и получайте бонусы!"
    await send_photo_or_text(call, caption, reply_markup=back_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "howto")
async def cb_howto(call: types.CallbackQuery):
    caption = "📚 <b>Инструкция по подключению:</b>\nПерейдите в Настройки → Аккаунт → Автоматизация чатов."
    await send_photo_or_text(call, caption, reply_markup=back_kb(), parse_mode="HTML")

# ================== БИЗНЕС КОМАНДЫ (TELEGRAM BUSINESS) ==================
@dp.business_message(F.text.startswith("."))
async def b_commands(message: types.Message):
    t = message.chat.id
    reply = message.reply_to_message
    owner_id = await get_owner_id(message.business_connection_id)
    if not await is_owner(message):
        return
    if not await check_business_subscription(message):
        return
    parts = message.text.split()
    cmd = parts[0].lower()

    if cmd == ".mute":
        m = int(parts[1]) if len(parts) > 1 else 10
        mutes[t] = datetime.now() + timedelta(minutes=m)
        get_stats(t)["mutes"] += 1
        await try_delete(message)
        await message.answer(f"🔇 Мут {m} мин")
    elif cmd == ".unmute":
        mutes.pop(t, None)
        await try_delete(message)
        await message.answer("🔊 Мут снят")
    elif cmd == ".warn":
        n = int(parts[1]) if len(parts) > 1 else 1
        warns[t] = min(warns.get(t, 0) + n, WARN_LIMIT)
        get_stats(t)["warns"] += n
        await try_delete(message)
        await message.answer(f"⚠️ Предупреждений: {warns[t]}/{WARN_LIMIT}")
        if warns[t] >= WARN_LIMIT:
            mutes[t] = datetime.now() + timedelta(minutes=WARN_MUTE_MINUTES)
    elif cmd == ".unwarn":
        warns.pop(t, None)
        mutes.pop(t, None)
        await try_delete(message)
        await message.answer("✅ Сброшено")
    elif cmd == ".del" and reply:
        await try_delete(reply)
        await try_delete(message)
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
    elif cmd == ".spam":
        p = message.text.split(maxsplit=2)
        if len(p) < 3:
            return
        try:
            n = min(int(p[1]), 100)
        except:
            n = 1
        
        spam_text = p[2]
        await try_delete(message)
        
        async def send_msg():
            try:
                await message.answer(spam_text)
            except Exception as e:
                if "retry after" in str(e).lower():
                    await asyncio.sleep(1)
                    try:
                        await message.answer(spam_text)
                    except:
                        pass

        tasks = []
        for _ in range(n):
            tasks.append(asyncio.create_task(send_msg()))
            await asyncio.sleep(0.02)  # Минимальная пауза 0.02 сек для отправки на максимальной скорости
        await asyncio.gather(*tasks, return_exceptions=True)

    elif cmd == ".st":
        text = message.text[3:].strip()
        if not text:
            return
        await try_delete(message)
        for word in text.split():
            try:
                await message.answer(word)
                await asyncio.sleep(0.05)
            except:
                await asyncio.sleep(0.2)
    elif cmd in (".echo", ".say"):
        text = message.text.split(maxsplit=1)[1] if len(parts) > 1 else ""
        if text:
            await message.answer(text)
        await try_delete(message)
    elif cmd == ".roll":
        n = int(parts[1]) if len(parts) > 1 else 100
        await try_delete(message)
        await message.answer(f"🎲 {random.randint(1, n)}")
    elif cmd == ".flip":
        await try_delete(message)
        await message.answer(random.choice(["🦅 Орёл", "🪙 Решка"]))
    elif cmd == ".calc":
        expr = message.text[5:].strip()
        try:
            res = eval(expr, {"__builtins__": None}, {})
        except:
            res = "ошибка"
        await try_delete(message)
        await message.answer(f"🧮 {expr} = {res}")
    elif cmd == ".clone":
        state = parts[1].lower() if len(parts) > 1 else "on"
        clone[t] = (state == "on")
        await try_delete(message)
        await message.answer(f"🔄 Автоповтор {'вкл' if state == 'on' else 'выкл'}")
    elif cmd == ".silent":
        state = parts[1].lower() if len(parts) > 1 else "on"
        silent_mode[t] = (state == "on")
        await try_delete(message)
        if state == "off":
            await message.answer("🔊 Тихий режим выкл")
    elif cmd == ".stats":
        s = get_stats(t)
        await try_delete(message)
        await message.answer(f"📊 Варнов: {warns.get(t, 0)}/{WARN_LIMIT}\nМут: {'да' if t in mutes else 'нет'}\nУдалено: {s['deleted']}")
    elif cmd == ".info":
        await try_delete(message)
        await message.answer(f"🆔 {t}\nВладелец: {owner_id}\nВ кэше: {len(message_cache.get(t, {}))}")
    elif cmd == ".history":
        n = int(parts[1]) if len(parts) > 1 else 10
        await try_delete(message)
        if t not in message_cache or not message_cache[t]:
            await message.answer("📭 История пуста")
            return
        items = sorted(message_cache[t].items(), key=lambda x: x[1]["time"])[-n:]
        text = f"📜 Последние {len(items)}:\n\n"
        for mid, d in items:
            who = "Ты" if d["sender"] == owner_id else "Собеседник"
            text += f"{who} ({d['time']}): {d['text'][:150]}\n"
        await message.answer(text[:4000])

# ================== ОБРАБОТКА ОБЫЧНЫХ БИЗНЕС-СООБЩЕНИЙ ==================
@dp.business_message()
async def on_biz_message(message: types.Message):
    t = message.chat.id
    owner_id = await get_owner_id(message.business_connection_id)
    msg_from = message.from_user.id if message.from_user else 0

    if message.text and message.text.startswith(".") and msg_from != owner_id:
        return
    if silent_mode.get(t) and msg_from == owner_id:
        return

    if t not in message_cache:
        message_cache[t] = {}
    message_cache[t][message.message_id] = {
        "text": message.text or "[медиа]",
        "time": message.date.strftime("%Y-%m-%d %H:%M:%S"),
        "sender": msg_from
    }
    if len(message_cache[t]) > 200:
        oldest = sorted(message_cache[t].keys())[0]
        message_cache[t].pop(oldest, None)

    if t in mutes and mutes[t] > datetime.now():
        if msg_from != owner_id:
            try:
                await message.delete()
                get_stats(t)["deleted"] += 1
            except:
                pass
            return

    if t in mutes and mutes[t] <= datetime.now():
        mutes.pop(t, None)
        warns.pop(t, None)

    if clone.get(t) and message.text and msg_from != owner_id:
        await message.answer(message.text)

# ================== ЗАПУСК ==================
async def main():
    me = await bot.get_me()
    bot.username = me.username
    logging.info(f"✅ Бот успешно запущен: @{me.username}")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
  
