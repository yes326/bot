# -*- coding: utf-8 -*-
"""
AntiSpam Defender Bot — Business-бот.
nonmute выключен по умолчанию. Добавлена команда .story.
"""

import os
import logging
import threading
import asyncio
import aiohttp
import time
import io
import ast
import operator
import random
import aiosqlite
import qrcode
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SetMyName
from aiogram.types import BufferedInputFile

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
    'Х': 'X', 'і': 'i', 'ї': 'i', 'ё': 'e',
    'б': '6', 'з': '3', 'в': 'b', 'г': 'r', 'д': 'd',
    'л': 'l', 'м': 'm', 'н': 'n', 'п': 'n', 'ф': 'f',
    'ц': 'u', 'ч': '4', 'ш': 'w', 'щ': 'w', 'ы': 'b',
    'ь': 'b', 'э': 'e', 'ю': 'io', 'я': 'ya',
    'Б': '6', 'З': '3', 'Г': 'R', 'Д': 'D', 'Л': 'L',
    'П': 'N', 'Ф': 'F', 'Ц': 'U', 'Ч': '4', 'Ш': 'W',
    'Щ': 'W', 'Ы': 'B', 'Э': 'E', 'Ю': 'IO', 'Я': 'YA',
}

DB_PATH = "bot.db"
NAME_UPDATE_INTERVAL = 86400
CACHE_LIMIT = 200
DEDUP_WINDOW = 5

BANNER_PATH = os.path.join(os.path.dirname(__file__), "angel.jpg")
BANNER_FALLBACK = os.path.join(os.path.dirname(__file__), "IMG_20260918_155302_695.jpg")


def get_banner_path():
    if os.path.exists(BANNER_PATH):
        return BANNER_PATH
    if os.path.exists(BANNER_FALLBACK):
        return BANNER_FALLBACK
    return None


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
echo_chats = {}
ghost_chats = {}
rps_games = {}
ttt_games = {}
wordle_games = {}
processed_updates = {}
deleted_by_bot = set()


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
def is_duplicate(chat_id: int, from_user_id: int, text: str) -> bool:
    now = time.time()
    key = (chat_id, from_user_id, (text or "")[:100])
    last = processed_updates.get(key)
    if last and (now - last) < DEDUP_WINDOW:
        return True
    processed_updates[key] = now
    if len(processed_updates) > 500:
        old_keys = [k for k, v in processed_updates.items() if now - v > 60]
        for k in old_keys:
            processed_updates.pop(k, None)
    return False


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
        deleted_by_bot.add(message_id)
        await delete_business_msg(conn_id, [message_id])
    except Exception as e:
        logging.error(f"auto_delete failed: {e}")


async def delete_cmd(message):
    if not message.business_connection_id:
        return
    try:
        deleted_by_bot.add(message.message_id)
        await delete_business_msg(message.business_connection_id, [message.message_id])
        logging.info(f"✅ Удалена команда: {(message.text or '')[:30]}")
    except Exception as e:
        logging.error(f"❌ Ошибка удаления: {type(e).__name__}: {e}")


async def send_confirm(chat_id, text, conn_id, seconds=None, reply_markup=None):
    try:
        kwargs = {"chat_id": chat_id, "text": text, "business_connection_id": conn_id, "parse_mode": "HTML"}
        if reply_markup:
            kwargs["reply_markup"] = reply_markup
        msg = await bot.send_message(**kwargs)
        if seconds is not None:
            asyncio.create_task(auto_delete(chat_id, msg.message_id, conn_id, seconds))
        return msg
    except Exception as e:
        logging.error(f"send_confirm failed: {e}")
        return None


async def send_chat_action(chat_id, conn_id, action):
    actions_map = {
        "typing": "typing",
        "photo": "upload_photo",
        "video": "upload_video",
        "voice": "record_voice",
        "document": "upload_document",
    }
    act = actions_map.get(action, "typing")
    try:
        result = await bot_api("sendChatAction", {
            "chat_id": chat_id,
            "business_connection_id": conn_id,
            "action": act,
        })
        if result:
            logging.info(f"✅ ChatAction '{act}' → chat={chat_id}")
        return result
    except Exception as e:
        logging.error(f"send_chat_action: {e}")
        return None


async def send_photo_banner(chat_id, caption, conn_id=None, reply_markup=None, parse_mode="HTML"):
    path = get_banner_path()
    if path:
        try:
            kwargs = {
                "chat_id": chat_id,
                "photo": types.FSInputFile(path),
                "caption": caption,
                "parse_mode": parse_mode,
            }
            if reply_markup:
                kwargs["reply_markup"] = reply_markup
            if conn_id:
                kwargs["business_connection_id"] = conn_id
            return await bot.send_photo(**kwargs)
        except Exception as e:
            logging.error(f"send_photo_banner: {e}")
    try:
        kwargs = {"chat_id": chat_id, "text": caption, "parse_mode": parse_mode}
        if reply_markup:
            kwargs["reply_markup"] = reply_markup
        if conn_id:
            kwargs["business_connection_id"] = conn_id
        return await bot.send_message(**kwargs)
    except Exception as e:
        logging.error(f"send_message fallback: {e}")
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


def cache_message(message):
    try:
        chat_id = message.chat.id
        if chat_id not in message_cache:
            message_cache[chat_id] = {}
        entry = {
            "from_id": message.from_user.id if message.from_user else None,
            "from_name": message.from_user.full_name if message.from_user else "?",
            "text": message.text or message.caption,
            "photo": message.photo[-1].file_id if message.photo else None,
            "video": message.video.file_id if message.video else None,
            "video_note": message.video_note.file_id if message.video_note else None,
            "voice": message.voice.file_id if message.voice else None,
            "audio": message.audio.file_id if message.audio else None,
            "document": message.document.file_id if message.document else None,
            "sticker": message.sticker.file_id if message.sticker else None,
            "animation": message.animation.file_id if message.animation else None,
            "date": message.date.isoformat() if message.date else None,
        }
        message_cache[chat_id][message.message_id] = entry
        if len(message_cache[chat_id]) > CACHE_LIMIT:
            sorted_ids = sorted(message_cache[chat_id].keys())
            for old_id in sorted_ids[:len(sorted_ids) - CACHE_LIMIT]:
                message_cache[chat_id].pop(old_id, None)
    except Exception as e:
        logging.error(f"cache_message: {e}")


# ================== STORY: НАРЕЗКА И СКАЧИВАНИЕ ==================
async def download_file(file_id: str):
    """Скачивает файл из Telegram по file_id. Возвращает bytes."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"file_id": file_id}) as r:
                data = await r.json()
                if not data.get("ok"):
                    logging.error(f"getFile: {data}")
                    return None
                file_path = data["result"]["file_path"]
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
            async with session.get(file_url) as r:
                return await r.read()
    except Exception as e:
        logging.error(f"download_file: {e}")
        return None


def split_3x3(img_bytes: bytes):
    """Режет фото на 9 частей 3×3. Возвращает список bytes JPEG."""
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
        cell = side // 3
        parts = []
        for r in range(3):
            for c in range(3):
                box = (c * cell, r * cell, (c + 1) * cell, (r + 1) * cell)
                piece = img.crop(box)
                buf = io.BytesIO()
                piece.save(buf, format="JPEG", quality=95)
                parts.append(buf.getvalue())
        return parts
    except Exception as e:
        logging.error(f"split_3x3: {e}")
        return []


# ================== КАЛЬКУЛЯТОР ==================
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.FloorDiv: operator.floordiv,
}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("Только числа")
    if isinstance(node, ast.BinOp):
        op = _SAFE_OPS.get(type(node.op))
        if not op:
            raise ValueError("Операция запрещена")
        return op(_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _SAFE_OPS.get(type(node.op))
        if not op:
            raise ValueError("Операция запрещена")
        return op(_safe_eval(node.operand))
    raise ValueError("Выражение не поддерживается")


def calc_expr(expr: str):
    try:
        tree = ast.parse(expr, mode="eval")
        result = _safe_eval(tree)
        if isinstance(result, float) and (result != result or abs(result) == float("inf")):
            return None
        return result
    except Exception:
        return None


# ================== КУРСЫ ВАЛЮТ ==================
async def fetch_prices() -> str:
    lines = ["💱 <b>Курсы валют к рублю</b>", "━━━━━━━━━━━━━━━━━━━━"]
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get("https://www.cbr-xml-daily.ru/daily_json.js") as r:
                data = await r.json()
                usd = data["Valute"]["USD"]["Value"]
                eur = data["Valute"]["EUR"]["Value"]
                cny = data["Valute"]["CNY"]["Value"]
                lines.append(f"🇺🇸 USD: <b>{usd:.2f}₽</b>")
                lines.append(f"🇪🇺 EUR: <b>{eur:.2f}₽</b>")
                lines.append(f"🇨🇳 CNY: <b>{cny:.2f}₽</b>")
            try:
                url = "https://api.coingecko.com/api/v3/simple/price?ids=tether,the-open-network&vs_currencies=rub"
                async with session.get(url) as r:
                    d = await r.json()
                    if "tether" in d:
                        lines.append(f"💵 USDT: <b>{d['tether']['rub']:.2f}₽</b>")
                    if "the-open-network" in d:
                        lines.append(f"💎 TON (GRAM): <b>{d['the-open-network']['rub']:.2f}₽</b>")
            except Exception as e:
                logging.error(f"coingecko: {e}")
    except Exception as e:
        logging.error(f"cbr: {e}")
        return "❌ Не удалось получить курсы"
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


# ================== RPS / TTT / WORDLE ==================
RPS_WINS = {"камень": "ножницы", "ножницы": "бумага", "бумага": "камень"}


def rps_result(player: str, bot_choice: str) -> str:
    if player == bot_choice:
        return "🤝 Ничья!"
    if RPS_WINS[player] == bot_choice:
        return "🎉 Ты победил!"
    return "😢 Ты проиграл!"


def ttt_board_kb(chat_id: int):
    game = ttt_games.get(chat_id)
    if not game:
        return None
    board = game["board"]
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            idx = r * 3 + c
            label = board[idx] if board[idx] != " " else "·"
            row.append(types.InlineKeyboardButton(text=label, callback_data=f"ttt_{idx}"))
        rows.append(row)
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def ttt_check_winner(board):
    lines = [
        [0,1,2],[3,4,5],[6,7,8],
        [0,3,6],[1,4,7],[2,5,8],
        [0,4,8],[2,4,6],
    ]
    for a,b,c in lines:
        if board[a] != " " and board[a] == board[b] == board[c]:
            return board[a]
    if " " not in board:
        return "draw"
    return None


def wordle_render(game) -> str:
    out = ["🎯 <b>Wordle</b>", "━━━━━━━━━━━━━━━━━━━━",
           f"Слово из <b>{len(game['word'])}</b> букв. Попыток: <b>{game['tries']}</b>", ""]
    for guess, marks in game["history"]:
        line = ""
        for i, ch in enumerate(guess):
            if marks[i] == "G":
                line += f"🟩{ch.upper()}"
            elif marks[i] == "Y":
                line += f"🟨{ch.upper()}"
            else:
                line += f"⬜{ch.upper()}"
        out.append(line)
    out.append("")
    out.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(out)


def wordle_marks(word: str, guess: str) -> str:
    marks = ["B"] * len(word)
    used = [False] * len(word)
    for i in range(len(word)):
        if guess[i] == word[i]:
            marks[i] = "G"
            used[i] = True
    for i in range(len(word)):
        if marks[i] == "G":
            continue
        for j in range(len(word)):
            if not used[j] and guess[i] == word[j]:
                marks[i] = "Y"
                used[j] = True
                break
    return "".join(marks)


# ================== ФОНОВАЯ ЗАДАЧА ==================
async def update_bot_name():
    try:
        total = await get_total_users()
        new_name = f"AntiSpam Defender | {total}"
        if len(new_name) > 64:
            new_name = f"AntiSpam | {total}"
        await bot(SetMyName(name=new_name))
        logging.info(f"🏷 Имя бота: {new_name}")
        return True
    except Exception as e:
        err = str(e)
        if "Flood control" in err or "Too Many Requests" in err:
            logging.warning(f"⏳ Flood control на setMyName")
        else:
            logging.error(f"❌ Ошибка обновления имени: {e}")
        return False


async def background_name_updater():
    await asyncio.sleep(300)
    ok = await update_bot_name()
    while True:
        if ok:
            await asyncio.sleep(NAME_UPDATE_INTERVAL)
        else:
            await asyncio.sleep(7200)
        ok = await update_bot_name()


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


# ================== ТЕКСТЫ ==================
TEXT_MAIN_MENU = (
    "🏠 <b>Главное меню</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🛡 <b>AntiSpam Defender</b> — защита\n"
    "ваших бизнес-чатов от спама\n"
    "и нежелательных сообщений.\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "👇 <i>Выбери действие:</i>"
)

TEXT_CMD_LIST = (
    "📖 <b>Команды бота</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "🛡 <b>Модерация</b>\n"
    "• <code>.mute N</code> — мут на N мин\n"
    "• <code>.unmute</code> — снять мут\n"
    "• <code>.warn N</code> — предупреждения\n"
    "• <code>.unwarn</code> — сбросить\n"
    "• <code>.spam N текст</code> — спам\n"
    "• <code>.nonmute on/off</code> — обход мута\n\n"
    "🎮 <b>Развлечения</b>\n"
    "• <code>.info</code> — данные собеседника\n"
    "• <code>.st текст</code> — текст по словам\n"
    "• <code>.calc 5*5</code> — калькулятор\n"
    "• <code>.qr текст</code> — QR-код\n"
    "• <code>.clone on/off</code> — автоповтор\n"
    "• <code>.echo on/off</code> — эхо\n"
    "• <code>.dl N текст</code> — автоудаление\n"
    "• <code>.txt текст</code> — анимация печати\n"
    "• <code>.rps</code> — камень-ножницы-бумага\n"
    "• <code>.ttt</code> — крестики-нолики\n"
    "• <code>.wordle слово</code> — угадай слово\n\n"
    "📸 <b>Истории</b>\n"
    "• <code>.story</code> (ответ на фото) — 3×3 в историю\n\n"
    "📝 <b>Статусы</b>\n"
    "• <code>.text</code> — «печатает» (5 сек)\n"
    "• <code>.photo</code> — «фото» (5 сек)\n"
    "• <code>.gs</code> — «голосовое» (5 сек)\n\n"
    "💱 <b>Полезное</b>\n"
    "• <code>.price</code> — курсы валют\n\n"
    "👻 <b>Приватность</b>\n"
    "• <code>.ghost on/off</code> — копия входящих в ЛС\n\n"
    "📸 <b>Медиа</b>\n"
    "• Ответ на медиа → одноразовое фото в ЛС\n"
    "━━━━━━━━━━━━━━━━━━━━"
)

TEXT_HOWTO = (
    "📚 <b>Как подключить</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "1️⃣ Открой <b>Настройки</b>\n"
    "2️⃣ Перейди в <b>Аккаунт</b>\n"
    "3️⃣ Найди <b>Автоматизация чатов</b>\n"
    "4️⃣ Выбери <b>AntiSpam Defender</b>\n\n"
    "✅ <b>Разрешения:</b>\n"
    "• Чтение сообщений\n"
    "• Ответы на сообщения\n"
    "• Удаление сообщений\n\n"
    "💬 Пиши команды <b>в бизнес-чате</b>:\n"
    "<code>.mute 10</code>\n"
    "━━━━━━━━━━━━━━━━━━━━"
)

TEXT_REF = (
    "👥 <b>Пригласить друга</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "🎁 За каждого друга — <b>+3 дня</b> к подписке!\n\n"
    "🔗 <b>Твоя ссылка:</b>\n<code>{link}</code>\n\n"
    "📊 <b>Приглашено:</b> {count}\n"
    "━━━━━━━━━━━━━━━━━━━━"
)


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

    await send_photo_banner(message.chat.id, TEXT_MAIN_MENU, reply_markup=main_menu())


# ================== /STATS ==================
@dp.message(F.text == "/stats", F.from_user.id == OWNER_ID)
async def stats_cmd(message):
    total = await get_total_users()
    with_sub = sum(1 for u in subscriptions if subscriptions[u] > datetime.now())
    trials = len(used_trials)
    last_users = await get_last_users(10)
    text = (
        "📊 <b>Статистика бота</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Пользователей: <b>{total}</b>\n"
        f"💎 Подписок: <b>{with_sub}</b>\n"
        f"🎁 Триалов: <b>{trials}</b>\n\n"
        "🕐 <b>Последние 10:</b>\n"
    )
    for row in last_users:
        name = row["first_name"] or row["username"] or str(row["user_id"])
        uname = f"@{row['username']}" if row["username"] else ""
        text += f"• {name} {uname} (<code>{row['user_id']}</code>)\n"
    text += "━━━━━━━━━━━━━━━━━━━━"
    await message.answer(text, parse_mode="HTML")


# ================== БИЗНЕС-ПОДКЛЮЧЕНИЕ ==================
@dp.business_connection()
async def on_business_connection(conn: types.BusinessConnection):
    try:
        business_owners[conn.id] = conn.user.id
        username_cache[(conn.user.username or "").lower()] = conn.user.id
        last_conn_by_chat[conn.user.id] = conn.id
        logging.info(f"🔗 Business connection: {conn.id} owner={conn.user.id} @{conn.user.username}")
    except Exception as e:
        logging.error(f"on_business_connection: {e}")


# ================== NONMUTE ==================
@dp.deleted_business_messages()
async def on_deleted_messages(event: types.BusinessMessagesDeleted):
    try:
        chat_id = event.chat.id
        conn_id = event.business_connection_id

        owner_id_of_conn = await get_owner_id(conn_id)
        if not owner_id_of_conn:
            return

        if nonmute_active.get(chat_id, False) is not True:
            return

        cached = message_cache.get(chat_id, {})
        if not cached:
            return

        for msg_id in event.message_ids:
            if msg_id in deleted_by_bot:
                deleted_by_bot.discard(msg_id)
                continue
            data = cached.get(msg_id)
            if not data:
                continue
            txt = (data.get("text") or "").strip()
            if txt.startswith("."):
                continue
            try:
                if data.get("text"):
                    await bot.send_message(chat_id=chat_id, text=data["text"], business_connection_id=conn_id)
                elif data.get("photo"):
                    await bot.send_photo(chat_id=chat_id, photo=data["photo"], business_connection_id=conn_id)
                elif data.get("video"):
                    await bot.send_video(chat_id=chat_id, video=data["video"], business_connection_id=conn_id)
                elif data.get("video_note"):
                    await bot.send_video_note(chat_id=chat_id, video_note=data["video_note"], business_connection_id=conn_id)
                elif data.get("voice"):
                    await bot.send_voice(chat_id=chat_id, voice=data["voice"], business_connection_id=conn_id)
                elif data.get("audio"):
                    await bot.send_audio(chat_id=chat_id, audio=data["audio"], business_connection_id=conn_id)
                elif data.get("document"):
                    await bot.send_document(chat_id=chat_id, document=data["document"], business_connection_id=conn_id)
                elif data.get("sticker"):
                    await bot.send_sticker(chat_id=chat_id, sticker=data["sticker"], business_connection_id=conn_id)
                elif data.get("animation"):
                    await bot.send_animation(chat_id=chat_id, animation=data["animation"], business_connection_id=conn_id)
                logging.info(f"♻️ Восстановлено сообщение {msg_id} в чате {chat_id}")
            except Exception as e:
                logging.error(f"restore {msg_id}: {e}")
            await asyncio.sleep(0.3)
    except Exception as e:
        logging.error(f"on_deleted_messages: {type(e).__name__}: {e}")


# ================== БИЗНЕС-СООБЩЕНИЯ ==================
@dp.business_message()
async def business_msg(message: types.Message):
    try:
        text = message.text or ""
        chat_id = message.chat.id
        conn_id = message.business_connection_id

        owner_id_of_conn = await get_owner_id(conn_id)
        if not owner_id_of_conn:
            return

        if message.from_user:
            if is_duplicate(chat_id, message.from_user.id, text):
                return

        cache_message(message)

        if message.from_user:
            last_conn_by_chat[message.from_user.id] = conn_id
            if message.from_user.username:
                username_cache[message.from_user.username.lower()] = message.from_user.id

        is_incoming = message.from_user and message.from_user.id != owner_id_of_conn

        # GHOST
        if ghost_chats.get(chat_id) and is_incoming and not text.startswith("."):
            try:
                user = message.from_user
                fwd = (
                    f"👻 <b>Ghost</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 @{user.username or user.full_name} (<code>{user.id}</code>)\n"
                    f"📝 <code>{(message.text or '[медиа]')[:500]}</code>"
                )
                await bot.send_message(owner_id_of_conn, fwd, parse_mode="HTML")
            except Exception as e:
                logging.error(f"ghost: {e}")

        # ЭХО
        if echo_chats.get(chat_id) and is_incoming and text and not text.startswith("."):
            try:
                await bot.send_message(chat_id=chat_id, text=text, business_connection_id=conn_id)
            except Exception as e:
                logging.error(f"echo: {e}")
            return

        if not text.startswith("."):
            return

        if not message.from_user or message.from_user.id != owner_id_of_conn:
            return

        if not await check_subscription(owner_id_of_conn):
            await delete_cmd(message)
            await send_confirm(
                chat_id,
                "⚠️ <b>Нужна подписка на канал!</b>\n\n"
                f"📢 Подпишись: {CHANNEL_LINK}\n\n"
                "Затем напиши /start в ЛС бота.",
                conn_id)
            return

        parts = text.split()
        cmd = parts[0].lower()

        # ---- .mute ----
        if cmd == ".mute":
            try:
                minutes = int(parts[1]) if len(parts) > 1 else 10
            except ValueError:
                minutes = 10
            if message.reply_to_message and message.reply_to_message.from_user:
                target_id = message.reply_to_message.from_user.id
            else:
                target_id = chat_id
            if target_id == owner_id_of_conn:
                await delete_cmd(message)
                await send_confirm(chat_id, "❌ Ответь реплаем на сообщение собеседника", conn_id)
                return
            mutes[target_id] = datetime.now() + timedelta(minutes=minutes)
            await delete_cmd(message)
            await send_confirm(chat_id, f"🔇 <b>Мут на {minutes} мин</b>", conn_id)
            return

        # ---- .unmute ----
        if cmd == ".unmute":
            if message.reply_to_message and message.reply_to_message.from_user:
                target_id = message.reply_to_message.from_user.id
            else:
                target_id = chat_id
            mutes.pop(target_id, None)
            await delete_cmd(message)
            await send_confirm(chat_id, "🔊 <b>Мут снят</b>", conn_id)
            return

        # ---- .warn ----
        if cmd == ".warn":
            try:
                count = int(parts[1]) if len(parts) > 1 else 1
            except ValueError:
                count = 1
            if message.reply_to_message and message.reply_to_message.from_user:
                target_id = message.reply_to_message.from_user.id
            else:
                target_id = chat_id
            if target_id == owner_id_of_conn:
                await delete_cmd(message)
                await send_confirm(chat_id, "❌ Ответь реплаем на сообщение собеседника", conn_id)
                return
            warns[target_id] = warns.get(target_id, 0) + count
            await delete_cmd(message)
            await send_confirm(chat_id, f"⚠️ <b>Warn {warns[target_id]}/{WARN_LIMIT}</b>", conn_id)
            if warns[target_id] >= WARN_LIMIT:
                mutes[target_id] = datetime.now() + timedelta(minutes=WARN_MUTE_MINUTES)
                warns[target_id] = 0
                await send_confirm(chat_id, f"🔇 <b>Лимит варнов — мут {WARN_MUTE_MINUTES} мин</b>", conn_id)
            return

        # ---- .unwarn ----
        if cmd == ".unwarn":
            if message.reply_to_message and message.reply_to_message.from_user:
                target_id = message.reply_to_message.from_user.id
            else:
                target_id = chat_id
            warns.pop(target_id, None)
            await delete_cmd(message)
            await send_confirm(chat_id, "✅ <b>Варны сброшены</b>", conn_id)
            return

        # ---- .spam ----
        if cmd == ".spam":
            if len(parts) < 3:
                await delete_cmd(message)
                await send_confirm(chat_id, "❌ <code>.spam N текст</code>", conn_id)
                return
            try:
                count = min(int(parts[1]), 30)
            except ValueError:
                count = 1
            spam_text = " ".join(parts[2:])
            await delete_cmd(message)
            for _ in range(count):
                try:
                    await bot.send_message(chat_id=chat_id, text=spam_text, business_connection_id=conn_id)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logging.error(f"spam: {e}")
                    break
            return

        # ---- .st ----
        if cmd == ".st":
            if len(parts) < 2:
                await delete_cmd(message)
                return
            src = " ".join(parts[1:])
            await delete_cmd(message)
            try:
                await bot.send_message(chat_id=chat_id, text=distort(src), business_connection_id=conn_id)
            except Exception as e:
                logging.error(f"st: {e}")
            return

        # ---- .clone ----
        if cmd == ".clone":
            if len(parts) < 2:
                await delete_cmd(message)
                return
            arg = parts[1].lower()
            if arg == "on":
                clone[chat_id] = True
                await delete_cmd(message)
                await send_confirm(chat_id, "🧬 <b>Клон включён</b>", conn_id)
            else:
                clone.pop(chat_id, None)
                await delete_cmd(message)
                await send_confirm(chat_id, "🧬 <b>Клон выключен</b>", conn_id)
            return

        # ---- .nonmute ----
        if cmd == ".nonmute":
            arg = parts[1].lower() if len(parts) > 1 else ""
            if arg == "on":
                nonmute_active[chat_id] = True
                await delete_cmd(message)
                await send_confirm(chat_id, "🛡 <b>Обход мута включён</b>", conn_id)
            elif arg == "off":
                nonmute_active[chat_id] = False
                await delete_cmd(message)
                await send_confirm(chat_id, "🔒 <b>Обход мута выключен</b>", conn_id)
            else:
                await delete_cmd(message)
                await send_confirm(chat_id, "ℹ️ <code>.nonmute on/off</code>", conn_id)
            return

        # ---- .info ----
        if cmd == ".info":
            await delete_cmd(message)
            target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
            if not target:
                return
            uname = f"@{target.username}" if target.username else "—"
            out = (
                "ℹ️ <b>Данные собеседника</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Имя: <b>{target.full_name}</b>\n"
                f"🔗 Username: <b>{uname}</b>\n"
                f"🆔 ID: <code>{target.id}</code>\n"
                f"🌐 Язык: <b>{target.language_code or '—'}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )
            await send_confirm(chat_id, out, conn_id)
            return

        # ---- .calc / .c ----
        if cmd in (".calc", ".c"):
            if len(parts) < 2:
                await delete_cmd(message)
                return
            expr = " ".join(parts[1:])
            await delete_cmd(message)
            if len(expr) > 200:
                await send_confirm(chat_id, "❌ Слишком длинное", conn_id)
                return
            result = calc_expr(expr)
            if result is None:
                await send_confirm(chat_id, "❌ Не могу посчитать", conn_id)
                return
            if isinstance(result, float) and result.is_integer():
                result = int(result)
            out = (
                "🧮 <b>Калькулятор</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"<code>{expr}</code>\n"
                f"= <b>{result}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )
            await send_confirm(chat_id, out, conn_id)
            return

        # ---- .qr ----
        if cmd == ".qr":
            if len(parts) < 2:
                await delete_cmd(message)
                return
            qr_text = " ".join(parts[1:])
            await delete_cmd(message)
            if len(qr_text) > 1000:
                await send_confirm(chat_id, "❌ Слишком длинный", conn_id)
                return
            try:
                img = qrcode.make(qr_text)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                buf.seek(0)
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=BufferedInputFile(buf.read(), filename="qr.png"),
                    caption=(
                        "📱 <b>QR-код</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        f"<code>{qr_text[:100]}</code>\n"
                        "━━━━━━━━━━━━━━━━━━━━"
                    ),
                    parse_mode="HTML",
                    business_connection_id=conn_id,
                )
            except Exception as e:
                logging.error(f"QR error: {e}")
                await send_confirm(chat_id, "❌ Ошибка QR", conn_id)
            return

        # ---- .echo ----
        if cmd == ".echo":
            if len(parts) < 2:
                await delete_cmd(message)
                return
            arg = parts[1].lower()
            if arg == "on":
                echo_chats[chat_id] = True
                await delete_cmd(message)
                await send_confirm(chat_id, "🔁 <b>Эхо включено</b>", conn_id)
            else:
                echo_chats.pop(chat_id, None)
                await delete_cmd(message)
                await send_confirm(chat_id, "🔇 <b>Эхо выключено</b>", conn_id)
            return

        # ---- .dl ----
        if cmd == ".dl":
            if len(parts) < 3:
                await delete_cmd(message)
                await send_confirm(chat_id, "❌ <code>.dl N текст</code>", conn_id)
                return
            try:
                sec = min(int(parts[1]), 300)
            except ValueError:
                sec = 5
            dl_text = " ".join(parts[2:])
            await delete_cmd(message)
            try:
                msg = await bot.send_message(chat_id=chat_id, text=dl_text, business_connection_id=conn_id)
                asyncio.create_task(auto_delete(chat_id, msg.message_id, conn_id, sec))
            except Exception as e:
                logging.error(f"dl: {e}")
            return

        # ---- .txt ----
        if cmd == ".txt":
            if len(parts) < 2:
                await delete_cmd(message)
                return
            src = " ".join(parts[1:])
            await delete_cmd(message)
            try:
                msg = await bot.send_message(chat_id=chat_id, text="▫️", business_connection_id=conn_id)
                current = ""
                for ch in src[:80]:
                    current += ch
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id, message_id=msg.message_id,
                            text=current + "▫️",
                            business_connection_id=conn_id,
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(0.4)
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=msg.message_id,
                        text=current,
                        business_connection_id=conn_id,
                    )
                except Exception:
                    pass
            except Exception as e:
                logging.error(f"txt: {e}")
            return

        # ---- .price ----
        if cmd == ".price":
            await delete_cmd(message)
            try:
                prices = await fetch_prices()
                await send_confirm(chat_id, prices, conn_id)
            except Exception as e:
                logging.error(f"price: {e}")
                await send_confirm(chat_id, "❌ Не удалось получить курсы", conn_id)
            return

        # ---- .rps ----
        if cmd == ".rps":
            await delete_cmd(message)
            bot_choice = random.choice(list(RPS_WINS.keys()))
            kb = types.InlineKeyboardMarkup(inline_keyboard=[[
                types.InlineKeyboardButton(text="✊ Камень", callback_data=f"rps_камень_{bot_choice}"),
                types.InlineKeyboardButton(text="✌️ Ножницы", callback_data=f"rps_ножницы_{bot_choice}"),
                types.InlineKeyboardButton(text="✋ Бумага", callback_data=f"rps_бумага_{bot_choice}"),
            ]])
            await send_confirm(chat_id, "🎮 <b>Камень-ножницы-бумага</b>\n\n👇 Сделай выбор:", conn_id, reply_markup=kb)
            return

        # ---- .ttt ----
        if cmd == ".ttt":
            await delete_cmd(message)
            ttt_games[chat_id] = {"board": [" "] * 9}
            kb = ttt_board_kb(chat_id)
            await send_confirm(chat_id, "❌ <b>Крестики-нолики</b>\n\n👇 Твой ход:", conn_id, reply_markup=kb)
            return

        # ---- .wordle ----
        if cmd == ".wordle":
            if len(parts) < 2:
                await delete_cmd(message)
                await send_confirm(chat_id, "❌ <code>.wordle слово</code>", conn_id)
                return
            word = parts[1].lower()
            if not word.isalpha() or len(word) < 3:
                await delete_cmd(message)
                await send_confirm(chat_id, "❌ Слово должно быть от 3 букв", conn_id)
                return
            wordle_games[chat_id] = {"word": word, "tries": 5, "history": []}
            await delete_cmd(message)
            await send_confirm(chat_id, wordle_render(wordle_games[chat_id]), conn_id)
            return

        # ---- .ghost ----
        if cmd == ".ghost":
            arg = parts[1].lower() if len(parts) > 1 else ""
            if arg == "on":
                ghost_chats[chat_id] = True
                await delete_cmd(message)
                await send_confirm(chat_id, "👻 <b>Ghost включён</b> — входящие в ЛС", conn_id)
            elif arg == "off":
                ghost_chats.pop(chat_id, None)
                await delete_cmd(message)
                await send_confirm(chat_id, "👻 <b>Ghost выключен</b>", conn_id)
            else:
                await delete_cmd(message)
                await send_confirm(chat_id, "ℹ️ <code>.ghost on/off</code>", conn_id)
            return

        # ---- .story ----
        if cmd == ".story":
            if not message.reply_to_message or not message.reply_to_message.photo:
                await delete_cmd(message)
                await send_confirm(chat_id, "❌ Ответь реплаем на фото", conn_id)
                return
            await delete_cmd(message)
            await send_confirm(chat_id, "⏳ Режу фото на 9 частей...", conn_id, 3)
            photo = message.reply_to_message.photo[-1]
            file_bytes = await download_file(photo.file_id)
            if not file_bytes:
                await send_confirm(chat_id, "❌ Не удалось скачать фото", conn_id)
                return
            parts_img = split_3x3(file_bytes)
            if not parts_img:
                await send_confirm(chat_id, "❌ Ошибка нарезки", conn_id)
                return
            caption = " ".join(parts[1:]) if len(parts) > 1 else ""
            posted = 0
            failed = 0
            last_err = ""
            for idx, piece in enumerate(parts_img):
                try:
                    url = f"https://api.telegram.org/bot{BOT_TOKEN}/postStory"
                    data = {
                        "business_connection_id": conn_id,
                        "active_period": 86400,
                        "post_to_chat_page": "true",
                    }
                    if caption:
                        data["caption"] = caption[:200]
                    files = {
                        "content": (f"part_{idx}.jpg", piece, "image/jpeg"),
                    }
                    async with aiohttp.ClientSession() as session:
                        async with session.post(url, data=data, files=files) as r:
                            res = await r.json()
                            if res.get("ok"):
                                posted += 1
                            else:
                                failed += 1
                                last_err = res.get("description", "")
                                logging.error(f"postStory {idx}: {res}")
                    await asyncio.sleep(0.7)
                except Exception as e:
                    failed += 1
                    last_err = str(e)
                    logging.error(f"postStory {idx}: {e}")
            if posted == 0 and last_err:
                await send_confirm(chat_id, f"❌ Ошибка: <code>{last_err[:150]}</code>", conn_id)
            else:
                await send_confirm(chat_id, f"✅ Выложено: <b>{posted}/9</b>", conn_id)
            return

        # ---- СТАТУСЫ ----
        if cmd == ".text":
            await delete_cmd(message)
            await send_chat_action(chat_id, conn_id, "typing")
            return

        if cmd == ".untext":
            await delete_cmd(message)
            await send_confirm(chat_id, "⌨️ <b>Статус «печатает» снят</b>", conn_id)
            return

        if cmd == ".photo":
            await delete_cmd(message)
            await send_chat_action(chat_id, conn_id, "photo")
            return

        if cmd == ".unphoto":
            await delete_cmd(message)
            await send_confirm(chat_id, "📷 <b>Статус «фото» снят</b>", conn_id)
            return

        if cmd == ".gs":
            await delete_cmd(message)
            await send_chat_action(chat_id, conn_id, "voice")
            return

        if cmd == ".ungs":
            await delete_cmd(message)
            await send_confirm(chat_id, "🎙 <b>Статус «голосовое» снят</b>", conn_id)
            return

        # ---- wordle guess ----
        if chat_id in wordle_games and len(text.split()) == 1 and text.isalpha():
            game = wordle_games[chat_id]
            guess = text.lower()
            if len(guess) != len(game["word"]):
                return
            marks = wordle_marks(game["word"], guess)
            game["history"].append((guess, marks))
            game["tries"] -= 1
            await delete_cmd(message)
            if guess == game["word"]:
                await send_confirm(chat_id, wordle_render(game) + "\n\n🎉 <b>Угадал!</b>", conn_id)
                wordle_games.pop(chat_id, None)
            elif game["tries"] <= 0:
                await send_confirm(chat_id, wordle_render(game) + f"\n\n😢 <b>Не угадал. Слово: {game['word']}</b>", conn_id)
                wordle_games.pop(chat_id, None)
            else:
                await send_confirm(chat_id, wordle_render(game), conn_id)
            return

    except Exception as e:
        logging.error(f"business_msg error: {type(e).__name__}: {e}")


# ================== ОДНОРАЗОВОЕ ФОТО ==================
@dp.business_message(F.reply_to_message)
async def onetime_media(message: types.Message):
    if message.text and message.text.startswith("."):
        return
    replied = message.reply_to_message
    if not replied:
        return
    has_media = bool(replied.photo or replied.video or replied.video_note)
    if not has_media:
        return
    conn_id = message.business_connection_id
    owner_id_of_conn = await get_owner_id(conn_id)
    if not owner_id_of_conn:
        return
    if not message.from_user or message.from_user.id != owner_id_of_conn:
        return
    if not await check_subscription(owner_id_of_conn):
        return
    try:
        await bot.copy_message(
            chat_id=owner_id_of_conn,
            from_chat_id=replied.chat.id,
            message_id=replied.message_id,
        )
        await send_confirm(message.chat.id, "✅ <b>Медиа отправлено в ЛС</b>", conn_id)
    except Exception as e:
        logging.error(f"onetime_media: {e}")


# ================== CALLBACKS: RPS / TTT ==================
@dp.callback_query(F.data.startswith("rps_"))
async def cb_rps(call):
    parts = call.data.split("_")
    if len(parts) != 3:
        await call.answer()
        return
    player = parts[1]
    bot_choice = parts[2]
    result = rps_result(player, bot_choice)
    text = f"✊ Ты: <b>{player}</b>\n🤖 Бот: <b>{bot_choice}</b>\n\n{result}"
    try:
        await call.message.edit_text(text, parse_mode="HTML")
    except Exception:
        pass
    await call.answer()


@dp.callback_query(F.data.startswith("ttt_"))
async def cb_ttt(call):
    try:
        idx = int(call.data.split("_")[1])
    except Exception:
        await call.answer()
        return
    chat_id = call.message.chat.id
    game = ttt_games.get(chat_id)
    if not game:
        await call.answer("Игра не найдена", show_alert=True)
        return
    board = game["board"]
    if board[idx] != " ":
        await call.answer("Занято", show_alert=True)
        return
    board[idx] = "❌"
    winner = ttt_check_winner(board)
    if not winner:
        free = [i for i in range(9) if board[i] == " "]
        if free:
            board[random.choice(free)] = "⭕"
            winner = ttt_check_winner(board)
    kb = ttt_board_kb(chat_id)
    if winner == "❌":
        try:
            await call.message.edit_text("❌ <b>Победа!</b>", parse_mode="HTML")
        except Exception:
            pass
        ttt_games.pop(chat_id, None)
    elif winner == "⭕":
        try:
            await call.message.edit_text("⭕ <b>Бот победил</b>", parse_mode="HTML")
        except Exception:
            pass
        ttt_games.pop(chat_id, None)
    elif winner == "draw":
        try:
            await call.message.edit_text("🤝 <b>Ничья</b>", parse_mode="HTML")
        except Exception:
            pass
        ttt_games.pop(chat_id, None)
    else:
        try:
            await call.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            pass
    await call.answer()


# ================== КОМАНДЫ В ЛИЧКЕ ==================
@dp.message(F.chat.type == "private", F.text.startswith("."))
async def pm_commands(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Только владелец может использовать команды.")
        return

    text = (message.text or "").strip()
    parts = text.split()

    if text == ".help":
        await message.answer(
            "📖 <b>Команды в личке бота:</b>\n\n"
            "<code>.mute @user N</code> — мут на N мин\n"
            "<code>.unmute @user</code> — снять мут\n"
            "<code>.warn @user N</code> — варны\n"
            "<code>.unwarn @user</code> — сбросить\n\n"
            "⚠️ Вместо @user можно ID.",
            parse_mode="HTML")
        return

    if parts[0] == ".mute" and len(parts) >= 3:
        target = parts[1].lstrip("@")
        try:
            m = int(parts[2])
        except ValueError:
            m = 10
        conn_id, chat_id = await find_connection_by_target(target)
        if not conn_id:
            await message.answer(f"❌ Не нашёл <b>{target}</b>", parse_mode="HTML")
            return
        mutes[chat_id] = datetime.now() + timedelta(minutes=m)
        await bot_api("sendMessage", {"chat_id": chat_id, "text": f"🔇 Мут на {m} мин", "business_connection_id": conn_id})
        await message.answer(f"✅ Мут <b>{target}</b> на {m} мин", parse_mode="HTML")
        return

    if parts[0] == ".unmute" and len(parts) >= 2:
        target = parts[1].lstrip("@")
        conn_id, chat_id = await find_connection_by_target(target)
        if not conn_id:
            await message.answer(f"❌ Не нашёл <b>{target}</b>", parse_mode="HTML"); return
        mutes.pop(chat_id, None); warns.pop(chat_id, None)
        await delete_warn_msg(chat_id)
        await bot_api("sendMessage", {"chat_id": chat_id, "text": "🔊 Мут снят", "business_connection_id": conn_id})
        await message.answer(f"✅ Мут снят с <b>{target}</b>", parse_mode="HTML")
        return


# ================== CALLBACKS ==================
@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(call):
    if await check_subscription(call.from_user.id):
        try: await call.message.delete()
        except: pass
        await send_photo_banner(call.message.chat.id, TEXT_MAIN_MENU, reply_markup=main_menu())
    else:
        await call.answer("❌ Ты ещё не подписался!", show_alert=True)


@dp.callback_query(F.data == "back_main")
async def cb_back(call):
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, TEXT_MAIN_MENU, reply_markup=main_menu())


@dp.callback_query(F.data == "cmd_list")
async def cb_cmds(call):
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, TEXT_CMD_LIST, reply_markup=back_kb())


@dp.callback_query(F.data == "sub_menu")
async def cb_sub(call):
    user_id = call.from_user.id
    now = datetime.now()
    current = subscriptions.get(user_id)
    status = "❌ не активна"
    if current and current > now:
        status = f"✅ активна до {current.strftime('%d.%m.%Y')}"
    trial_text = f"🎁 Пробный период — {TRIAL_DAYS} дней\n\n" if user_id not in used_trials else ""
    text = (
        "💎 <b>Подписка</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Статус: <b>{status}</b>\n\n"
        f"{trial_text}"
        "👇 <i>Выбери тариф:</i>"
    )
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, text, reply_markup=plans_kb(user_id))


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
    text = (
        "🎁 <b>Пробный период активирован!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 Дней: <b>{TRIAL_DAYS}</b>\n"
        f"📅 До: <b>{until.strftime('%d.%m.%Y %H:%M')}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, text, reply_markup=back_kb())
    await call.answer("Активировано ✅")


@dp.callback_query(F.data == "ref")
async def cb_ref(call):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{call.from_user.id}"
    invited = len(referrals.get(call.from_user.id, set()))
    text = TEXT_REF.format(link=link, count=invited)
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, text, reply_markup=back_kb())
    await call.answer()


@dp.callback_query(F.data == "howto")
async def cb_howto(call):
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, TEXT_HOWTO, reply_markup=back_kb())
    await call.answer()


@dp.callback_query(F.data.startswith("pay_"))
async def cb_pay(call):
    plan = call.data.split("_")[1]
    p = PRICES[plan]
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{plan}")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="sub_menu")],
    ])
    text = (
        f"💳 <b>Оплата «{p['label']}»</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Сумма: <b>{p['rub']}₽</b>\n"
        f"💳 Карта: <code>{CARD_NUMBER}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "После оплаты нажми «✅ Я оплатил»"
    )
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, text, reply_markup=kb)


@dp.callback_query(F.data.startswith("paid_"))
async def cb_paid(call):
    plan = call.data.split("_")[1]
    pending_payments[call.from_user.id] = {"plan": plan}
    await call.message.answer("📸 <b>Пришли скриншот оплаты.</b>", parse_mode="HTML")


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


# ================== MAIN ==================
async def main():
    await init_db()
    logging.info("✅ БД инициализирована")

    asyncio.create_task(background_name_updater())
    logging.info("✅ Фоновый апдейтер имени запущен")

    threading.Thread(target=run_flask, daemon=True).start()
    logging.info("✅ Flask запущен")

    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("✅ Вебхук сброшен, начинаю polling")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
