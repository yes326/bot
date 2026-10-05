# -*- coding: utf-8 -*-
import os, logging, threading, asyncio, aiohttp, time, io, ast, json, operator, random, urllib.parse, aiosqlite, qrcode
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SetMyName
from aiogram.types import BufferedInputFile

BOT_TOKEN = os.environ.get("BOT_TOKEN")
OWNER_USERNAME = "ysorn"
OWNER_ID = 8502858396
CHANNEL_LINK = "https://t.me/+MV9rTn9A6L1hNGNi"
CHANNEL_ID = -1004412177691
PRICES = {"1month": {"rub": 100, "days": 30, "label": "1 месяц"},
          "6months": {"rub": 599, "days": 180, "label": "6 месяцев"},
          "1year": {"rub": 1199, "days": 365, "label": "1 год"}}
TRIAL_DAYS = 7; WARN_LIMIT = 5; WARN_MUTE_MINUTES = 60
ENV_MAX_SEEN = int(os.environ.get("MAX_SEEN_COUNT", "0"))
ZWSP = "\u200b"; ZWNJ = "\u200c"; ZWJ = "\u200d"; INVISIBLES = [ZWSP, ZWNJ, ZWJ]
SIMILAR = {'а':'a','е':'e','о':'o','р':'p','с':'c','у':'y','х':'x','А':'A','В':'B','Е':'E','К':'K','М':'M','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','і':'i','ї':'i','ё':'e','б':'6','з':'3','в':'b','г':'r','д':'d','л':'l','м':'m','н':'n','п':'n','ф':'f','ц':'u','ч':'4','ш':'w','щ':'w','ы':'b','ь':'b','э':'e','ю':'io','я':'ya','Б':'6','З':'3','Г':'R','Д':'D','Л':'L','П':'N','Ф':'F','Ц':'U','Ч':'4','Ш':'W','Щ':'W','Ы':'B','Э':'E','Ю':'IO','Я':'YA'}
DB_PATH = "bot.db"; NAME_UPDATE_INTERVAL = 86400; CACHE_LIMIT = 200; DEDUP_WINDOW = 5
BANNER_PATH = os.path.join(os.path.dirname(__file__), "angel.jpg")
BANNER_FALLBACK = os.path.join(os.path.dirname(__file__), "IMG_20260918_155302_695.jpg")

def get_banner_path():
    if os.path.exists(BANNER_PATH): return BANNER_PATH
    if os.path.exists(BANNER_FALLBACK): return BANNER_FALLBACK
    return None

business_owners = {}; pending_payments = {}
message_cache = {}; warns = {}; mutes = {}; clone = {}; warn_messages = {}
referrals = {}; username_cache = {}; last_conn_by_chat = {}; nonmute_active = {}
bot_rate = defaultdict(list); echo_chats = {}; ghost_chats = {}
rps_games = {}; ttt_games = {}; wordle_games = {}
processed_updates = {}; deleted_by_bot = set(); type_styles = {}
_monotonic_count = ENV_MAX_SEEN; _last_bio = ""

EIGHTBALL = ["🎱 Да, определённо.","🎱 Без сомнений.","🎱 Всё говорит о том, что да.","🎱 Скорее всего, да.","🎱 Знаки говорят — да.","🎱 Пока не ясно, попробуй ещё.","🎱 Спроси позже.","🎱 Лучше не говорить сейчас.","🎱 Не могу предсказать.","🎱 Сконцентрируйся и спроси снова.","🎱 Не рассчитывай на это.","🎱 Мой ответ — нет.","🎱 По моим данным — нет.","🎱 Весьма сомнительно."]
WCODES = {0:"☀️ Ясно",1:"🌤 Преимущественно ясно",2:"⛅ Переменная облачность",3:"☁️ Пасмурно",45:"🌫 Туман",48:"🌫 Туман с инеем",51:"🌦 Морось слабая",53:"🌦 Морось",55:"🌧 Морось сильная",61:"🌧 Дождь слабый",63:"🌧 Дождь",65:"🌧 Дождь сильный",71:"🌨 Снег слабый",73:"🌨 Снег",75:"❄️ Снег сильный",77:"🌨 Снежные зёрна",80:"🌦 Ливень слабый",81:"🌧 Ливень",82:"⛈ Ливень сильный",85:"🌨 Снегопад",86:"❄️ Снегопад сильный",95:"⛈ Гроза",96:"⛈ Гроза с градом",99:"⛈ Гроза с сильным градом"}
TYPE_STYLES = {"bold":("<b>","</b>"),"italic":("<i>","</i>"),"underline":("<u>","</u>"),"strike":("<s>","</s>"),"code":("<code>","</code>"),"quote":("<blockquote>","</blockquote>"),"spoiler":("<tg-spoiler>","</tg-spoiler>")}

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, joined_at TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, until TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS trials (user_id INTEGER PRIMARY KEY, used_at TEXT)")
        await db.commit()

async def register_user(uid, un, fn):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at) VALUES (?,?,?,?)", (uid, un, fn, datetime.now().isoformat()))
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
        await db.execute("INSERT OR REPLACE INTO subscriptions (user_id, until) VALUES (?,?)", (user_id, until_dt.isoformat()))
        await db.commit()

async def has_used_trial(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM trials WHERE user_id=?", (user_id,))
        return (await cur.fetchone()) is not None

async def mark_trial_used(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO trials (user_id, used_at) VALUES (?,?)", (user_id, datetime.now().isoformat()))
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

flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "Bot is running"
def run_flask(): flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), use_reloader=False)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
bot = Bot(token=BOT_TOKEN); dp = Dispatcher(storage=MemoryStorage())

def is_duplicate(cid, uid, txt):
    now = time.time(); key = (cid, uid, (txt or "")[:100])
    last = processed_updates.get(key)
    if last and (now - last) < DEDUP_WINDOW: return True
    processed_updates[key] = now
    if len(processed_updates) > 500:
        for k in [k for k,v in processed_updates.items() if now - v > 60]: processed_updates.pop(k, None)
    return False

async def bot_api(method, data):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=data) as r:
                res = await r.json()
                if not res.get("ok"): logging.error(f"bot_api({method}): {res}"); return None
                return res
    except Exception as e: logging.error(f"bot_api({method}): {e}"); return None

async def delete_business_msg(cid, mids):
    if not isinstance(mids, list): mids = [mids]
    return await bot_api("deleteBusinessMessages", {"business_connection_id": cid, "message_ids": mids})

async def auto_delete(chat_id, mid, cid, sec=3):
    await asyncio.sleep(sec)
    try: deleted_by_bot.add(mid); await delete_business_msg(cid, [mid])
    except Exception as e: logging.error(f"auto_delete: {e}")

async def delete_cmd(message):
    if not message.business_connection_id: return
    try:
        deleted_by_bot.add(message.message_id)
        await delete_business_msg(message.business_connection_id, [message.message_id])
        logging.info(f"✅ Удалена команда: {(message.text or '')[:30]}")
    except Exception as e: logging.error(f"delete_cmd: {e}")

async def send_confirm(cid, text, conn, sec=None, kb=None):
    try:
        kw = {"chat_id": cid, "text": text, "business_connection_id": conn, "parse_mode": "HTML"}
        if kb: kw["reply_markup"] = kb
        msg = await bot.send_message(**kw)
        if sec: asyncio.create_task(auto_delete(cid, msg.message_id, conn, sec))
        return msg
    except Exception as e: logging.error(f"send_confirm: {e}"); return None

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
        except Exception as e: logging.error(f"send_photo_banner: {e}")
    try:
        kw = {"chat_id": cid, "text": caption, "parse_mode": pm}
        if kb: kw["reply_markup"] = kb
        if conn: kw["business_connection_id"] = conn
        return await bot.send_message(**kw)
    except Exception as e: logging.error(f"fallback: {e}"); return None

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
        entry = {"from_id": msg.from_user.id if msg.from_user else None, "from_name": msg.from_user.full_name if msg.from_user else "?", "text": msg.text or msg.caption, "photo": msg.photo[-1].file_id if msg.photo else None, "video": msg.video.file_id if msg.video else None, "video_note": msg.video_note.file_id if msg.video_note else None, "voice": msg.voice.file_id if msg.voice else None, "audio": msg.audio.file_id if msg.audio else None, "document": msg.document.file_id if msg.document else None, "sticker": msg.sticker.file_id if msg.sticker else None, "animation": msg.animation.file_id if msg.animation else None, "date": msg.date.isoformat() if msg.date else None}
        message_cache[cid][msg.message_id] = entry
        if len(message_cache[cid]) > CACHE_LIMIT:
            for old in sorted(message_cache[cid].keys())[:-CACHE_LIMIT]: message_cache[cid].pop(old, None)
    except Exception as e: logging.error(f"cache_message: {e}")

async def get_weather(city):
    try:
        t = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=t) as s:
            async with s.get("https://geocoding-api.open-meteo.com/v1/search", params={"name":city,"count":1,"language":"ru","format":"json"}) as r:
                if r.status != 200: return None
                d = await r.json()
                if not d.get("results"): return None
                loc = d["results"][0]; lat, lon = loc["latitude"], loc["longitude"]
                name = loc.get("name", city); country = loc.get("country", "")
            async with s.get("https://api.open-meteo.com/v1/forecast", params={"latitude":lat,"longitude":lon,"current":"temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,apparent_temperature","timezone":"auto"}) as r:
                if r.status != 200: return None
                w = await r.json(); c = w.get("current", {})
                return (f"🌍 <b>{name}</b>, {country}\n━━━━━━━━━━━━━━━━━━━━\n{WCODES.get(c.get('weather_code',0),'🌡')}\n"
                        f"🌡 Температура: <b>{c.get('temperature_2m')}°C</b>\n🤔 Ощущается: <b>{c.get('apparent_temperature')}°C</b>\n"
                        f"💧 Влажность: <b>{c.get('relative_humidity_2m')}%</b>\n💨 Ветер: <b>{c.get('wind_speed_10m')} км/ч</b>\n━━━━━━━━━━━━━━━━━━━━")
    except Exception as e: logging.error(f"get_weather: {e}"); return None

async def translate_text(text, tl="ru"):
    try:
        t = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=t) as s:
            async with s.get("https://translate.googleapis.com/translate_a/single", params={"client":"gtx","sl":"auto","tl":tl,"dt":"t","q":text}) as r:
                if r.status != 200: return None
                d = await r.json()
                if d and isinstance(d, list) and d[0]:
                    tr = "".join(p[0] for p in d[0] if p and p[0]); det = d[2] if len(d) > 2 else "auto"
                    return tr, det
                return None
    except Exception as e: logging.error(f"translate: {e}"); return None

async def download_file(fid):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", json={"file_id": fid}) as r:
                d = await r.json()
                if not d.get("ok"): return None
                fp = d["result"]["file_path"]
            async with s.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{fp}") as r:
                return await r.read()
    except Exception as e: logging.error(f"download_file: {e}"); return None

def split_3x3(img_bytes):
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB"); w, h = img.size
        tr = 9/16; cr = w/h
        if cr > tr:
            nw = int(h*tr); left = (w-nw)//2; img = img.crop((left,0,left+nw,h))
        else:
            nh = int(w/tr); top = (h-nh)//2; img = img.crop((0,top,w,top+nh))
        w, h = img.size; cw = w//3; ch = h//3; parts = []
        for r in range(2,-1,-1):
            for c in range(2,-1,-1):
                box = (c*cw, r*ch, (c+1)*cw, (r+1)*ch)
                p = img.crop(box).resize((1080,1920), Image.LANCZOS)
                b = io.BytesIO(); p.save(b, format="JPEG", quality=95); parts.append(b.getvalue())
        return parts
    except Exception as e: logging.error(f"split_3x3: {e}"); return []

async def post_story(conn, img_bytes, fname, caption=""):
    try:
        form = aiohttp.FormData()
        form.add_field("business_connection_id", conn); form.add_field("active_period", "86400"); form.add_field("post_to_chat_page", "true")
        if caption: form.add_field("caption", caption[:200])
        form.add_field("content", json.dumps({"type":"photo","photo":"attach://story_photo"}))
        form.add_field("story_photo", img_bytes, filename=fname, content_type="image/jpeg")
        async with aiohttp.ClientSession() as s:
            async with s.post(f"https://api.telegram.org/bot{BOT_TOKEN}/postStory", data=form) as r:
                res = await r.json()
                if res.get("ok"): return True, ""
                return False, res.get("description", "unknown")
    except Exception as e: return False, str(e)

_SAFE_OPS = {ast.Add:operator.add, ast.Sub:operator.sub, ast.Mult:operator.mul, ast.Div:operator.truediv, ast.Pow:operator.pow, ast.Mod:operator.mod, ast.USub:operator.neg, ast.UAdd:operator.pos, ast.FloorDiv:operator.floordiv}
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
    except Exception: return None

async def fetch_prices():
    lines = ["💱 <b>Курсы валют к рублю</b>","━━━━━━━━━━━━━━━━━━━━"]; got = False; usdr = None
    try:
        t = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=t) as s:
            async with s.get("https://www.cbr-xml-daily.ru/daily_json.js") as r:
                if r.status == 200:
                    d = await r.json(); usdr = d["Valute"]["USD"]["Value"]
                    lines += [f"🇺🇸 USD: <b>{usdr:.2f}₽</b>", f"🇪🇺 EUR: <b>{d['Valute']['EUR']['Value']:.2f}₽</b>", f"🇨🇳 CNY: <b>{d['Valute']['CNY']['Value']:.2f}₽</b>"]; got = True
    except Exception as e: logging.error(f"cbr: {e}")
    try:
        t = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=t) as s:
            async with s.get("https://api.coinpaprika.com/v1/tickers/usdt-tether") as r:
                if r.status == 200:
                    d = await r.json(); pu = float(d["quotes"]["USD"]["price"])
                    lines.append(f"💵 USDT: <b>{pu*usdr:.2f}₽</b>" if usdr else f"💵 USDT: <b>${pu:.4f}</b>"); got = True
    except Exception as e: logging.error(f"usdt: {e}")
    for tid in ("ton-toncoin","toncoin"):
        try:
            t = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=t) as s:
                async with s.get(f"https://api.coinpaprika.com/v1/tickers/{tid}") as r:
                    if r.status == 200:
                        d = await r.json(); pu = float(d["quotes"]["USD"]["price"])
                        lines.append(f"💎 TON: <b>{pu*usdr:.2f}₽</b>" if usdr else f"💎 TON: <b>${pu:.4f}</b>"); got = True; break
        except Exception: pass
    if not got: return "❌ Не удалось получить курсы"
    lines.append("━━━━━━━━━━━━━━━━━━━━"); return "\n".join(lines)

RPS_WINS = {"камень":"ножницы","ножницы":"бумага","бумага":"камень"}
def rps_res(p,b):
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
            i = r*3+c; row.append(types.InlineKeyboardButton(text=b[i] if b[i] != " " else "·", callback_data=f"ttt_{i}"))
        rows.append(row)
    return types.InlineKeyboardMarkup(inline_keyboard=rows)
def ttt_w(b):
    for a,c,d in [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]]:
        if b[a] != " " and b[a] == b[c] == b[d]: return b[a]
    return "draw" if " " not in b else None
def wordle_r(g):
    out = ["🎯 <b>Wordle</b>","━━━━━━━━━━━━━━━━━━━━", f"Слово из <b>{len(g['word'])}</b> букв. Попыток: <b>{g['tries']}</b>",""]
    for guess, marks in g["history"]:
        line = ""
        for i, ch in enumerate(guess):
            line += f"🟩{ch.upper()}" if marks[i]=="G" else f"🟨{ch.upper()}" if marks[i]=="Y" else f"⬜{ch.upper()}"
        out.append(line)
    out += ["","━━━━━━━━━━━━━━━━━━━━"]; return "\n".join(out)
def wordle_m(w, g):
    marks = ["B"]*len(w); used = [False]*len(w)
    for i in range(len(w)):
        if g[i]==w[i]: marks[i]="G"; used[i]=True
    for i in range(len(w)):
        if marks[i]=="G": continue
        for j in range(len(w)):
            if not used[j] and g[i]==w[j]: marks[i]="Y"; used[j]=True; break
    return "".join(marks)

def pluralize(n):
    s = f"{n:,}".replace(","," "); m100 = n%100; m10 = n%10
    if 11<=m100<=19: w = "пользователей"
    elif m10==1: w = "пользователь"
    elif 2<=m10<=4: w = "пользователя"
    else: w = "пользователей"
    return f"{s} {w}"

async def update_bot_name():
    try:
        await bot(SetMyName(name="AntiSpam Defender")); logging.info("🏷 Имя бота обновлено"); return True
    except Exception as e:
        err = str(e)
        if "Flood control" in err or "Too Many Requests" in err: logging.warning("⏳ Flood control")
        else: logging.error(f"setMyName: {e}")
        return False

async def update_bot_description():
    global _last_bio
    try:
        total = await get_total_users(); pretty = pluralize(total)
        desc = f"🛡 AntiSpam Defender\n━━━━━━━━━━━━━━━━━━━━\nЗащита бизнес-чатов:\nмодерация, развлечения, утилиты.\n\n👥 {pretty}"
        if len(desc) > 512: desc = desc[:509]+"..."
        try:
            await bot.set_my_description(description=desc); _last_bio = desc; logging.info(f"📝 Bio: {pretty}")
        except Exception as e1:
            logging.error(f"setMyDescription: {e1}")
            try:
                sh = f"🛡 AntiSpam Defender · 👥 {pretty}"
                if len(sh) > 120: sh = sh[:117]+"..."
                await bot.set_my_short_description(short_description=sh)
            except Exception as e2: logging.error(f"setShort: {e2}")
        return True
    except Exception as e: logging.error(f"update_desc: {e}"); return False

async def background_name_updater():
    await asyncio.sleep(300)
    ok = await update_bot_name(); await update_bot_description()
    while True:
        await asyncio.sleep(NAME_UPDATE_INTERVAL if ok else 7200)
        ok = await update_bot_name(); await update_bot_description()

async def check_subscription(uid):
    try:
        m = await bot.get_chat_member(CHANNEL_ID, uid)
        return m.status not in ("left","kicked")
    except Exception as e: logging.error(f"sub: {e}"); return True

def subscribe_kb():
    return types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="📢 Подписаться", url=CHANNEL_LINK)],[types.InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")]])

async def get_owner_id(conn):
    if not conn: return None
    if conn in business_owners: return business_owners[conn]
    try:
        c = await bot.get_business_connection(conn); business_owners[conn] = c.user.id; return c.user.id
    except Exception as e: logging.error(f"get_owner_id: {e}"); return None

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

def main_menu():
    return types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="📖 Команды", callback_data="cmd_list")],[types.InlineKeyboardButton(text="💎 Подписка", callback_data="sub_menu")],[types.InlineKeyboardButton(text="👥 Пригласить друга", callback_data="ref")],[types.InlineKeyboardButton(text="📚 Как подключить", callback_data="howto")]])
def back_kb(): return types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="🔙 В меню", callback_data="back_main")]])
def plans_kb(uid=None):
    rows = [[types.InlineKeyboardButton(text=f"🎁 Пробный период ({TRIAL_DAYS} дней)", callback_data="trial")]]
    for k,v in PRICES.items(): rows.append([types.InlineKeyboardButton(text=f"{v['label']} — {v['rub']}₽", callback_data=f"pay_{k}")])
    rows.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)

TEXT_MAIN_MENU = "🏠 <b>Главное меню</b>\n━━━━━━━━━━━━━━━━━━━━\n🛡 <b>AntiSpam Defender</b> — защита\nваших бизнес-чатов от спама\nи нежелательных сообщений.\n━━━━━━━━━━━━━━━━━━━━\n👇 <i>Выбери действие:</i>"
TEXT_CMD_LIST = ("📖 <b>Команды бота</b>\n━━━━━━━━━━━━━━━━━━━━\n\n🛡 <b>Модерация</b>\n• <code>.mute N</code> · <code>.unmute</code>\n• <code>.warn N</code> · <code>.unwarn</code>\n• <code>.spam N текст</code>\n• <code>.nonmute on/off</code>\n\n🎮 <b>Развлечения</b>\n• <code>.info</code> · <code>.st текст</code>\n• <code>.calc 5*5</code> · <code>.qr текст</code>\n• <code>.dl N текст</code> · <code>.txt текст</code>\n• <code>.rps</code> · <code>.ttt</code> · <code>.wordle слово</code>\n• <code>.roll 2d6</code> · <code>.coin</code> · <code>.8ball вопрос</code>\n\n🌐 <b>Полезное</b>\n• <code>.price</code> · <code>.weather Город</code>\n• <code>.translate текст</code>\n\n🖋 <b>Авто-шрифт</b>\n• <code>.type on bold/italic/underline/strike/code/quote/spoiler</code>\n• <code>.type off</code>\n\n📸 <b>Истории</b>\n• <code>.story</code> (ответ на фото) — 3×3\n\n📝 <b>Статусы</b>\n• <code>.text</code> · <code>.photo</code> · <code>.gs</code>\n\n👻 <b>Приватность</b>\n• <code>.ghost on/off</code>\n━━━━━━━━━━━━━━━━━━━━")
TEXT_HOWTO = "📚 <b>Как подключить</b>\n━━━━━━━━━━━━━━━━━━━━\n\n1️⃣ <b>Настройки</b>\n2️⃣ <b>Аккаунт</b>\n3️⃣ <b>Автоматизация чатов</b>\n4️⃣ <b>AntiSpam Defender</b>\n\n✅ <b>Разрешения:</b>\n• Чтение сообщений\n• Ответы на сообщения\n• Удаление сообщений\n\n💬 Пиши команды <b>в бизнес-чате</b>:\n<code>.mute 10</code>\n━━━━━━━━━━━━━━━━━━━━"
TEXT_REF = "👥 <b>Пригласить друга</b>\n━━━━━━━━━━━━━━━━━━━━\n\n🎁 За каждого друга — <b>+3 дня</b>\n\n🔗 <b>Твоя ссылка:</b>\n<code>{link}</code>\n\n📊 <b>Приглашено:</b> {count}\n━━━━━━━━━━━━━━━━━━━━"

@dp.message(F.text == "/start")
async def start_cmd(message):
    uid = message.from_user.id
    await register_user(uid, message.from_user.username or "", message.from_user.first_name or "")
    total = await get_total_users()
    logging.info(f"👤 /start от {uid} | всего: {total}")
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            rid = int(args[1][4:])
            if rid != uid:
                referrals.setdefault(rid, set()).add(uid)
                now = datetime.now()
                cur = await get_subscription(rid) or now
                await set_subscription(rid, max(cur, now) + timedelta(days=3))
                try: await bot.send_message(rid, "🎁 <b>Новый друг присоединился!</b>\n+3 дня", parse_mode="HTML")
                except: pass
        except ValueError: pass
    if not await check_subscription(uid):
        await message.answer("⚠️ <b>Подпишись на канал для использования бота.</b>\n\n📢 Подпишись и нажми «✅ Я подписался».", parse_mode="HTML", reply_markup=subscribe_kb()); return
    await send_photo_banner(message.chat.id, TEXT_MAIN_MENU, kb=main_menu())

@dp.message(F.text == "/stats", F.from_user.id == OWNER_ID)
async def stats_cmd(message):
    total = await get_total_users(); with_sub = await count_active_subs(); trials = await count_trials()
    last = await get_last_users(10)
    text = f"📊 <b>Статистика</b>\n━━━━━━━━━━━━━━━━━━━━\n\n👥 Пользователей: <b>{total}</b>\n💎 Подписок: <b>{with_sub}</b>\n🎁 Триалов: <b>{trials}</b>\n\n🕐 <b>Последние 10:</b>\n"
    for row in last:
        name = row["first_name"] or row["username"] or str(row["user_id"]); un = f"@{row['username']}" if row["username"] else ""
        text += f"• {name} {un} (<code>{row['user_id']}</code>)\n"
    text += "━━━━━━━━━━━━━━━━━━━━"
    await message.answer(text, parse_mode="HTML")

@dp.business_connection()
async def on_business_connection(conn: types.BusinessConnection):
    try:
        business_owners[conn.id] = conn.user.id
        username_cache[(conn.user.username or "").lower()] = conn.user.id
        last_conn_by_chat[conn.user.id] = conn.id
        logging.info(f"🔗 Business connection: {conn.id} owner={conn.user.id} @{conn.user.username}")
    except Exception as e: logging.error(f"on_business_connection: {e}")

@dp.deleted_business_messages()
async def on_deleted_messages(event: types.BusinessMessagesDeleted):
    try:
        cid = event.chat.id; conn = event.business_connection_id
        if not await get_owner_id(conn): return
        if nonmute_active.get(cid, False) is not True: return
        cached = message_cache.get(cid, {})
        if not cached: return
        for mid in event.message_ids:
            if mid in deleted_by_bot: deleted_by_bot.discard(mid); continue
            data = cached.get(mid)
            if not data: continue
            txt = (data.get("text") or "").strip()
            if txt.startswith("."): continue
            try:
                if data.get("text"): await bot.send_message(chat_id=cid, text=data["text"], business_connection_id=conn)
                elif data.get("photo"): await bot.send_photo(chat_id=cid, photo=data["photo"], business_connection_id=conn)
                elif data.get("video"): await bot.send_video(chat_id=cid, video=data["video"], business_connection_id=conn)
                elif data.get("video_note"): await bot.send_video_note(chat_id=cid, video_note=data["video_note"], business_connection_id=conn)
                elif data.get("voice"): await bot.send_voice(chat_id=cid, voice=data["voice"], business_connection_id=conn)
                elif data.get("audio"): await bot.send_audio(chat_id=cid, audio=data["audio"], business_connection_id=conn)
                elif data.get("document"): await bot.send_document(chat_id=cid, document=data["document"], business_connection_id=conn)
                elif data.get("sticker"): await bot.send_sticker(chat_id=cid, sticker=data["sticker"], business_connection_id=conn)
                elif data.get("animation"): await bot.send_animation(chat_id=cid, animation=data["animation"], business_connection_id=conn)
            except Exception as e: logging.error(f"restore {mid}: {e}")
            await asyncio.sleep(0.3)
    except Exception as e: logging.error(f"on_deleted: {e}")

@dp.business_message()
async def business_msg(message: types.Message):
    try:
        text = message.text or ""; cid = message.chat.id; conn = message.business_connection_id
        owner_id_of_conn = await get_owner_id(conn)
        if not owner_id_of_conn: return
        if message.from_user and is_duplicate(cid, message.from_user.id, text): return
        cache_message(message)
        if message.from_user:
            last_conn_by_chat[message.from_user.id] = conn
            if message.from_user.username: username_cache[message.from_user.username.lower()] = message.from_user.id
        is_incoming = message.from_user and message.from_user.id != owner_id_of_conn
        is_from_owner = message.from_user and message.from_user.id == owner_id_of_conn

        if is_incoming:
            muted = mutes.get(message.from_user.id) or mutes.get(cid)
            if muted and datetime.now() < muted:
                try:
                    deleted_by_bot.add(message.message_id); await delete_business_msg(conn, [message.message_id])
                except Exception as e: logging.error(f"mute del: {e}")
                return
        if ghost_chats.get(cid) and is_incoming and not text.startswith("."):
            try:
                u = message.from_user
                await bot.send_message(owner_id_of_conn, f"👻 <b>Ghost</b>\n━━━━━━━━━━━━━━━━━━━━\n👤 @{u.username or u.full_name} (<code>{u.id}</code>)\n📝 <code>{(message.text or '[медиа]')[:500]}</code>", parse_mode="HTML")
            except Exception as e: logging.error(f"ghost: {e}")
        if echo_chats.get(cid) and is_incoming and text and not text.startswith("."):
            try: await bot.send_message(chat_id=cid, text=text, business_connection_id=conn)
            except Exception as e: logging.error(f"echo: {e}")
            return
        if is_from_owner and cid in type_styles and text and not text.startswith("."):
            style = type_styles.get(cid)
            if style and style in TYPE_STYLES:
                o, cl = TYPE_STYLES[style]
                try:
                    deleted_by_bot.add(message.message_id); await delete_business_msg(conn, [message.message_id])
                except Exception as e: logging.error(f"type del: {e}")
                try: await bot.send_message(chat_id=cid, text=f"{o}{text}{cl}", parse_mode="HTML", business_connection_id=conn)
                except Exception as e: logging.error(f"type send: {e}")
                return
        if not text.startswith("."): return
        if not message.from_user or message.from_user.id != owner_id_of_conn: return
        if not await check_subscription(owner_id_of_conn):
            await delete_cmd(message)
            await send_confirm(cid, "⚠️ <b>Нужна подписка на канал!</b>\n\n" + f"📢 Подпишись: {CHANNEL_LINK}\n\nЗатем /start в ЛС бота.", conn); return
        parts = text.split(); cmd = parts[0].lower()

        if cmd == ".info":
            await delete_cmd(message)
            t = message.reply_to_message.from_user if message.reply_to_message else message.from_user
            if not t: return
            un = f"@{t.username}" if t.username else "—"
            pm = "✅" if getattr(t, "is_premium", False) else "—"
            await send_confirm(cid, f"ℹ️ <b>Данные собеседника</b>\n━━━━━━━━━━━━━━━━━━━━\n👤 Имя: <b>{t.full_name}</b>\n🔗 Username: <b>{un}</b>\n🆔 ID: <code>{t.id}</code>\n🌐 Язык: <b>{t.language_code or '—'}</b>\n💎 Premium: <b>{pm}</b>\n━━━━━━━━━━━━━━━━━━━━", conn); return

        if cmd == ".weather":
            if len(parts) < 2: await delete_cmd(message); await send_confirm(cid, "❌ <code>.weather Город</code>", conn); return
            city = " ".join(parts[1:]); await delete_cmd(message); await send_chat_action(cid, conn, "typing")
            r = await get_weather(city)
            await send_confirm(cid, r if r else f"❌ Не нашёл <b>{city}</b>", conn); return

        if cmd == ".translate":
            if len(parts) < 2: await delete_cmd(message); await send_confirm(cid, "❌ <code>.translate текст</code>", conn); return
            src = " ".join(parts[1:]); await delete_cmd(message); await send_chat_action(cid, conn, "typing")
            r = await translate_text(src, "ru")
            if r:
                tr, det = r
                await send_confirm(cid, f"🌐 <b>Перевод</b>\n━━━━━━━━━━━━━━━━━━━━\n<i>Было ({det}):</i>\n{src[:300]}\n\n<i>Стало (ru):</i>\n{tr[:300]}\n━━━━━━━━━━━━━━━━━━━━", conn)
            else: await send_confirm(cid, "❌ Не удалось перевести", conn)
            return

        if cmd == ".roll":
            await delete_cmd(message)
            try:
                dice = parts[1] if len(parts) > 1 else "1d6"
                if "d" in dice.lower(): n, m = dice.lower().split("d"); n = max(1, min(int(n), 20)); m = max(2, min(int(m), 1000))
                else: n, m = 1, int(dice)
            except Exception: n, m = 1, 6
            res = [random.randint(1, m) for _ in range(n)]
            await send_confirm(cid, f"🎲 <b>Бросок {n}d{m}</b>\n━━━━━━━━━━━━━━━━━━━━\nРезультаты: <code>{', '.join(str(x) for x in res)}</code>\nСумма: <b>{sum(res)}</b>\n━━━━━━━━━━━━━━━━━━━━", conn, 30); return

        if cmd == ".coin":
            await delete_cmd(message); await send_confirm(cid, f"<b>{random.choice(['🪙 Орёл','🪙 Решка'])}</b>", conn, 15); return

        if cmd == ".8ball":
            await delete_cmd(message)
            if len(parts) < 2: await send_confirm(cid, "❌ <code>.8ball вопрос</code>", conn, 5); return
            await send_confirm(cid, f"❓ <i>{' '.join(parts[1:])[:200]}</i>\n\n{random.choice(EIGHTBALL)}", conn, 30); return

        if cmd == ".type":
            arg = parts[1].lower() if len(parts) > 1 else ""
            if arg == "off":
                type_styles.pop(cid, None); await delete_cmd(message); await send_confirm(cid, "🖋 <b>Авто-шрифт выключен</b>", conn); return
            if arg == "on":
                if len(parts) < 3:
                    await delete_cmd(message)
                    sl = ", ".join(f"<code>{s}</code>" for s in TYPE_STYLES.keys())
                    await send_confirm(cid, f"❌ Укажи стиль:\n<code>.type on bold</code>\nДоступные: {sl}", conn); return
                style = parts[2].lower()
                if style not in TYPE_STYLES:
                    await delete_cmd(message); await send_confirm(cid, f"❌ Стиль не найден", conn); return
                type_styles[cid] = style; await delete_cmd(message); await send_confirm(cid, f"🖋 <b>Авто-шрифт: {style}</b>", conn); return
            cur = type_styles.get(cid); await delete_cmd(message)
            await send_confirm(cid, f"🖋 <b>{cur}</b>" if cur else "🖋 <b>выключен</b>", conn); return

        if cmd == ".mute":
            try: mins = int(parts[1]) if len(parts) > 1 else 10
            except ValueError: mins = 10
            tid = message.reply_to_message.from_user.id if (message.reply_to_message and message.reply_to_message.from_user) else cid
            if tid == owner_id_of_conn: await delete_cmd(message); await send_confirm(cid, "❌ Ответь реплаем", conn); return
            mutes[tid] = datetime.now() + timedelta(minutes=mins); await delete_cmd(message)
            await send_confirm(cid, f"🔇 <b>Мут на {mins} мин</b>", conn); return

        if cmd == ".unmute":
            tid = message.reply_to_message.from_user.id if (message.reply_to_message and message.reply_to_message.from_user) else cid
            mutes.pop(tid, None); await delete_cmd(message); await send_confirm(cid, "🔊 <b>Мут снят</b>", conn); return

        if cmd == ".warn":
            try: cnt = int(parts[1]) if len(parts) > 1 else 1
            except ValueError: cnt = 1
            tid = message.reply_to_message.from_user.id if (message.reply_to_message and message.reply_to_message.from_user) else cid
            if tid == owner_id_of_conn: await delete_cmd(message); await send_confirm(cid, "❌ Ответь реплаем", conn); return
            warns[tid] = warns.get(tid, 0) + cnt; await delete_cmd(message)
            await send_confirm(cid, f"⚠️ <b>Warn {warns[tid]}/{WARN_LIMIT}</b>", conn)
            if warns[tid] >= WARN_LIMIT:
                mutes[tid] = datetime.now() + timedelta(minutes=WARN_MUTE_MINUTES); warns[tid] = 0
                await send_confirm(cid, f"🔇 <b>Мут {WARN_MUTE_MINUTES} мин</b>", conn)
            return

        if cmd == ".unwarn":
            tid = message.reply_to_message.from_user.id if (message.reply_to_message and message.reply_to_message.from_user) else cid
            warns.pop(tid, None); await delete_cmd(message); await send_confirm(cid, "✅ <b>Варны сброшены</b>", conn); return

        if cmd == ".spam":
            if len(parts) < 3: await delete_cmd(message); await send_confirm(cid, "❌ <code>.spam N текст</code>", conn); return
            try: cnt = min(int(parts[1]), 30)
            except ValueError: cnt = 1
            st = " ".join(parts[2:]); await delete_cmd(message)
            for _ in range(cnt):
                try:
                    await bot.send_message(chat_id=cid, text=st, business_connection_id=conn); await asyncio.sleep(0.15)
                except Exception as e: logging.error(f"spam: {e}"); break
            return

        if cmd == ".st":
            if len(parts) < 2: await delete_cmd(message); return
            s = " ".join(parts[1:]); await delete_cmd(message)
            try: await bot.send_message(chat_id=cid, text=distort(s), business_connection_id=conn)
            except Exception as e: logging.error(f"st: {e}")
            return

        if cmd == ".clone":
            if len(parts) < 2: await delete_cmd(message); return
            if parts[1].lower() == "on": clone[cid] = True; await delete_cmd(message); await send_confirm(cid, "🧬 <b>Клон включён</b>", conn)
            else: clone.pop(cid, None); await delete_cmd(message); await send_confirm(cid, "🧬 <b>Клон выключен</b>", conn)
            return

        if cmd == ".nonmute":
            arg = parts[1].lower() if len(parts) > 1 else ""
            if arg == "on": nonmute_active[cid] = True; await delete_cmd(message); await send_confirm(cid, "🛡 <b>Обход мута вкл</b>", conn)
            elif arg == "off": nonmute_active[cid] = False; await delete_cmd(message); await send_confirm(cid, "🔒 <b>Обход мута выкл</b>", conn)
            else: await delete_cmd(message); await send_confirm(cid, "ℹ️ <code>.nonmute on/off</code>", conn)
            return

        if cmd in (".calc", ".c"):
            if len(parts) < 2: await delete_cmd(message); return
            expr = " ".join(parts[1:]); await delete_cmd(message)
            if len(expr) > 200: await send_confirm(cid, "❌ Слишком длинное", conn); return
            r = calc_expr(expr)
            if r is None: await send_confirm(cid, "❌ Не могу посчитать", conn); return
            if isinstance(r, float) and r.is_integer(): r = int(r)
            await send_confirm(cid, f"🧮 <b>Калькулятор</b>\n━━━━━━━━━━━━━━━━━━━━\n<code>{expr}</code>\n= <b>{r}</b>\n━━━━━━━━━━━━━━━━━━━━", conn); return

        if cmd == ".qr":
            if len(parts) < 2: await delete_cmd(message); return
            qt = " ".join(parts[1:]); await delete_cmd(message)
            if len(qt) > 1000: await send_confirm(cid, "❌ Слишком длинный", conn); return
            try:
                img = qrcode.make(qt); buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
                await bot.send_photo(chat_id=cid, photo=BufferedInputFile(buf.read(), filename="qr.png"),
                    caption=f"📱 <b>QR-код</b>\n━━━━━━━━━━━━━━━━━━━━\n<code>{qt[:100]}</code>\n━━━━━━━━━━━━━━━━━━━━",
                    parse_mode="HTML", business_connection_id=conn)
            except Exception as e:
                logging.error(f"QR: {e}"); await send_confirm(cid, "❌ Ошибка QR", conn)
            return

        if cmd == ".echo":
            if len(parts) < 2: await delete_cmd(message); return
            if parts[1].lower() == "on": echo_chats[cid] = True; await delete_cmd(message); await send_confirm(cid, "🔁 <b>Эхо вкл</b>", conn)
            else: echo_chats.pop(cid, None); await delete_cmd(message); await send_confirm(cid, "🔇 <b>Эхо выкл</b>", conn)
            return

        if cmd == ".dl":
            if len(parts) < 3: await delete_cmd(message); await send_confirm(cid, "❌ <code>.dl N текст</code>", conn); return
            try: sec = min(int(parts[1]), 300)
            except ValueError: sec = 5
            dt = " ".join(parts[2:]); await delete_cmd(message)
            try:
                msg = await bot.send_message(chat_id=cid, text=dt, business_connection_id=conn)
                asyncio.create_task(auto_delete(cid, msg.message_id, conn, sec))
            except Exception as e: logging.error(f"dl: {e}")
            return

        if cmd == ".txt":
            if len(parts) < 2: await delete_cmd(message); return
            src = " ".join(parts[1:]); await delete_cmd(message)
            try:
                msg = await bot.send_message(chat_id=cid, text="▫️", business_connection_id=conn)
                cur = ""
                for ch in src[:80]:
                    cur += ch
                    try: await bot.edit_message_text(chat_id=cid, message_id=msg.message_id, text=cur + "▫️", business_connection_id=conn)
                    except Exception: pass
                    await asyncio.sleep(0.4)
                try: await bot.edit_message_text(chat_id=cid, message_id=msg.message_id, text=cur, business_connection_id=conn)
                except Exception: pass
            except Exception as e: logging.error(f"txt: {e}")
            return

        if cmd == ".price":
            await delete_cmd(message)
            try: await send_confirm(cid, await fetch_prices(), conn)
            except Exception as e: logging.error(f"price: {e}"); await send_confirm(cid, "❌ Не удалось получить курсы", conn)
            return

        if cmd == ".rps":
            await delete_cmd(message); bc = random.choice(list(RPS_WINS.keys()))
            kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="✊ Камень", callback_data=f"rps_камень_{bc}"), types.InlineKeyboardButton(text="✌️ Ножницы", callback_data=f"rps_ножницы_{bc}"), types.InlineKeyboardButton(text="✋ Бумага", callback_data=f"rps_бумага_{bc}")]])
            await send_confirm(cid, "🎮 <b>Камень-ножницы-бумага</b>\n\n👇 Сделай выбор:", conn, kb=kb); return

        if cmd == ".ttt":
            await delete_cmd(message); ttt_games[cid] = {"board": [" "] * 9}
            await send_confirm(cid, "❌ <b>Крестики-нолики</b>\n\n👇 Твой ход:", conn, kb=ttt_kb(cid)); return

        if cmd == ".wordle":
            if len(parts) < 2: await delete_cmd(message); await send_confirm(cid, "❌ <code>.wordle слово</code>", conn); return
            w = parts[1].lower()
            if not w.isalpha() or len(w) < 3: await delete_cmd(message); await send_confirm(cid, "❌ Слово от 3 букв", conn); return
            wordle_games[cid] = {"word": w, "tries": 5, "history": []}; await delete_cmd(message)
            await send_confirm(cid, wordle_r(wordle_games[cid]), conn); return

        if cmd == ".ghost":
            arg = parts[1].lower() if len(parts) > 1 else ""
            if arg == "on": ghost_chats[cid] = True; await delete_cmd(message); await send_confirm(cid, "👻 <b>Ghost вкл</b>", conn)
            elif arg == "off": ghost_chats.pop(cid, None); await delete_cmd(message); await send_confirm(cid, "👻 <b>Ghost выкл</b>", conn)
            else: await delete_cmd(message); await send_confirm(cid, "ℹ️ <code>.ghost on/off</code>", conn)
            return

        if cmd == ".story":
            if not message.reply_to_message or not message.reply_to_message.photo:
                await delete_cmd(message); await send_confirm(cid, "❌ Ответь реплаем на фото", conn); return
            await delete_cmd(message); await send_confirm(cid, "⏳ Режу фото на 9 частей...", conn, 3)
            photo = message.reply_to_message.photo[-1]
            fb = await download_file(photo.file_id)
            if not fb: await send_confirm(cid, "❌ Не удалось скачать фото", conn); return
            pi = split_3x3(fb)
            if not pi: await send_confirm(cid, "❌ Ошибка нарезки", conn); return
            caption = " ".join(parts[1:]) if len(parts) > 1 else ""
            posted = 0; last_err = ""
            for i, piece in enumerate(pi):
                ok, err = await post_story(conn, piece, f"part_{i}.jpg", caption)
                if ok: posted += 1
                else: last_err = err; logging.error(f"postStory {i}: {err}")
                await asyncio.sleep(0.7)
            if posted == 0 and last_err: await send_confirm(cid, f"❌ Ошибка: <code>{last_err[:150]}</code>", conn)
            else: await send_confirm(cid, f"✅ Выложено: <b>{posted}/9</b>", conn)
            return

        if cmd == ".text": await delete_cmd(message); await send_chat_action(cid, conn, "typing"); return
        if cmd == ".untext": await delete_cmd(message); await send_confirm(cid, "⌨️ <b>Снят</b>", conn); return
        if cmd == ".photo": await delete_cmd(message); await send_chat_action(cid, conn, "photo"); return
        if cmd == ".unphoto": await delete_cmd(message); await send_confirm(cid, "📷 <b>Снят</b>", conn); return
        if cmd == ".gs": await delete_cmd(message); await send_chat_action(cid, conn, "voice"); return
        if cmd == ".ungs": await delete_cmd(message); await send_confirm(cid, "🎙 <b>Снят</b>", conn); return

        if cid in wordle_games and len(text.split()) == 1 and text.isalpha():
            g = wordle_games[cid]; guess = text.lower()
            if len(guess) != len(g["word"]): return
            m = wordle_m(g["word"], guess); g["history"].append((guess, m)); g["tries"] -= 1
            await delete_cmd(message)
            if guess == g["word"]: await send_confirm(cid, wordle_r(g) + "\n\n🎉 <b>Угадал!</b>", conn); wordle_games.pop(cid, None)
            elif g["tries"] <= 0: await send_confirm(cid, wordle_r(g) + f"\n\n😢 <b>Слово: {g['word']}</b>", conn); wordle_games.pop(cid, None)
            else: await send_confirm(cid, wordle_r(g), conn)
            return
    except Exception as e: logging.error(f"business_msg: {type(e).__name__}: {e}")

@dp.business_message(F.reply_to_message)
async def onetime_media(message: types.Message):
    if message.text and message.text.startswith("."): return
    rep = message.reply_to_message
    if not rep: return
    if not (rep.photo or rep.video or rep.video_note): return
    conn = message.business_connection_id; oid = await get_owner_id(conn)
    if not oid: return
    if not message.from_user or message.from_user.id != oid: return
    if not await check_subscription(oid): return
    try:
        await bot.copy_message(chat_id=oid, from_chat_id=rep.chat.id, message_id=rep.message_id)
        await send_confirm(message.chat.id, "✅ <b>Медиа в ЛС</b>", conn)
    except Exception as e: logging.error(f"onetime_media: {e}")

@dp.callback_query(F.data.startswith("rps_"))
async def cb_rps(call):
    p = call.data.split("_")
    if len(p) != 3: await call.answer(); return
    try: await call.message.edit_text(f"✊ Ты: <b>{p[1]}</b>\n🤖 Бот: <b>{p[2]}</b>\n\n{rps_res(p[1], p[2])}", parse_mode="HTML")
    except: pass
    await call.answer()

@dp.callback_query(F.data.startswith("ttt_"))
async def cb_ttt(call):
    try: idx = int(call.data.split("_")[1])
    except: await call.answer(); return
    cid = call.message.chat.id; g = ttt_games.get(cid)
    if not g: await call.answer("Не найдено", show_alert=True); return
    b = g["board"]
    if b[idx] != " ": await call.answer("Занято", show_alert=True); return
    b[idx] = "❌"; w = ttt_w(b)
    if not w:
        free = [i for i in range(9) if b[i] == " "]
        if free: b[random.choice(free)] = "⭕"; w = ttt_w(b)
    kb = ttt_kb(cid)
    if w == "❌": await call.message.edit_text("❌ <b>Победа!</b>", parse_mode="HTML"); ttt_games.pop(cid, None)
    elif w == "⭕": await call.message.edit_text("⭕ <b>Бот победил</b>", parse_mode="HTML"); ttt_games.pop(cid, None)
    elif w == "draw": await call.message.edit_text("🤝 <b>Ничья</b>", parse_mode="HTML"); ttt_games.pop(cid, None)
    else: await call.message.edit_reply_markup(reply_markup=kb)
    await call.answer()

@dp.message(F.chat.type == "private", F.text.startswith("."))
async def pm_commands(message: types.Message):
    if message.from_user.id != OWNER_ID: await message.answer("❌ Только владелец."); return
    parts = (message.text or "").strip().split()
    if parts[0] == ".help":
        await message.answer("📖 <code>.mute @user N</code> · <code>.unmute @user</code>", parse_mode="HTML"); return
    if parts[0] == ".mute" and len(parts) >= 3:
        t = parts[1].lstrip("@")
        try: m = int(parts[2])
        except ValueError: m = 10
        conn, cid = await find_connection_by_target(t)
        if not conn: await message.answer(f"❌ Не нашёл <b>{t}</b>", parse_mode="HTML"); return
        mutes[cid] = datetime.now() + timedelta(minutes=m)
        await bot_api("sendMessage", {"chat_id": cid, "text": f"🔇 Мут {m} мин", "business_connection_id": conn})
        await message.answer(f"✅ Мут <b>{t}</b> на {m} мин", parse_mode="HTML"); return
    if parts[0] == ".unmute" and len(parts) >= 2:
        t = parts[1].lstrip("@")
        conn, cid = await find_connection_by_target(t)
        if not conn: await message.answer(f"❌ Не нашёл", parse_mode="HTML"); return
        mutes.pop(cid, None); warns.pop(cid, None); await delete_warn_msg(cid)
        await bot_api("sendMessage", {"chat_id": cid, "text": "🔊 Мут снят", "business_connection_id": conn})
        await message.answer(f"✅ Снят", parse_mode="HTML"); return

@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(call):
    if await check_subscription(call.from_user.id):
        try: await call.message.delete()
        except: pass
        await send_photo_banner(call.message.chat.id, TEXT_MAIN_MENU, kb=main_menu())
    else: await call.answer("❌ Не подписан!", show_alert=True)

@dp.callback_query(F.data == "back_main")
async def cb_back(call):
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, TEXT_MAIN_MENU, kb=main_menu())

@dp.callback_query(F.data == "cmd_list")
async def cb_cmds(call):
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, TEXT_CMD_LIST, kb=back_kb())

@dp.callback_query(F.data == "sub_menu")
async def cb_sub(call):
    uid = call.from_user.id; now = datetime.now()
    cur = await get_subscription(uid)
    status = "❌ не активна"
    if cur and cur > now: status = f"✅ активна до {cur.strftime('%d.%m.%Y')}"
    used = await has_used_trial(uid)
    trial = f"🎁 Пробный период — {TRIAL_DAYS} дней\n\n" if not used else ""
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, f"💎 <b>Подписка</b>\n━━━━━━━━━━━━━━━━━━━━\n📌 Статус: <b>{status}</b>\n\n{trial}👇 <i>Выбери тариф:</i>", kb=plans_kb(uid))

@dp.callback_query(F.data == "trial")
async def cb_trial(call):
    uid = call.from_user.id; now = datetime.now()
    if await has_used_trial(uid): await call.answer("❌ Уже использовал!", show_alert=True); return
    cur = await get_subscription(uid)
    if cur and cur > now: await call.answer("❌ Уже есть!", show_alert=True); return
    await mark_trial_used(uid)
    until = now + timedelta(days=TRIAL_DAYS)
    await set_subscription(uid, until)
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, f"🎁 <b>Пробный активирован!</b>\n━━━━━━━━━━━━━━━━━━━━\n💎 {TRIAL_DAYS} дней\n📅 До: <b>{until.strftime('%d.%m.%Y %H:%M')}</b>\n━━━━━━━━━━━━━━━━━━━━", kb=back_kb())
    await call.answer("✅")

@dp.callback_query(F.data == "ref")
async def cb_ref(call):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{call.from_user.id}"
    inv = len(referrals.get(call.from_user.id, set()))
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, TEXT_REF.format(link=link, count=inv), kb=back_kb())
    await call.answer()

@dp.callback_query(F.data == "howto")
async def cb_howto(call):
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, TEXT_HOWTO, kb=back_kb())
    await call.answer()

@dp.callback_query(F.data.startswith("pay_"))
async def cb_pay(call):
    plan = call.data.split("_")[1]; p = PRICES[plan]
    msg_text = (f"Хочу оплатить подписку по карте!\n📦 Тариф: {p['label']}\n⏳ Срок: {p['days']} дней\n💰 Сумма: {p['rub']}₽\n💱 Валюта: RUB")
    deep_link = f"https://t.me/{OWNER_USERNAME}?text={urllib.parse.quote(msg_text)}"
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="💳 Оплатить картой", url=deep_link)],[types.InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{plan}")],[types.InlineKeyboardButton(text="🔙 Назад", callback_data="sub_menu")]])
    text = (f"💳 <b>Оплата «{p['label']}»</b>\n━━━━━━━━━━━━━━━━━━━━\n📦 Тариф: <b>{p['label']}</b>\n⏳ Срок: <b>{p['days']} дней</b>\n💰 Сумма: <b>{p['rub']}₽</b>\n💱 Валюта: <b>RUB</b>\n━━━━━━━━━━━━━━━━━━━━\n💳 Нажми <b>«Оплатить картой»</b> — откроется чат с @{OWNER_USERNAME} с готовым сообщением.\n\nПосле оплаты нажми «✅ Я оплатил» и пришли скриншот.")
    try: await call.message.delete()
    except: pass
    await send_photo_banner(call.message.chat.id, text, kb=kb)

@dp.callback_query(F.data.startswith("paid_"))
async def cb_paid(call):
    plan = call.data.split("_")[1]
    pending_payments[call.from_user.id] = {"plan": plan}
    await call.message.answer("📸 <b>Пришли скриншот оплаты.</b>", parse_mode="HTML")

@dp.message(F.photo)
async def on_screenshot(message):
    uid = message.from_user.id
    if uid not in pending_payments: return
    plan = pending_payments[uid].get("plan", "1month"); u = message.from_user
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"approve_{u.id}_{plan}")],[types.InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{u.id}")]])
    try:
        await bot.send_photo(chat_id=OWNER_ID, photo=message.photo[-1].file_id,
            caption=f"💰 <b>Оплата</b>\n\n👤 @{u.username or u.first_name} (<code>{u.id}</code>)\n📦 {PRICES[plan]['label']} — {PRICES[plan]['rub']}₽",
            parse_mode="HTML", reply_markup=kb)
        await message.answer("✅ Отправлено!"); pending_payments.pop(uid, None)
    except Exception as e: logging.error(f"screenshot: {e}"); await message.answer("⚠️ Ошибка.")

@dp.callback_query(F.data.startswith("approve_"))
async def cb_approve(call):
    if call.from_user.id != OWNER_ID: await call.answer("❌ Нет доступа", show_alert=True); return
    p = call.data.split("_"); uid = int(p[1]); plan = p[2]
    days = PRICES[plan]["days"]; now = datetime.now()
    cur = await get_subscription(uid) or now
    until = max(cur, now) + timedelta(days=days)
    await set_subscription(uid, until)
    try: await bot.send_message(uid, f"✅ <b>Оплата подтверждена!</b>\n\n💎 {days} дней.\n📅 До: <b>{until.strftime('%d.%m.%Y')}</b>", parse_mode="HTML")
    except: pass
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n✅ <b>Подтверждено</b>", parse_mode="HTML")
    await call.answer("✅")

@dp.callback_query(F.data.startswith("reject_"))
async def cb_reject(call):
    if call.from_user.id != OWNER_ID: await call.answer("❌ Нет доступа", show_alert=True); return
    uid = int(call.data.split("_")[1])
    try: await bot.send_message(uid, "❌ Оплата отклонена.")
    except: pass
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n❌ <b>Отклонено</b>", parse_mode="HTML")
    await call.answer("❌")

@dp.message(F.chat.type == "private", ~F.text.startswith("/"))
async def forward_to_owner(message):
    if message.from_user.id == OWNER_ID: return
    if message.text and message.text.startswith("."): return
    try:
        text = message.text or "[медиа]"; u = message.from_user
        await bot.send_message(OWNER_ID, f"📩 <b>Сообщение</b>\n\n👤 @{u.username or u.first_name} (<code>{u.id}</code>)\n📝 <code>{text[:500]}</code>", parse_mode="HTML")
    except Exception as e: logging.error(f"forward: {e}")

async def main():
    await init_db(); logging.info("✅ БД инициализирована")
    asyncio.create_task(background_name_updater()); logging.info("✅ Апдейтер запущен")
    threading.Thread(target=run_flask, daemon=True).start(); logging.info("✅ Flask запущен")
    await bot.delete_webhook(drop_pending_updates=True); logging.info("✅ Вебхук сброшен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
