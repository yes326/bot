# -*- coding: utf-8 -*-
# AntiSpam Defender Bot — @AntiSpam_Defender_bot
# Python + aiogram 3.15 + aiohttp + aiosqlite + Flask (health + WebApp)

import os, logging, threading, asyncio, aiohttp, time, io, ast, json, operator, random, urllib.parse, aiosqlite, qrcode, hmac, hashlib, sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask, request, jsonify, send_from_directory
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SetMyName
from aiogram.types import (
    BufferedInputFile, WebAppInfo, MenuButtonWebApp,
    LabeledPrice, PreCheckoutQuery,
    BotCommand, BotCommandScopeChat, BotCommandScopeDefault,
)

# ============================================================
# КОНФИГ
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
OWNER_USERNAME = "ysorn"
OWNER_ID = 8502858396
CHANNEL_LINK = "https://t.me/+MV9rTn9A6L1hNGNi"
CHANNEL_ID = -1004412177691
PRICES = {
    "1month":  {"rub": 100,  "stars": 65,  "days": 30,  "label": "1 месяц"},
    "6months": {"rub": 599,  "stars": 390, "days": 180, "label": "6 месяцев"},
    "1year":   {"rub": 1199, "stars": 780, "days": 365, "label": "1 год"},
}
TRIAL_DAYS = 7
WARN_LIMIT = 5
WARN_MUTE_MINUTES = 60
ENV_MAX_SEEN = int(os.environ.get("MAX_SEEN_COUNT", "0"))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://bot-7ifx.onrender.com").rstrip("/")
WEBAPP_URL = f"{RENDER_URL}/webapp"

ZWSP = "\u200b"; ZWNJ = "\u200c"; ZWJ = "\u200d"
INVISIBLES = [ZWSP, ZWNJ, ZWJ]

SIMILAR = {
    'а':'a','е':'e','о':'o','р':'p','с':'c','у':'y','х':'x',
    'А':'A','В':'B','Е':'E','К':'K','М':'M','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X',
    'і':'i','ї':'i','ё':'e','б':'6','з':'3','в':'b','г':'r','д':'d','л':'l','м':'m','н':'n',
    'п':'n','ф':'f','ц':'u','ч':'4','ш':'w','щ':'w','ы':'b','ь':'b','э':'e','ю':'io','я':'ya',
    'Б':'6','З':'3','Г':'R','Д':'D','Л':'L','П':'N','Ф':'F','Ц':'U','Ч':'4','Ш':'W','Щ':'W','Ы':'B','Э':'E','Ю':'IO','Я':'YA',
}

DB_PATH = "bot.db"
NAME_UPDATE_INTERVAL = 86400
CACHE_LIMIT = 200
DEDUP_WINDOW = 5

BANNER_PATH = os.path.join(os.path.dirname(__file__), "angel.jpg")
BANNER_FALLBACK = os.path.join(os.path.dirname(__file__), "IMG_20260918_155302_695.jpg")

def get_banner_path():
    if os.path.exists(BANNER_PATH): return BANNER_PATH
    if os.path.exists(BANNER_FALLBACK): return BANNER_FALLBACK
    return None

# ============================================================
# ГЛОБАЛЬНЫЕ ХРАНИЛИЩА
# ============================================================
business_owners = {}
pending_payments = {}
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
type_styles = {}
user_settings_cache = {}   # кэш настроек: uid -> dict
_monotonic_count = ENV_MAX_SEEN
_last_bio = ""

EIGHTBALL = [
    "🎱 Да, определённо.","🎱 Без сомнений.","🎱 Всё говорит о том, что да.",
    "🎱 Скорее всего, да.","🎱 Знаки говорят — да.","🎱 Пока не ясно, попробуй ещё.",
    "🎱 Спроси позже.","🎱 Лучше не говорить сейчас.","🎱 Не могу предсказать.",
    "🎱 Сконцентрируйся и спроси снова.","🎱 Не рассчитывай на это.","🎱 Мой ответ — нет.",
    "🎱 По моим данным — нет.","🎱 Весьма сомнительно."
]

WCODES = {
    0:"☀️ Ясно",1:"🌤 Преимущественно ясно",2:"⛅ Переменная облачность",3:"☁️ Пасмурно",
    45:"🌫 Туман",48:"🌫 Туман с инеем",51:"🌦 Морось слабая",53:"🌦 Морось",55:"🌧 Морось сильная",
    61:"🌧 Дождь слабый",63:"🌧 Дождь",65:"🌧 Дождь сильный",71:"🌨 Снег слабый",73:"🌨 Снег",
    75:"❄️ Снег сильный",77:"🌨 Снежные зёрна",80:"🌦 Ливень слабый",81:"🌧 Ливень",82:"⛈ Ливень сильный",
    85:"🌨 Снегопад",86:"❄️ Снегопад сильный",95:"⛈ Гроза",96:"⛈ Гроза с градом",99:"⛈ Гроза с сильным градом"
}

TYPE_STYLES = {
    "bold":("<b>","</b>"),"italic":("<i>","</i>"),"underline":("<u>","</u>"),
    "strike":("<s>","</s>"),"code":("<code>","</code>"),"quote":("<blockquote>","</blockquote>"),
    "spoiler":("<tg-spoiler>","</tg-spoiler>")
}

# ============================================================
# БД
# ============================================================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, joined_at TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, until TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS trials (user_id INTEGER PRIMARY KEY, used_at TEXT)")
        await db.execute("""CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            notify_edit INTEGER DEFAULT 1,
            notify_delete INTEGER DEFAULT 1,
            cmd_prefix TEXT DEFAULT '.',
            excluded_chats TEXT DEFAULT '[]',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        await db.commit()
    logging.info("✅ БД инициализирована")

async def register_user(uid, un, fn):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at) VALUES (?,?,?,?)",
            (uid, un, fn, datetime.now().isoformat())
        )
        await db.commit()

async def get_total_users():
    global _monotonic_count
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users"); row = await cur.fetchone()
        count = row[0] if row else 0
        cur = await db.execute("SELECT value FROM meta WHERE key='max_seen_count'"); row = await cur.fetchone()
        saved = int(row[0]) if row and row[0] else 0
        result = max(count, saved, ENV_MAX_SEEN, _monotonic_count)
        if result > saved:
            await db.execute("INSERT OR REPLACE INTO meta (key,value) VALUES ('max_seen_count',?)", (str(result),))
            await db.commit()
        _monotonic_count = result
        return result

async def get_last_users(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users ORDER BY joined_at DESC LIMIT ?", (limit,))
        return await cur.fetchall()

async def get_subscription(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT until FROM subscriptions WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if not row or not row[0]: return None
        try: return datetime.fromisoformat(row[0])
        except: return None

async def set_subscription(user_id, until_dt):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO subscriptions (user_id, until) VALUES (?,?)",
                         (user_id, until_dt.isoformat()))
        await db.commit()

async def has_used_trial(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM trials WHERE user_id=?", (user_id,))
        return (await cur.fetchone()) is not None

async def mark_trial_used(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO trials (user_id, used_at) VALUES (?,?)",
                         (user_id, datetime.now().isoformat()))
        await db.commit()

async def count_active_subs():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM subscriptions WHERE until > ?", (datetime.now().isoformat(),))
        row = await cur.fetchone()
        return row[0] if row else 0

async def count_trials():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM trials")
        row = await cur.fetchone()
        return row[0] if row else 0

# ============================================================
# НАСТРОЙКИ (user_settings)
# ============================================================
async def db_get_settings(uid: int) -> dict:
    """Читает настройки из БД, кэширует."""
    if uid in user_settings_cache:
        return user_settings_cache[uid]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM user_settings WHERE user_id=?", (uid,))
        row = await cur.fetchone()
        if not row:
            await db.execute("INSERT OR IGNORE INTO user_settings(user_id) VALUES(?)", (uid,))
            await db.commit()
            data = {"user_id": uid, "notify_edit": 1, "notify_delete": 1, "cmd_prefix": ".", "excluded_chats": []}
        else:
            try:
                excl = json.loads(row["excluded_chats"] or "[]")
            except Exception:
                excl = []
            data = {
                "user_id": row["user_id"],
                "notify_edit": int(row["notify_edit"]),
                "notify_delete": int(row["notify_delete"]),
                "cmd_prefix": row["cmd_prefix"] or ".",
                "excluded_chats": excl,
            }
    user_settings_cache[uid] = data
    return data

async def db_set_settings(uid: int, **fields):
    """Обновляет поля настроек."""
    if not fields: return
    cols, vals = [], []
    for k, v in fields.items():
        if k == "excluded_chats":
            v = json.dumps(v, ensure_ascii=False)
        cols.append(f"{k}=?")
        vals.append(v)
    vals.append(uid)
    sql = f"UPDATE user_settings SET {', '.join(cols)}, updated_at=CURRENT_TIMESTAMP WHERE user_id=?"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO user_settings(user_id) VALUES(?)", (uid,))
        await db.execute(sql, vals)
        await db.commit()
    # сброс кэша
    user_settings_cache.pop(uid, None)

# ============================================================
# FLASK: health + WebApp
# ============================================================
flask_app = Flask(__name__, static_folder=None)

@flask_app.route('/')
def home():
    return "Bot is running"

@flask_app.route('/webapp')
def webapp_page():
    try:
        return send_from_directory(".", "webapp.html", mimetype="text/html")
    except Exception as e:
        return f"webapp.html not found: {e}", 500

def _validate_init_data(init_data: str):
    """HMAC-SHA256 проверка initData Telegram WebApp."""
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, strict_parsing=True))
    except Exception:
        return None
    if "hash" not in parsed: return None
    received = parsed.pop("hash")
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received): return None
    try:
        if time.time() - int(parsed.get("auth_date", "0")) > 86400: return None
    except Exception:
        return None
    try:
        parsed["user"] = json.loads(parsed.get("user", "{}"))
    except Exception:
        parsed["user"] = {}
    return parsed

@flask_app.route('/api/settings', methods=["GET"])
def api_settings_get():
    parsed = _validate_init_data(request.headers.get("X-Init-Data", ""))
    if not parsed: return jsonify({"ok": False, "error": "unauthorized"}), 401
    uid = parsed["user"].get("id")
    if not uid: return jsonify({"ok": False, "error": "no user"}), 400
    try:
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM user_settings WHERE user_id=?", (uid,))
        row = cur.fetchone()
        if not row:
            conn.execute("INSERT OR IGNORE INTO user_settings(user_id) VALUES(?)", (uid,))
            conn.commit()
            data = {"notify_edit": 1, "notify_delete": 1, "cmd_prefix": ".", "excluded_chats": []}
        else:
            try: excl = json.loads(row["excluded_chats"] or "[]")
            except Exception: excl = []
            data = {
                "notify_edit": int(row["notify_edit"]),
                "notify_delete": int(row["notify_delete"]),
                "cmd_prefix": row["cmd_prefix"] or ".",
                "excluded_chats": excl,
            }
        conn.close()
        return jsonify({"ok": True, "settings": data})
    except Exception as e:
        logging.exception("api_get_settings")
        return jsonify({"ok": False, "error": str(e)}), 500

@flask_app.route('/api/settings', methods=["POST"])
def api_settings_post():
    parsed = _validate_init_data(request.headers.get("X-Init-Data", ""))
    if not parsed: return jsonify({"ok": False, "error": "unauthorized"}), 401
    uid = parsed["user"].get("id")
    if not uid: return jsonify({"ok": False, "error": "no user"}), 400
    payload = request.get_json(silent=True) or {}
    updates = {}
    if "notify_edit" in payload: updates["notify_edit"] = 1 if payload["notify_edit"] else 0
    if "notify_delete" in payload: updates["notify_delete"] = 1 if payload["notify_delete"] else 0
    if "cmd_prefix" in payload:
        p = str(payload["cmd_prefix"]).strip()[:3]
        updates["cmd_prefix"] = p or "."
    if "excluded_chats" in payload and isinstance(payload["excluded_chats"], list):
        updates["excluded_chats"] = [str(x) for x in payload["excluded_chats"]][:200]
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR IGNORE INTO user_settings(user_id) VALUES(?)", (uid,))
        if updates:
            cols, vals = [], []
            for k, v in updates.items():
                if k == "excluded_chats": v = json.dumps(v, ensure_ascii=False)
                cols.append(f"{k}=?")
                vals.append(v)
            vals.append(uid)
            conn.execute(f"UPDATE user_settings SET {', '.join(cols)}, updated_at=CURRENT_TIMESTAMP WHERE user_id=?", vals)
        conn.commit(); conn.close()
        # сброс кэша
        user_settings_cache.pop(uid, None)
        return jsonify({"ok": True})
    except Exception as e:
        logging.exception("api_post_settings")
        return jsonify({"ok": False, "error": str(e)}), 500

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), use_reloader=False)

# ============================================================
# ЛОГИ + БОТ + ДИСПЕТЧЕР
# ============================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ============================================================
# УТИЛИТЫ
# ============================================================
def is_duplicate(cid, uid, txt):
    now = time.time(); key = (cid, uid, (txt or "")[:100])
    last = processed_updates.get(key)
    if last and (now - last) < DEDUP_WINDOW: return True
    processed_updates[key] = now
    if len(processed_updates) > 500:
        for k in [k for k, v in processed_updates.items() if now - v > 60]:
            processed_updates.pop(k, None)
    return False

async def bot_api(method, data):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=data) as r:
                res = await r.json()
                if not res.get("ok"):
                    logging.error(f"bot_api({method}): {res}")
                    return None
                return res
    except Exception as e:
        logging.error(f"bot_api({method}): {e}")
        return None

async def delete_business_msg(cid, mids):
    if not isinstance(mids, list): mids = [mids]
    return await bot_api("deleteBusinessMessages", {"business_connection_id": cid, "message_ids": mids})

async def auto_delete(chat_id, mid, cid, sec=3):
    await asyncio.sleep(sec)
    try:
        deleted_by_bot.add(mid)
        await delete_business_msg(cid, [mid])
    except Exception as e:
        logging.error(f"auto_delete: {e}")

async def delete_cmd(message):
    if not message.business_connection_id: return
    try:
        deleted_by_bot.add(message.message_id)
        await delete_business_msg(message.business_connection_id, [message.message_id])
        logging.info(f"✅ Удалена команда: {(message.text or '')[:30]}")
    except Exception as e:
        logging.error(f"delete_cmd: {e}")

async def send_confirm(cid, text, conn=None, sec=None, kb=None):
    try:
        kw = {"chat_id": cid, "text": text, "parse_mode": "HTML"}
        if conn: kw["business_connection_id"] = conn
        if kb: kw["reply_markup"] = kb
        msg = await bot.send_message(**kw)
        if sec and conn:
            asyncio.create_task(auto_delete(cid, msg.message_id, conn, sec))
        return msg
    except Exception as e:
        logging.error(f"send_confirm: {e}")
        return None

async def send_chat_action(cid, conn, action):
    am = {"typing":"typing","photo":"upload_photo","video":"upload_video","voice":"record_voice","document":"upload_document"}
    return await bot_api("sendChatAction", {"chat_id": cid, "business_connection_id": conn, "action": am.get(action, "typing")})

async def send_photo_banner(cid, caption, conn=None, kb=None, pm="HTML"):
    p = get_banner_path()
    if p:
        try:
            kw = {"chat_id": cid, "photo": types.FSInputFile(p), "caption": caption, "parse_mode": pm}
            if kb: kw["reply_markup"] = kb
            if conn: kw["business_connection_id"] = conn
            return await bot.send_photo(**kw)
        except Exception as e:
            logging.error(f"send_photo_banner: {e}")
    try:
        kw = {"chat_id": cid, "text": caption, "parse_mode": pm}
        if kb: kw["reply_markup"] = kb
        if conn: kw["business_connection_id"] = conn
        return await bot.send_message(**kw)
    except Exception as e:
        logging.error(f"fallback: {e}")
        return None

async def delete_warn_msg(cid):
    old = warn_messages.get(cid); conn = last_conn_by_chat.get(cid)
    if old and conn:
        try: await delete_business_msg(conn, [old])
        except Exception as e: logging.error(f"del warn: {e}")
    warn_messages.pop(cid, None)

def distort(text, level=3):
    if not text: return text
    out = []
    for i, ch in enumerate(text):
        out.append(SIMILAR.get(ch, ch))
        if i % 2 == 0: out.append(INVISIBLES[i % len(INVISIBLES)])
    d = "".join(out)
    return d[:4000] if len(d) > 4000 else d

def cache_message(msg):
    try:
        cid = msg.chat.id
        if cid not in message_cache: message_cache[cid] = {}
        entry = {
            "from_id": msg.from_user.id if msg.from_user else None,
            "from_name": msg.from_user.full_name if msg.from_user else "?",
            "text": msg.text or msg.caption,
            "photo": msg.photo[-1].file_id if msg.photo else None,
            "video": msg.video.file_id if msg.video else None,
            "video_note": msg.video_note.file_id if msg.video_note else None,
            "voice": msg.voice.file_id if msg.voice else None,
            "audio": msg.audio.file_id if msg.audio else None,
            "document": msg.document.file_id if msg.document else None,
            "sticker": msg.sticker.file_id if msg.sticker else None,
            "animation": msg.animation.file_id if msg.animation else None,
            "date": msg.date.isoformat() if msg.date else None,
        }
        message_cache[cid][msg.message_id] = entry
        if len(message_cache[cid]) > CACHE_LIMIT:
            for old in sorted(message_cache[cid].keys())[:-CACHE_LIMIT]:
                message_cache[cid].pop(old, None)
    except Exception as e:
        logging.error(f"cache_message: {e}")

async def get_weather(city):
    try:
        t = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=t) as s:
            async with s.get("https://geocoding-api.open-meteo.com/v1/search",
                             params={"name": city, "count": 1, "language": "ru", "format": "json"}) as r:
                if r.status != 200: return None
                d = await r.json()
                if not d.get("results"): return None
                loc = d["results"][0]; lat, lon = loc["latitude"], loc["longitude"]
                name = loc.get("name", city); country = loc.get("country", "")
            async with s.get("https://api.open-meteo.com/v1/forecast",
                             params={"latitude": lat, "longitude": lon,
                                     "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,apparent_temperature",
                                     "timezone": "auto"}) as r:
                if r.status != 200: return None
                w = await r.json(); c = w.get("current", {})
                return (f"🌍 <b>{name}</b>, {country}\n━━━━━━━━━━━━━━━━━━━━\n"
                        f"{WCODES.get(c.get('weather_code', 0), '🌡')}\n"
                        f"🌡 Температура: <b>{c.get('temperature_2m')}°C</b>\n"
                        f"🤔 Ощущается: <b>{c.get('apparent_temperature')}°C</b>\n"
                        f"💧 Влажность: <b>{c.get('relative_humidity_2m')}%</b>\n"
                        f"💨 Ветер: <b>{c.get('wind_speed_10m')} км/ч</b>\n━━━━━━━━━━━━━━━━━━━━")
    except Exception as e:
        logging.error(f"get_weather: {e}")
        return None

async def translate_text(text, tl="ru"):
    try:
        t = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=t) as s:
            async with s.get("https://translate.googleapis.com/translate_a/single",
                             params={"client": "gtx", "sl": "auto", "tl": tl, "dt": "t", "q": text}) as r:
                if r.status != 200: return None
                d = await r.json()
                if d and isinstance(d, list) and d[0]:
                    tr = "".join(p[0] for p in d[0] if p and p[0])
                    det = d[2] if len(d) > 2 else "auto"
                    return tr, det
                return None
    except Exception as e:
        logging.error(f"translate: {e}")
        return None

async def download_file(fid):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", json={"file_id": fid}) as r:
                d = await r.json()
                if not d.get("ok"): return None
                fp = d["result"]["file_path"]
            async with s.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{fp}") as r:
                return await r.read()
    except Exception as e:
        logging.error(f"download_file: {e}")
        return None

def split_3x3(img_bytes):
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB"); w, h = img.size
        tr = 9/16; cr = w/h
        if cr > tr:
            nw = int(h*tr); left = (w-nw)//2; img = img.crop((left, 0, left+nw, h))
        else:
            nh = int(w/tr); top = (h-nh)//2; img = img.crop((0, top, w, top+nh))
        w, h = img.size; cw = w//3; ch = h//3; parts = []
        for r in range(2, -1, -1):
            for c in range(2, -1, -1):
                box = (c*cw, r*ch, (c+1)*cw, (r+1)*ch)
                p = img.crop(box).resize((1080, 1920), Image.LANCZOS)
                b = io.BytesIO(); p.save(b, format="JPEG", quality=95); parts.append(b.getvalue())
        return parts
    except Exception as e:
        logging.error(f"split_3x3: {e}")
        return []

async def post_story(conn, img_bytes, fname, caption=""):
    try:
        form = aiohttp.FormData()
        form.add_field("business_connection_id", conn)
        form.add_field("active_period", "86400")
        form.add_field("post_to_chat_page", "true")
        if caption: form.add_field("caption", caption[:200])
        form.add_field("content", json.dumps({"type": "photo", "photo": "attach://story_photo"}))
        form.add_field("story_photo", img_bytes, filename=fname, content_type="image/jpeg")
        async with aiohttp.ClientSession() as s:
            async with s.post(f"https://api.telegram.org/bot{BOT_TOKEN}/postStory", data=form) as r:
                res = await r.json()
                if res.get("ok"): return True, ""
                return False, res.get("description", "unknown")
    except Exception as e:
        return False, str(e)

_SAFE_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
             ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
             ast.USub: operator.neg, ast.UAdd: operator.pos, ast.FloorDiv: operator.floordiv}

def _eval(n):
    if isinstance(n, ast.Expression): return _eval(n.body)
    if isinstance(n, ast.Constant):
        if isinstance(n.value, (int, float)): return n.value
        raise ValueError()
    if isinstance(n, ast.BinOp):
        op = _SAFE_OPS.get(type(n.op))
        if not op: raise ValueError()
        return op(_eval(n.left), _eval(n.right))
    if isinstance(n, ast.UnaryOp):
        op = _SAFE_OPS.get(type(n.op))
        if not op: raise ValueError()
        return op(_eval(n.operand))
    raise ValueError()

def calc_expr(e):
    try:
        r = _eval(ast.parse(e, mode="eval"))
        if isinstance(r, float) and (r != r or abs(r) == float("inf")): return None
        return r
    except Exception:
        return None

async def fetch_prices():
    lines = ["💱 <b>Курсы валют к рублю</b>", "━━━━━━━━━━━━━━━━━━━━"]; got = False; usdr = None
    try:
        t = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=t) as s:
            async with s.get("https://www.cbr-xml-daily.ru/daily_json.js") as r:
                if r.status == 200:
                    d = await r.json(); usdr = d["Valute"]["USD"]["Value"]
                    lines += [
                        f"🇺🇸 USD: <b>{usdr:.2f}₽</b>",
                        f"🇪🇺 EUR: <b>{d['Valute']['EUR']['Value']:.2f}₽</b>",
                        f"🇨🇳 CNY: <b>{d['Valute']['CNY']['Value']:.2f}₽</b>",
                    ]; got = True
    except Exception as e:
        logging.error(f"cbr: {e}")
    try:
        t = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=t) as s:
            async with s.get("https://api.coinpaprika.com/v1/tickers/usdt-tether") as r:
                if r.status == 200:
                    d = await r.json(); pu = float(d["quotes"]["USD"]["price"])
                    lines.append(f"💵 USDT: <b>{pu*usdr:.2f}₽</b>" if usdr else f"💵 USDT: <b>${pu:.4f}</b>")
                    got = True
    except Exception as e:
        logging.error(f"usdt: {e}")
    for tid in ("ton-toncoin", "toncoin"):
        try:
            t = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=t) as s:
                async with s.get(f"https://api.coinpaprika.com/v1/tickers/{tid}") as r:
                    if r.status == 200:
                        d = await r.json(); pu = float(d["quotes"]["USD"]["price"])
                        lines.append(f"💎 TON: <b>{pu*usdr:.2f}₽</b>" if usdr else f"💎 TON: <b>${pu:.4f}</b>")
                        got = True; break
        except Exception: pass
    if not got: return "❌ Не удалось получить курсы"
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

# ---- игры ----
RPS_WINS = {"камень": "ножницы", "ножницы": "бумага", "бумага": "камень"}
def rps_res(p, b):
    if p == b: return "🤝 Ничья!"
    if RPS_WINS[p] == b: return "🎉 Ты победил!"
    return "😢 Ты проиграл!"

def ttt_kb(cid):
    g = ttt_games.get(cid)
    if not g: return None
    b = g["board"]; rows = []
    for r in range(3):
        row = []
        for c in range(3):
            i = r*3 + c
            row.append(types.InlineKeyboardButton(text=b[i] if b[i] != " " else "·", callback_data=f"ttt_{i}"))
        rows.append(row)
    return types.InlineKeyboardMarkup(inline_keyboard=rows)

def ttt_w(b):
    for a, c, d in [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]]:
        if b[a] != " " and b[a] == b[c] == b[d]: return b[a]
    return "draw" if " " not in b else None

def wordle_r(g):
    out = ["🎯 <b>Wordle</b>", "━━━━━━━━━━━━━━━━━━━━",
           f"Слово из <b>{len(g['word'])}</b> букв. Попыток: <b>{g['tries']}</b>", ""]
    for guess, marks in g["history"]:
        line = ""
        for i, ch in enumerate(guess):
            line += f"🟩{ch.upper()}" if marks[i] == "G" else f"🟨{ch.upper()}" if marks[i] == "Y" else f"⬜{ch.upper()}"
        out.append(line)
    out += ["", "━━━━━━━━━━━━━━━━━━━━"]
    return "\n".join(out)

def wordle_m(w, g):
    marks = ["B"]*len(w); used = [False]*len(w)
    for i in range(len(w)):
        if g[i] == w[i]: marks[i] = "G"; used[i] = True
    for i in range(len(w)):
        if marks[i] == "G": continue
        for j in range(len(w)):
            if not used[j] and g[i] == w[j]: marks[i] = "Y"; used[j] = True; break
    return "".join(marks)

def pluralize(n):
    s = f"{n:,}".replace(",", " "); m100 = n % 100; m10 = n % 10
    if 11 <= m100 <= 19: w = "пользователей"
    elif m10 == 1: w = "пользователь"
    elif 2 <= m10 <= 4: w = "пользователя"
    else: w = "пользователей"
    return f"{s} {w}"

# ============================================================
# ИМЯ И ОПИСАНИЕ БОТА
# ============================================================
async def update_bot_name():
    try:
        await bot(SetMyName(name="AntiSpam Defender"))
        return True
    except Exception as e:
        err = str(e)
        if "Flood control" in err or "Too Many" in err:
            logging.warning(f"setMyName flood: {err}")
        else:
            logging.error(f"setMyName: {e}")
        return False

async def update_bot_description():
    global _last_bio
    try:
        total = await get_total_users()
        desc = f"🛡 AntiSpam Defender\n━━━━━━━━━━━━━━━━━━━━\n👥 Пользователей: {pluralize(total)}\n\nЗащита от спама, мут, варны и многое другое."
        if len(desc) > 512: desc = desc[:509] + "..."
        if desc == _last_bio: return True
        try:
            await bot.set_my_description(description=desc)
            _last_bio = desc
        except Exception as e1:
            logging.error(f"setMyDescription: {e1}")
            try:
                sh = f"🛡 AntiSpam Defender · {pluralize(total)}"
                if len(sh) > 120: sh = sh[:117] + "..."
                await bot.set_my_short_description(short_description=sh)
            except Exception as e2:
                logging.error(f"setMyShortDescription: {e2}")
        return True
    except Exception as e:
        logging.error(f"update_bot_description: {e}")
        return False

async def background_name_updater():
    await asyncio.sleep(300)
    await update_bot_name()
    await update_bot_description()
    while True:
        await asyncio.sleep(NAME_UPDATE_INTERVAL)
        await update_bot_name()
        await update_bot_description()

# ============================================================
# ПОДПИСКА НА КАНАЛ
# ============================================================
async def check_subscription(uid):
    try:
        m = await bot.get_chat_member(CHANNEL_ID, uid)
        return m.status not in ("left", "kicked")
    except Exception as e:
        logging.error(f"sub check: {e}")
        return False

def subscribe_kb():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📢 Подписаться", url=CHANNEL_LINK)],
        [types.InlineKeyboardButton(text="✅ Проверить", callback_data="check_sub")],
    ])

# ============================================================
# BUSINESS CONNECTION
# ============================================================
async def get_owner_id(conn):
    if not conn: return None
    if conn in business_owners: return business_owners[conn]
    try:
        c = await bot.get_business_connection(business_connection_id=conn)
        business_owners[conn] = c.user.id
        return c.user.id
    except Exception as e:
        logging.error(f"get_owner_id: {e}")
        return None

async def find_connection_by_target(t):
    t = t.strip().lstrip("@").lower()
    if t in username_cache:
        uid = username_cache[t]; conn = last_conn_by_chat.get(uid)
        if conn: return conn, uid
    try:
        tid = int(t); conn = last_conn_by_chat.get(tid)
        if conn: return conn, tid
    except ValueError: pass
    return None, None

# ============================================================
# КЛАВИАТУРЫ И ТЕКСТЫ МЕНЮ
# ============================================================
def main_menu():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📖 Команды", callback_data="cmd_list")],
        [types.InlineKeyboardButton(text="💎 Подписка", callback_data="sub_menu")],
        [types.InlineKeyboardButton(text="👥 Пригласить друга", callback_data="ref_menu")],
        [types.InlineKeyboardButton(text="⚙️ Настройки", web_app=WebAppInfo(url=WEBAPP_URL))],
    ])

def back_kb():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
    ])

def plans_kb(uid=None):
    rows = []
    for k, v in PRICES.items():
        rows.append([types.InlineKeyboardButton(text=f"💎 {v['label']} — {v['stars']}⭐ / {v['rub']}₽",
                                                 callback_data=f"pay_{k}")])
    rows.append([types.InlineKeyboardButton(text="🎁 Пробный период", callback_data="trial")])
    rows.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)

TEXT_MAIN_MENU = ("🏠 <b>Главное меню</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                  "🛡 <b>AntiSpam Defender</b> — защита от спама в бизнес-чатах Telegram.\n\n"
                  "Подключите бота к своему аккаунту и управляйте командами прямо в переписке.")
TEXT_CMD_LIST = ("📖 <b>Команды бота</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                 "<b>Модерация:</b>\n.mute N, .unmute, .warn N, .unwarn\n.spam N текст — рассылка\n\n"
                 "<b>Утилиты:</b>\n.info, .calc/.c, .qr, .dl N текст, .txt текст\n"
                 ".weather Город, .translate текст, .price\n\n"
                 "<b>Стили:</b>\n.type on стиль, .type off\n.text/.untext, .photo/.unphoto, .gs/.ungs\n\n"
                 "<b>Развлечения:</b>\n.rps, .ttt, .wordle слово\n.roll 2d6, .coin, .8ball вопрос\n\n"
                 "<b>Клонирование:</b>\n.clone on/off, .nonmute on/off, .ghost on/off, .story")
TEXT_HOWTO = ("📚 <b>Как подключить</b>\n━━━━━━━━━━━━━━━━━━━━\n"
              "1. Откройте @AntiSpam_Defender_bot\n"
              "2. Настройки → Telegram Business → Чат-боты\n"
              "3. Подключите @AntiSpam_Defender_bot\n"
              "4. Готово! Команды работают прямо в переписке.")
TEXT_REF = ("👥 <b>Пригласить друга</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            "За каждого друга — <b>+3 дня</b> подписки!\n\nВаша ссылка:\n")

# ============================================================
# /start
# ============================================================
@dp.message(F.text == "/start")
async def start_cmd(message: types.Message):
    uid = message.from_user.id
    await register_user(uid, message.from_user.username, message.from_user.full_name)
    total = await get_total_users()
    logging.info(f"👤 /start от {uid} | всего: {total}")

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            rid = int(args[1][4:])
            if rid != uid:
                referrals.setdefault(rid, set()).add(uid)
                now = datetime.now()
                cur = await get_subscription(rid)
                base = max(cur, now) if cur and cur > now else now
                await set_subscription(rid, base + timedelta(days=3))
                try:
                    await bot.send_message(rid, "🎉 По вашей ссылке пришёл друг! +3 дня подписки.")
                except: pass
        except ValueError: pass

    if not await check_subscription(uid):
        await message.answer("⚠️ <b>Подпишись на канал, чтобы пользоваться ботом:</b>",
                             reply_markup=subscribe_kb(), parse_mode="HTML")
        return

    await send_photo_banner(message.chat.id, TEXT_MAIN_MENU, kb=main_menu())

# ============================================================
# /stats (owner)
# ============================================================
@dp.message(F.text == "/stats", F.from_user.id == OWNER_ID)
async def stats_cmd(message: types.Message):
    total = await get_total_users(); with_sub = await count_active_subs(); trials = await count_trials()
    last = await get_last_users(10)
    text = (f"📊 <b>Статистика</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 Всего: <b>{total}</b>\n✅ Активных подписок: <b>{with_sub}</b>\n"
            f"🎁 Триалов: <b>{trials}</b>\n\n<b>Последние:</b>\n")
    for row in last:
        name = row["first_name"] or row["username"] or "—"
        un = f"@{row['username']}" if row["username"] else ""
        text += f"• {name} {un} (<code>{row['user_id']}</code>)\n"
    text += "━━━━━━━━━━━━━━━━━━━━"
    await message.answer(text, parse_mode="HTML")

# ============================================================
# BUSINESS CONNECTION
# ============================================================
@dp.business_connection()
async def on_business_connection(conn: types.BusinessConnection):
    try:
        business_owners[conn.id] = conn.user.id
        if conn.user.username:
            username_cache[(conn.user.username or "").lower()] = conn.user.id
        last_conn_by_chat[conn.user.id] = conn.id
        logging.info(f"🔗 Business connection: {conn.id} | owner: {conn.user.id}")
        # Устанавливаем MenuButton с WebApp для owner'а
        try:
            await bot.set_chat_menu_button(
                chat_id=conn.user.id,
                menu_button=MenuButtonWebApp(text="⚙️ Настройки", web_app=WebAppInfo(url=WEBAPP_URL))
            )
        except Exception as e:
            logging.error(f"set_chat_menu_button: {e}")
    except Exception as e:
        logging.error(f"on_business_connection: {e}")

# ============================================================
# УДАЛЕНИЕ СООБЩЕНИЙ СОБЕСЕДНИКА
# ============================================================
@dp.deleted_business_messages()
async def on_deleted_messages(event: types.BusinessMessagesDeleted):
    try:
        cid = event.chat.id; conn = event.business_connection_id
        owner_id_of_conn = await get_owner_id(conn)
        if not owner_id_of_conn: return

        # ---- уведомления об удалении в ЛС владельцу ----
        settings = await db_get_settings(owner_id_of_conn)
        cached_all = message_cache.get(cid, {})

        for mid in event.message_ids:
            if mid in deleted_by_bot:
                deleted_by_bot.discard(mid); continue
            data = cached_all.get(mid)
            if not data: continue
            # Если владелец хочет получать уведомления об удалении
            if settings["notify_delete"]:
                from_name = data.get("from_name", "—")
                from_id = data.get("from_id")
                preview = (data.get("text") or "[медиа]")[:200]
                try:
                    await bot.send_message(
                        owner_id_of_conn,
                        f"🗑 <b>Удалено сообщение</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                        f"👤 {from_name} <code>{from_id}</code>\n"
                        f"💬 {preview}\n━━━━━━━━━━━━━━━━━━━━"
                    )
                except Exception as e:
                    logging.error(f"notify_delete: {e}")

        # ---- старая логика для mute-удалений ----
        if nonmute_active.get(cid, False):
            return
        cached = cached_all
        if not cached: return
        for mid in event.message_ids:
            if mid in deleted_by_bot:
                deleted_by_bot.discard(mid); continue
            data = cached.get(mid)
            if not data: continue
            txt = (data.get("text") or "")
            if txt.startswith("."): continue
            # тут мог быть форвард владельцу — оставим как было
    except Exception as e:
        logging.error(f"on_deleted_messages: {e}")

# ============================================================
# ИЗМЕНЕНИЕ СООБЩЕНИЙ — уведомление владельцу
# ============================================================
@dp.edited_business_message()
async def on_edited_business_msg(message: types.Message):
    try:
        conn = message.business_connection_id
        if not conn: return
        owner_id_of_conn = await get_owner_id(conn)
        if not owner_id_of_conn: return
        # Обновляем кэш и смотрим, что было
        old = None
        cid = message.chat.id
        if cid in message_cache and message.message_id in message_cache[cid]:
            old = message_cache[cid][message.message_id]
        cache_message(message)

        settings = await db_get_settings(owner_id_of_conn)
        if not settings["notify_edit"]: return

        from_name = message.from_user.full_name if message.from_user else "—"
        from_id = message.from_user.id if message.from_user else "—"
        old_text = (old.get("text") if old else None) or "—"
        new_text = message.text or message.caption or "[медиа]"
        try:
            await bot.send_message(
                owner_id_of_conn,
                f"✏️ <b>Сообщение изменено</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 {from_name} <code>{from_id}</code>\n"
                f"📝 Было: {old_text[:300]}\n"
                f"🆕 Стало: {new_text[:300]}\n━━━━━━━━━━━━━━━━━━━━"
            )
        except Exception as e:
            logging.error(f"notify_edit: {e}")
    except Exception as e:
        logging.error(f"on_edited_business_msg: {e}")

# ============================================================
# ОСНОВНОЙ ОБРАБОТЧИК BUSINESS MESSAGE
# ============================================================
@dp.business_message()
async def business_msg(message: types.Message):
    try:
        text = message.text or ""
        cid = message.chat.id
        conn = message.business_connection_id
        owner_id_of_conn = await get_owner_id(conn)
        if not owner_id_of_conn: return

        if message.from_user and is_duplicate(cid, message.from_user.id, text): return
        cache_message(message)

        if message.from_user:
            last_conn_by_chat[message.from_user.id] = conn
            if message.from_user.username:
                username_cache[message.from_user.username.lower()] = message.from_user.id

        is_incoming = message.from_user and message.from_user.id != owner_id_of_conn
        is_from_owner = message.from_user and message.from_user.id == owner_id_of_conn

        # ---- ИСКЛЮЧЁННЫЕ ЧАТЫ ----
        if is_incoming:
            settings = await db_get_settings(owner_id_of_conn)
            if str(message.from_user.id) in [str(x) for x in settings["excluded_chats"]]:
                logging.info(f"⏭ Исключённый чат: {message.from_user.id}")
                return

        # ---- МУТ ----
        if is_incoming:
            muted = mutes.get(message.from_user.id)
            if muted and datetime.now() < muted:
                try:
                    deleted_by_bot.add(message.message_id)
                    await delete_business_msg(conn, [message.message_id])
                except Exception as e:
                    logging.error(f"mute delete: {e}")
                return

        # ---- GHOST (копия входящих в ЛС) ----
        if ghost_chats.get(cid) and is_incoming:
            try:
                u = message.from_user
                await bot.send_message(owner_id_of_conn,
                                       f"👻 <b>Ghost</b>\n👤 {u.full_name} <code>{u.id}</code>\n💬 {text or '[медиа]'}")
            except Exception as e:
                logging.error(f"ghost: {e}")

        # ---- ECHO ----
        if echo_chats.get(cid) and is_incoming:
            try:
                await bot.send_message(cid, f"👤 {message.from_user.full_name}: {text}",
                                       business_connection_id=conn)
            except Exception as e:
                logging.error(f"echo: {e}")
            return

        # ---- АВТОСТИЛЬ ----
        if is_from_owner and cid in type_styles:
            style = type_styles.get(cid)
            if style and style in TYPE_STYLES:
                o, cl = TYPE_STYLES[style]
                try:
                    deleted_by_bot.add(message.message_id)
                    await delete_business_msg(conn, [message.message_id])
                except Exception as e:
                    logging.error(f"style del: {e}")
                try:
                    await bot.send_message(cid, f"{o}{text}{cl}", parse_mode="HTML",
                                           business_connection_id=conn)
                except Exception as e:
                    logging.error(f"style send: {e}")
                return

        # ---- КОМАНДЫ ----
        if not is_from_owner: return
        # читаем префикс из настроек
        settings = await db_get_settings(owner_id_of_conn)
        prefix = settings.get("cmd_prefix") or "."
        if not text.startswith(prefix): return

        if not await check_subscription(owner_id_of_conn):
            await delete_cmd(message)
            await send_confirm(cid, "⚠️ <b>Нужна активная подписка для использования команд.</b>", conn, sec=5)
            return

        # нормализуем текст: заменяем префикс на точку для удобства парсинга ниже
        parts = text.split()
        cmd = parts[0].lower()
        # команды в коде используют "." — заменяем пользовательский префикс
        if prefix != "." and cmd.startswith(prefix):
            cmd = "." + cmd[len(prefix):]
            parts[0] = cmd

        # ---- .info ----
        if cmd == ".info":
            await delete_cmd(message)
            t = message.reply_to_message.from_user if message.reply_to_message else None
            if not t: return
            un = f"@{t.username}" if t.username else "—"
            pm = "✅" if getattr(t, "is_premium", False) else "❌"
            await send_confirm(
                cid,
                f"ℹ️ <b>Данные собеседника</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Имя: <b>{t.full_name}</b>\n🆔 ID: <code>{t.id}</code>\n"
                f"📛 Username: {un}\n⭐ Premium: {pm}\n━━━━━━━━━━━━━━━━━━━━",
                conn, sec=15
            )
            return

        # ---- .weather ----
        if cmd == ".weather":
            if len(parts) < 2:
                await delete_cmd(message); return
            city = " ".join(parts[1:])
            await delete_cmd(message)
            await send_chat_action(cid, conn, "typing")
            r = await get_weather(city)
            await send_confirm(cid, r if r else "❌ Город не найден", conn, sec=30)
            return

        # ---- .translate ----
        if cmd == ".translate":
            if len(parts) < 2:
                await delete_cmd(message); return
            src = " ".join(parts[1:])
            await delete_cmd(message)
            r = await translate_text(src, "ru")
            if r:
                tr, det = r
                await send_confirm(cid, f"🌐 <b>Перевод</b> ({det} → ru):\n{tr}", conn, sec=30)
            else:
                await send_confirm(cid, "❌ Не удалось перевести", conn, sec=5)
            return

        # ---- .roll ----
        if cmd == ".roll":
            await delete_cmd(message)
            try:
                dice = parts[1] if len(parts) > 1 else "1d6"
                if "d" in dice.lower():
                    n, m = map(int, dice.lower().split("d"))
                else:
                    n, m = 1, int(dice)
            except Exception:
                n, m = 1, 6
            n = min(n, 20); m = min(m, 1000)
            res = [random.randint(1, m) for _ in range(n)]
            total = sum(res)
            await send_confirm(cid, f"🎲 <b>Бросок:</b> {', '.join(map(str, res))}\n"
                                    f"Σ <b>{total}</b>", conn, sec=15)
            return

        # ---- .coin ----
        if cmd == ".coin":
            await delete_cmd(message)
            res = random.choice(["🪙 Орёл", "🪙 Решка"])
            await send_confirm(cid, res, conn, sec=10)
            return

        # ---- .8ball ----
        if cmd == ".8ball":
            await delete_cmd(message)
            if len(parts) < 2:
                await send_confirm(cid, "❓ Задай вопрос после команды", conn, sec=5); return
            await send_confirm(cid, f"❓ <i>{' '.join(parts[1:])}</i>\n\n{random.choice(EIGHTBALL)}",
                               conn, sec=20)
            return

        # ---- .type ----
        if cmd == ".type":
            arg = parts[1].lower() if len(parts) > 1 else ""
            if arg == "off":
                type_styles.pop(cid, None)
                await delete_cmd(message)
                await send_confirm(cid, "🔕 Автостиль отключён", conn, sec=5)
                return
            if arg == "on":
                if len(parts) < 3:
                    await delete_cmd(message)
                    sl = ", ".join(f"<code>{s}</code>" for s in TYPE_STYLES)
                    await send_confirm(cid, f"🎨 Доступные стили: {sl}\nИспользование: .type on bold", conn, sec=15)
                    return
                style = parts[2].lower()
                if style not in TYPE_STYLES:
                    await delete_cmd(message)
                    await send_confirm(cid, "❌ Неизвестный стиль", conn, sec=5); return
                type_styles[cid] = style
                await delete_cmd(message)
                await send_confirm(cid, f"✏️ Стиль <b>{style}</b> включён", conn, sec=5)
                return

        # ---- .mute ----
        if cmd == ".mute":
            try: mins = int(parts[1]) if len(parts) > 1 else 10
            except ValueError: mins = 10
            mins = min(mins, 1440)
            if not message.reply_to_message or not message.reply_to_message.from_user:
                await delete_cmd(message); return
            tid = message.reply_to_message.from_user.id
            if tid == owner_id_of_conn:
                await delete_cmd(message); return
            mutes[tid] = datetime.now() + timedelta(minutes=mins)
            await delete_cmd(message)
            await send_confirm(cid, f"🔇 <b>Мут</b> {mins} мин. для <code>{tid}</code>", conn, sec=10)
            return

        # ---- .unmute ----
        if cmd == ".unmute":
            if not message.reply_to_message or not message.reply_to_message.from_user:
                await delete_cmd(message); return
            tid = message.reply_to_message.from_user.id
            mutes.pop(tid, None)
            await delete_cmd(message)
            await send_confirm(cid, f"🔊 Мут снят с <code>{tid}</code>", conn, sec=10)
            return

        # ---- .warn ----
        if cmd == ".warn":
            try: cnt = int(parts[1]) if len(parts) > 1 else 1
            except ValueError: cnt = 1
            if not message.reply_to_message or not message.reply_to_message.from_user:
                await delete_cmd(message); return
            tid = message.reply_to_message.from_user.id
            if tid == owner_id_of_conn:
                await delete_cmd(message); return
            warns[tid] = warns.get(tid, 0) + cnt
            await delete_cmd(message)
            await send_confirm(cid, f"⚠️ <b>Варн</b> {cnt}. Всего: <b>{warns[tid]}</b>/{WARN_LIMIT}",
                               conn, sec=10)
            if warns[tid] >= WARN_LIMIT:
                mutes[tid] = datetime.now() + timedelta(minutes=WARN_MUTE_MINUTES)
                await send_confirm(cid, f"🔇 <b>Мут</b> {WARN_MUTE_MINUTES} мин. за {WARN_LIMIT} варнов",
                                   conn, sec=15)
                warns[tid] = 0
            return

        # ---- .unwarn ----
        if cmd == ".unwarn":
            if not message.reply_to_message or not message.reply_to_message.from_user:
                await delete_cmd(message); return
            tid = message.reply_to_message.from_user.id
            warns.pop(tid, None)
            await delete_cmd(message)
            await send_confirm(cid, f"✅ Варны сняты с <code>{tid}</code>", conn, sec=10)
            return

        # ---- .spam ----
        if cmd == ".spam":
            if len(parts) < 3:
                await delete_cmd(message); return
            try: cnt = min(int(parts[1]), 30)
            except ValueError: cnt = 1
            st = " ".join(parts[2:])
            await delete_cmd(message)
            for _ in range(cnt):
                try:
                    await bot.send_message(cid, st, business_connection_id=conn)
                except Exception as e:
                    logging.error(f"spam: {e}"); break
                await asyncio.sleep(0.15)
            return

        # ---- .st ----
        if cmd == ".st":
            if len(parts) < 2:
                await delete_cmd(message); return
            s = " ".join(parts[1:])
            await delete_cmd(message)
            try:
                await bot.send_message(cid, f"<b>{s}</b>", parse_mode="HTML",
                                       business_connection_id=conn)
            except Exception as e:
                logging.error(f"st: {e}")
            return

        # ---- .clone ----
        if cmd == ".clone":
            if len(parts) < 2:
                await delete_cmd(message); return
            if parts[1].lower() == "on":
                clone[cid] = True
                await delete_cmd(message)
                await send_confirm(cid, "👥 Клонирование включено", conn, sec=5)
            else:
                clone.pop(cid, None)
                await delete_cmd(message)
                await send_confirm(cid, "👥 Клонирование выключено", conn, sec=5)
            return

        # ---- .nonmute ----
        if cmd == ".nonmute":
            arg = parts[1].lower() if len(parts) > 1 else ""
            if arg == "on":
                nonmute_active[cid] = True
                await delete_cmd(message)
                await send_confirm(cid, "✅ NonMute ON", conn, sec=5)
            elif arg == "off":
                nonmute_active.pop(cid, None)
                await delete_cmd(message)
                await send_confirm(cid, "✅ NonMute OFF", conn, sec=5)
            else:
                await delete_cmd(message)
            return

        # ---- .ghost ----
        if cmd == ".ghost":
            arg = parts[1].lower() if len(parts) > 1 else ""
            if arg == "on":
                ghost_chats[cid] = True
                await delete_cmd(message)
                await send_confirm(cid, "👻 Ghost ON", conn, sec=5)
            elif arg == "off":
                ghost_chats.pop(cid, None)
                await delete_cmd(message)
                await send_confirm(cid, "👻 Ghost OFF", conn, sec=5)
            else:
                await delete_cmd(message)
            return

        # ---- .echo ----
        if cmd == ".echo":
            if len(parts) < 2:
                await delete_cmd(message); return
            if parts[1].lower() == "on":
                echo_chats[cid] = True
                await delete_cmd(message)
                await send_confirm(cid, "🔊 Echo ON", conn, sec=5)
            else:
                echo_chats.pop(cid, None)
                await delete_cmd(message)
                await send_confirm(cid, "🔇 Echo OFF", conn, sec=5)
            return

        # ---- .calc / .c ----
        if cmd in (".calc", ".c"):
            if len(parts) < 2:
                await delete_cmd(message); return
            expr = " ".join(parts[1:])
            await delete_cmd(message)
            if len(expr) > 200:
                await send_confirm(cid, "❌ Слишком длинно", conn, sec=5); return
            r = calc_expr(expr)
            if r is None:
                await send_confirm(cid, "❌ Ошибка в выражении", conn, sec=5)
            else:
                if isinstance(r, float) and r.is_integer(): r = int(r)
                await send_confirm(cid, f"🧮 <b>Калькулятор</b>\n<code>{expr}</code> = <b>{r}</b>",
                                   conn, sec=20)
            return

        # ---- .qr ----
        if cmd == ".qr":
            if len(parts) < 2:
                await delete_cmd(message); return
            qt = " ".join(parts[1:])
            await delete_cmd(message)
            if len(qt) > 1000:
                await send_confirm(cid, "❌ Слишком длинно", conn, sec=5); return
            try:
                img = qrcode.make(qt); buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
                await bot.send_photo(chat_id=cid, photo=BufferedInputFile(buf.read(), filename="qr.png"),
                                     caption=f"📱 <b>QR-код</b>\n<code>{qt[:80]}</code>",
                                     parse_mode="HTML", business_connection_id=conn)
            except Exception as e:
                logging.error(f"QR: {e}")
                await send_confirm(cid, "❌ Не удалось создать QR", conn, sec=5)
            return

        # ---- .dl ----
        if cmd == ".dl":
            if len(parts) < 3:
                await delete_cmd(message); return
            try: sec = min(int(parts[1]), 300)
            except ValueError: sec = 5
            dt = " ".join(parts[2:])
            await delete_cmd(message)
            try:
                msg = await bot.send_message(cid, dt, business_connection_id=conn)
                asyncio.create_task(auto_delete(cid, msg.message_id, conn, sec))
            except Exception as e:
                logging.error(f"dl: {e}")
            return

        # ---- .txt ----
        if cmd == ".txt":
            if len(parts) < 2:
                await delete_cmd(message); return
            src = " ".join(parts[1:])
            await delete_cmd(message)
            try:
                msg = await bot.send_message(cid, "▌", business_connection_id=conn)
                cur = ""
                for ch in src[:80]:
                    cur += ch
                    try:
                        await bot.edit_message_text(chat_id=cid, message_id=msg.message_id, text=cur + "▌",
                                                    business_connection_id=conn)
                    except Exception: pass
                    await asyncio.sleep(0.4)
                try:
                    await bot.edit_message_text(chat_id=cid, message_id=msg.message_id, text=cur,
                                                business_connection_id=conn)
                except Exception: pass
            except Exception as e:
                logging.error(f"txt: {e}")
            return

        # ---- .price ----
        if cmd == ".price":
            await delete_cmd(message)
            try:
                p = await fetch_prices()
                await send_confirm(cid, p, conn, sec=60)
            except Exception as e:
                logging.error(f"price: {e}")
            return

        # ---- .rps ----
        if cmd == ".rps":
            await delete_cmd(message)
            bc = types.InlineKeyboardMarkup(inline_keyboard=[[
                types.InlineKeyboardButton(text="🪨 Камень", callback_data="rps_rock"),
                types.InlineKeyboardButton(text="✂️ Ножницы", callback_data="rps_scissors"),
                types.InlineKeyboardButton(text="📄 Бумага", callback_data="rps_paper"),
            ]])
            await send_confirm(cid, "🎮 <b>Камень-Ножницы-Бумага</b>\nВыбери:", conn, kb=bc)
            return

        # ---- .ttt ----
        if cmd == ".ttt":
            await delete_cmd(message)
            ttt_games[cid] = {"board": [" "]*9}
            await send_confirm(cid, "❌ <b>Крестики-нолики</b>\nТвой ход:",
                               conn, kb=ttt_kb(cid))
            return

        # ---- .wordle ----
        if cmd == ".wordle":
            if len(parts) < 2:
                await delete_cmd(message); return
            w = parts[1].lower()
            if not w.isalpha() or len(w) < 3 or len(w) > 15:
                await delete_cmd(message)
                await send_confirm(cid, "❌ Слово: только буквы, 3-15 символов", conn, sec=5)
                return
            wordle_games[cid] = {"word": w, "tries": 6, "history": []}
            await delete_cmd(message)
            await send_confirm(cid, wordle_r(wordle_games[cid]), conn)
            return

        # ---- .story ----
        if cmd == ".story":
            if not message.reply_to_message or not message.reply_to_message.photo:
                await delete_cmd(message)
                await send_confirm(cid, "❌ Ответь на фото командой .story", conn, sec=5)
                return
            await delete_cmd(message)
            photo = message.reply_to_message.photo[-1]
            fb = await download_file(photo.file_id)
            if not fb:
                await send_confirm(cid, "❌ Не удалось скачать фото", conn, sec=5); return
            pieces = split_3x3(fb)
            if not pieces:
                await send_confirm(cid, "❌ Не удалось нарезать", conn, sec=5); return
            caption = " ".join(parts[1:]) if len(parts) > 1 else ""
            posted = 0; last_err = ""
            for i, piece in enumerate(pieces):
                ok, err = await post_story(conn, piece, f"piece_{i}.jpg", caption)
                if ok: posted += 1
                else: last_err = err; logging.error(f"story: {err}")
                await asyncio.sleep(0.7)
            if posted == 0 and last_err:
                await send_confirm(cid, f"❌ Ошибка story: {last_err}", conn, sec=10)
            else:
                await send_confirm(cid, f"✅ Опубликовано {posted}/9 частей в историю", conn, sec=10)
            return

        # ---- .text/.untext, .photo/.unphoto, .gs/.ungs ----
        if cmd == ".text":
            await delete_cmd(message)
            await send_confirm(cid, "📝 Text-режим ON (заглушка)", conn, sec=5)
            return
        if cmd == ".untext":
            await delete_cmd(message)
            await send_confirm(cid, "📝 Text-режим OFF", conn, sec=5)
            return
        if cmd == ".photo":
            await delete_cmd(message)
            await send_confirm(cid, "📷 Photo-режим ON (заглушка)", conn, sec=5)
            return
        if cmd == ".unphoto":
            await delete_cmd(message)
            await send_confirm(cid, "📷 Photo-режим OFF", conn, sec=5)
            return
        if cmd == ".gs":
            await delete_cmd(message)
            await send_confirm(cid, "🎭 GS ON (заглушка)", conn, sec=5)
            return
        if cmd == ".ungs":
            await delete_cmd(message)
            await send_confirm(cid, "🎭 GS OFF", conn, sec=5)
            return

        # ---- Wordle guess (если игра активна) ----
        if cid in wordle_games and len(text.strip()) == len(wordle_games[cid]["word"]):
            g = wordle_games[cid]; guess = text.strip().lower()
            try:
                if len(guess) != len(g["word"]):
                    return
                m = wordle_m(g["word"], guess)
                g["history"].append((guess, m)); g["tries"] -= 1
                await delete_cmd(message)
                if guess == g["word"]:
                    await send_confirm(cid, f"🎉 Угадал! Слово: <b>{g['word']}</b>", conn)
                    wordle_games.pop(cid, None)
                elif g["tries"] <= 0:
                    await send_confirm(cid, f"❌ Попытки кончились. Было: <b>{g['word']}</b>", conn)
                    wordle_games.pop(cid, None)
                else:
                    await send_confirm(cid, wordle_r(g), conn)
            except Exception as e:
                logging.error(f"wordle guess: {e}")
            return
    except Exception as e:
        logging.error(f"business_msg: {e}")

# ============================================================
# ОДНОРАЗОВОЕ ФОТО
# ============================================================
@dp.business_message(F.reply_to_message)
async def onetime_media(message: types.Message):
    if message.text and message.text.startswith("."):
        return
    rep = message.reply_to_message
    if not rep: return
    if not (rep.photo or rep.video or rep.video_note or rep.voice or rep.document):
        return
    conn = message.business_connection_id; oid = await get_owner_id(conn)
    if not oid: return
    if not message.from_user or message.from_user.id != oid: return
    if not await check_subscription(oid): return
    try:
        await bot.copy_message(chat_id=oid, from_chat_id=rep.chat.id, message_id=rep.message_id)
        await send_confirm(message.chat.id, "📩 Отправлено в ЛС", conn, sec=3)
    except Exception as e:
        logging.error(f"onetime: {e}")

# ============================================================
# CALLBACK: RPS / TTT
# ============================================================
@dp.callback_query(F.data.startswith("rps_"))
async def cb_rps(call: types.CallbackQuery):
    p = call.data.split("_")
    if len(p) != 2: await call.answer(); return
    player = {"rock": "камень", "scissors": "ножницы", "paper": "бумага"}.get(p[1], "камень")
    bot_choice = random.choice(["камень", "ножницы", "бумага"])
    res = rps_res(player, bot_choice)
    try:
        await call.message.edit_text(
            f"🎮 Ты: <b>{player}</b>\n🤖 Бот: <b>{bot_choice}</b>\n\n{res}",
            parse_mode="HTML"
        )
    except Exception: pass
    await call.answer()

@dp.callback_query(F.data.startswith("ttt_"))
async def cb_ttt(call: types.CallbackQuery):
    try: idx = int(call.data.split("_")[1])
    except: await call.answer(); return
    cid = call.message.chat.id; g = ttt_games.get(cid)
    if not g: await call.answer("Не найдено", show_alert=True); return
    b = g["board"]
    if b[idx] != " ": await call.answer("Занято"); return
    b[idx] = "❌"; w = ttt_w(b)
    if not w:
        free = [i for i in range(9) if b[i] == " "]
        if free: b[random.choice(free)] = "⭕"
        w = ttt_w(b)
    kb = ttt_kb(cid)
    if w == "❌":
        await call.message.edit_text("🏆 Ты победил!", reply_markup=None)
        ttt_games.pop(cid, None)
    elif w == "⭕":
        await call.message.edit_text("🤖 Бот победил!", reply_markup=None)
        ttt_games.pop(cid, None)
    elif w == "draw":
        await call.message.edit_text("🤝 Ничья!", reply_markup=None)
        ttt_games.pop(cid, None)
    else:
        await call.message.edit_reply_markup(reply_markup=kb)
    await call.answer()

# ============================================================
# CALLBACK: подписка / меню / оплата
# ============================================================
@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(call: types.CallbackQuery):
    if await check_subscription(call.from_user.id):
        try: await call.message.delete()
        except: pass
        await send_photo_banner(call.message.chat.id, TEXT_MAIN_MENU, kb=main_menu())
    else:
        await call.answer("❌ Ты ещё не подписан", show_alert=True)

@dp.callback_query(F.data == "cmd_list")
async def cb_cmds(call: types.CallbackQuery):
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, TEXT_CMD_LIST, kb=back_kb())

@dp.callback_query(F.data == "ref_menu")
async def cb_ref(call: types.CallbackQuery):
    try: await call.message.delete()
    except: pass
    link = f"https://t.me/AntiSpam_Defender_bot?start=ref_{call.from_user.id}"
    await send_photo_banner(call.message.chat.id, TEXT_REF + f"<code>{link}</code>", kb=back_kb())

@dp.callback_query(F.data == "back")
async def cb_back(call: types.CallbackQuery):
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, TEXT_MAIN_MENU, kb=main_menu())

@dp.callback_query(F.data == "sub_menu")
async def cb_sub(call: types.CallbackQuery):
    uid = call.from_user.id; now = datetime.now()
    cur = await get_subscription(uid)
    status = "❌ Не активна"
    if cur and cur > now: status = f"✅ Активна до {cur.strftime('%d.%m.%Y')}"
    used = await has_used_trial(uid)
    trial = f"🎁 Пробный период — {TRIAL_DAYS} дней" if not used else "🎁 Пробный период использован"
    text = (f"💎 <b>Подписка</b>\n━━━━━━━━━━━━━━━━━━━━\nСтатус: {status}\n{trial}\n\n"
            "Выбери тариф:")
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, text, kb=plans_kb(uid))

@dp.callback_query(F.data == "trial")
async def cb_trial(call: types.CallbackQuery):
    uid = call.from_user.id; now = datetime.now()
    if await has_used_trial(uid):
        await call.answer("❌ Триал уже использован", show_alert=True); return
    cur = await get_subscription(uid)
    if cur and cur > now:
        await call.answer("❌ У вас уже есть подписка", show_alert=True); return
    await mark_trial_used(uid)
    until = now + timedelta(days=TRIAL_DAYS)
    await set_subscription(uid, until)
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id,
                            f"🎉 <b>Пробный период активирован!</b>\nДо {until.strftime('%d.%m.%Y')}",
                            kb=back_kb())

@dp.callback_query(F.data.startswith("pay_"))
async def cb_pay(call: types.CallbackQuery):
    plan = call.data.split("_", 1)[1]
    p = PRICES.get(plan)
    if not p: await call.answer("❌"); return
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"⭐ Оплатить {p['stars']} звёзд", callback_data=f"stars_{plan}")],
        [types.InlineKeyboardButton(text="💳 Оплатить картой", url=f"https://t.me/{OWNER_USERNAME}")],
        [types.InlineKeyboardButton(text="✅ Я оплатил(а) картой", callback_data=f"paid_{plan}")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="sub_menu")],
    ])
    text = (f"💳 <b>Оплата «{p['label']}»</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 Тариф: <b>{p['label']}</b>\n"
            f"💰 Сумма: <b>{p['rub']}₽</b> / <b>{p['stars']}⭐</b>\n"
            f"💱 Валюта: RUB / XTR\n━━━━━━━━━━━━━━━━━━━━\n"
            "⭐ <b>Оплатить звёздами</b> — быстро\n"
            "💳 <b>Оплатить картой</b> — напиши @ysorn\n"
            "<i>После оплаты картой нажми «✅ Я оплатил(а)».</i>")
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, text, kb=kb)

@dp.callback_query(F.data.startswith("stars_"))
async def cb_stars(call: types.CallbackQuery):
    plan = call.data.split("_", 1)[1]
    if plan not in PRICES: await call.answer("❌"); return
    p = PRICES[plan]
    try:
        await bot.send_invoice(
            chat_id=call.message.chat.id,
            title=f"AntiSpam Defender — {p['label']}",
            description=f"Подписка на {p['label']}",
            payload=plan,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=p["label"], amount=p["stars"])],
        )
        await call.answer("⭐ Открываю окно оплаты")
    except Exception as e:
        logging.error(f"send_invoice: {type(e).__name__}: {e}")
        await call.answer("❌ Ошибка. Попробуй позже.", show_alert=True)

@dp.callback_query(F.data.startswith("paid_"))
async def cb_paid(call: types.CallbackQuery):
    plan = call.data.split("_", 1)[1]
    pending_payments[call.from_user.id] = {"plan": plan, "at": time.time()}
    await call.message.answer("📸 <b>Пришли скриншот оплаты в этот чат.</b>\nОн будет отправлен владельцу на проверку.")

@dp.message(F.photo)
async def on_screenshot(message: types.Message):
    uid = message.from_user.id
    if uid not in pending_payments: return
    plan = pending_payments[uid].get("plan", "?")
    if plan not in PRICES: return
    p = PRICES[plan]
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"approve_{uid}_{plan}"),
        types.InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{uid}"),
    ]])
    try:
        await bot.send_photo(chat_id=OWNER_ID, photo=message.photo[-1].file_id,
                             caption=f"💰 <b>Оплата</b>\n\n👤 @{message.from_user.username or '—'} (<code>{uid}</code>)\n"
                                     f"📦 Тариф: <b>{p['label']}</b> — {p['rub']}₽",
                             parse_mode="HTML", reply_markup=kb)
        await message.answer("✅ Отправлено! Ждите подтверждения.")
    except Exception as e:
        logging.error(f"screenshot: {e}")

@dp.callback_query(F.data.startswith("approve_"))
async def cb_approve(call: types.CallbackQuery):
    if call.from_user.id != OWNER_ID: await call.answer("❌"); return
    p = call.data.split("_"); uid = int(p[1]); plan = p[2] if len(p) > 2 else "1month"
    if plan not in PRICES: plan = "1month"
    days = PRICES[plan]["days"]; now = datetime.now()
    cur = await get_subscription(uid) or now
    until = max(cur, now) + timedelta(days=days)
    await set_subscription(uid, until)
    try: await bot.send_message(uid, f"✅ Оплата подтверждена! Подписка до {until.strftime('%d.%m.%Y')}")
    except: pass
    try: await call.message.edit_caption(caption=f"✅ Подтверждено: <code>{uid}</code>")
    except: pass
    await call.answer("✅")

@dp.callback_query(F.data.startswith("reject_"))
async def cb_reject(call: types.CallbackQuery):
    if call.from_user.id != OWNER_ID: await call.answer("❌"); return
    uid = int(call.data.split("_")[1])
    try: await bot.send_message(uid, "❌ Оплата не подтверждена. Свяжитесь с @ysorn.")
    except: pass
    try: await call.message.edit_caption(caption=f"❌ Отклонено: <code>{uid}</code>")
    except: pass
    await call.answer("❌")

# ============================================================
# ПРЕДОПЛАТА ЗВЁЗДАМИ
# ============================================================
@dp.pre_checkout_query()
async def pre_checkout_handler(pcq: PreCheckoutQuery):
    try:
        await pcq.answer(ok=True)
        logging.info(f"⭐ Pre-checkout: user={pcq.from_user.id} payload={pcq.invoice_payload}")
    except Exception as e:
        logging.error(f"pre_checkout: {e}")
        try: await pcq.answer(ok=False, error_message="Ошибка, попробуйте позже")
        except: pass

@dp.message(F.successful_payment)
async def on_successful_payment(message: types.Message):
    try:
        pay = message.successful_payment
        uid = message.from_user.id
        plan = pay.invoice_payload
        if plan not in PRICES:
            logging.error(f"⭐ Неизвестный план: {plan}"); return
        days = PRICES[plan]["days"]; stars = PRICES[plan]["stars"]
        now = datetime.now()
        cur = await get_subscription(uid) or now
        until = max(cur, now) + timedelta(days=days)
        await set_subscription(uid, until)
        logging.info(f"⭐ Оплата: user={uid} plan={plan} stars={stars}")
        await message.answer(
            f"✅ <b>Оплата получена!</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"⭐ Звёзд: <b>{stars}</b>\n📦 Тариф: <b>{PRICES[plan]['label']}</b>\n"
            f"💎 Дней: <b>{days}</b>\n📅 Подписка до: <b>{until.strftime('%d.%m.%Y')}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\nСпасибо! 🎉"
        )
        try:
            await bot.send_message(OWNER_ID,
                                   f"💰 <b>Новая оплата звёздами</b>\n"
                                   f"👤 @{message.from_user.username or '—'} (<code>{uid}</code>)\n"
                                   f"⭐ Звёзд: <b>{stars}</b>\n📦 Тариф: <b>{plan}</b>")
        except: pass
    except Exception as e:
        logging.error(f"successful_payment: {e}")

# ============================================================
# ЛС КОМАНДЫ (только owner)
# ============================================================
@dp.message(F.chat.type == "private", F.text.startswith("."), F.from_user.id == OWNER_ID)
async def pm_commands(message: types.Message):
    parts = (message.text or "").strip().split()
    if not parts: return
    if parts[0] == ".help":
        await message.answer("📖 <code>.mute @user N</code>, <code>.unmute @user</code>")
    if parts[0] == ".mute" and len(parts) >= 2:
        t = parts[1].lstrip("@")
        try: m = int(parts[2])
        except (ValueError, IndexError): m = 10
        conn, cid = await find_connection_by_target(t)
        if not conn: await message.answer(f"❌ Не найден {t}"); return
        mutes[cid] = datetime.now() + timedelta(minutes=m)
        await message.answer(f"✅ Мут {t} на {m} мин")
    if parts[0] == ".unmute" and len(parts) >= 2:
        t = parts[1].lstrip("@")
        conn, cid = await find_connection_by_target(t)
        if not conn: await message.answer(f"❌ Не найден {t}"); return
        mutes.pop(cid, None); warns.pop(cid, None)
        await message.answer(f"✅ Размучен {t}")

# ============================================================
# ФОРВАРД ЛС ВЛАДЕЛЬЦУ
# ============================================================
@dp.message(F.chat.type == "private", ~F.text.startswith("."))
async def forward_to_owner(message: types.Message):
    if message.from_user.id == OWNER_ID: return
    if message.text and message.text.startswith("/"): return
    try:
        text = message.text or "[медиа]"
        u = message.from_user
        await bot.send_message(OWNER_ID, f"📨 От {u.full_name} (@{u.username or '—'}):\n{text}")
    except Exception as e:
        logging.error(f"forward: {e}")

# ============================================================
# MAIN
# ============================================================
async def main():
    await init_db()
    logging.info("✅ БД инициализирована, стартую...")

    asyncio.create_task(background_name_updater())
    threading.Thread(target=run_flask, daemon=True).start()
    logging.info(f"🌐 Flask на порту {os.environ.get('PORT', 10000)} | WebApp: {WEBAPP_URL}")

    # MenuButton для owner'а (WebApp)
    try:
        await bot.set_chat_menu_button(
            chat_id=OWNER_ID,
            menu_button=MenuButtonWebApp(text="⚙️ Настройки", web_app=WebAppInfo(url=WEBAPP_URL))
        )
        logging.info("✅ MenuButton установлен")
    except Exception as e:
        logging.error(f"set_chat_menu_button: {e}")

    # Команды в меню бота
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Главное меню"),
        ])
    except Exception as e:
        logging.error(f"set_my_commands: {e}")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
