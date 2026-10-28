import asyncio
import logging
import sqlite3
import time

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, Message, ReplyKeyboardMarkup,
)

# ====== SOZLAMALAR ======
TOKEN = "8903593516:AAFNtWT0zuCUHGT69ll0_gR66ZlVbFGsqTE"
ADMIN_PASSWORD = "2012"
# ========================

logging.basicConfig(level=logging.INFO)
bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())

PLANS = {"1": ("1 oylik", 30), "3": ("3 oylik", 90), "12": ("1 yillik", 365)}

# ---------- DATABASE ----------
db = sqlite3.connect("kino.db", check_same_thread=False)
db.executescript("""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0, vip_until INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS movies(code TEXT PRIMARY KEY, title TEXT, vip INTEGER, file_id TEXT, ftype TEXT);
CREATE TABLE IF NOT EXISTS prices(plan TEXT PRIMARY KEY, price INTEGER);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, months INTEGER, price INTEGER, ts INTEGER);
CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
""")
for p, v in (("1", 10000), ("3", 25000), ("12", 90000)):
    db.execute("INSERT OR IGNORE INTO prices VALUES(?,?)", (p, v))
db.execute("INSERT OR IGNORE INTO settings VALUES('card','Karta raqami hali kiritilmagan')")
db.execute("INSERT OR IGNORE INTO settings VALUES('admin_username','@admin')")
db.commit()


def q(sql, args=(), one=False, commit=False):
    cur = db.execute(sql, args)
    if commit:
        db.commit()
    return cur.fetchone() if one else cur.fetchall()


def get_setting(key):
    return q("SELECT value FROM settings WHERE key=?", (key,), one=True)[0]


def set_setting(key, value):
    q("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, value), commit=True)


def ensure_user(uid):
    q("INSERT OR IGNORE INTO users(id) VALUES(?)", (uid,), commit=True)


def is_admin(uid):
    return q("SELECT 1 FROM admins WHERE id=?", (uid,), one=True) is not None


def is_vip(uid):
    r = q("SELECT vip_until FROM users WHERE id=?", (uid,), one=True)
    return bool(r and r[0] > time.time())


def price(plan):
    return q("SELECT price FROM prices WHERE plan=?", (plan,), one=True)[0]


def add_vip(uid, days):
    ensure_user(uid)
    cur = q("SELECT vip_until FROM users WHERE id=?", (uid,), one=True)[0]
    new = max(int(time.time()), cur) + days * 86400
    q("UPDATE users SET vip_until=? WHERE id=?", (new, uid), commit=True)
    return new


def fmt_date(ts):
    return time.strftime("%d.%m.%Y", time.localtime(ts))


# ---------- KLAVIATURALAR ----------
BTN_MOVIES = "🎬 Kinolarni ko'rish"
BTN_VIP = "💎 VIP tarif olish"
BTN_ACC = "👤 Hisobim"
BTN_TOPUP = "💳 Hisob to'ldirish"

user_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_MOVIES), KeyboardButton(text=BTN_VIP)],
              [KeyboardButton(text=BTN_ACC), KeyboardButton(text=BTN_TOPUP)]],
    resize_keyboard=True)

A_ADD = "➕ Kino joylash"
A_DEL = "🗑 Kino o'chirish"
A_VIP = "💎 VIP berish"
A_PRICE = "💲 Narx belgilash"
A_TOPUP = "💰 Hisob to'ldirish"
A_ORD = "📦 Zakazlar"
A_CARD = "💳 Karta almashtirish"
A_UNAME = "👤 Admin username almashtirish"
A_EXIT = "🚪 Admin paneldan chiqish"

admin_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=A_ADD), KeyboardButton(text=A_DEL)],
              [KeyboardButton(text=A_VIP), KeyboardButton(text=A_PRICE)],
              [KeyboardButton(text=A_TOPUP), KeyboardButton(text=A_ORD)],
              [KeyboardButton(text=A_CARD), KeyboardButton(text=A_UNAME)],
              [KeyboardButton(text=A_EXIT)]],
    resize_keyboard=True)


def ikb(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])


def plans_kb(prefix, with_price=False):
    rows = []
    for k, (name, _) in PLANS.items():
        label = f"{name} — {price(k)} so'm" if with_price else name
        rows.append([(label, f"{prefix}:{k}")])
    return ikb(rows)


# ---------- HOLATLAR ----------
class AddMovie(StatesGroup):
    kind = State()
    title = State()
    code = State()
    video = State()
    confirm = State()


class DelMovie(StatesGroup):
    code = State()
    confirm = State()


class GiveVip(StatesGroup):
    uid = State()
    plan = State()


class SetPrice(StatesGroup):
    plan = State()
    value = State()


class TopUp(StatesGroup):
    uid = State()
    amount = State()


class ChangeCard(StatesGroup):
    value = State()


class ChangeUname(StatesGroup):
    value = State()


async def send_long(m: Message, text: str):
    for i in range(0, len(text), 3800):
        await m.answer(text[i:i + 3800])


# ---------- START ----------
@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    ensure_user(m.from_user.id)
    await m.answer("Kino kodini kiriting 🎬", reply_markup=user_kb)


# ---------- FOYDALANUVCHI TUGMALARI ----------
@dp.message(F.text == BTN_MOVIES)
async def list_movies(m: Message, state: FSMContext):
    await state.clear()
    rows = q("SELECT title, code, vip FROM movies ORDER BY rowid")
    if not rows:
        return await m.answer("Hozircha kinolar yo'q.")
    text = "🎬 Kinolar ro'yxati:\n\n"
    for title, code, vip in rows:
        text += f"{'💎 VIP' if vip else '🆓'} | {title}\n   Kod: {code}\n\n"
    text += "Kino kodini yozing — kino yuboriladi."
    await send_long(m, text)


@dp.message(F.text == BTN_ACC)
async def account(m: Message, state: FSMContext):
    await state.clear()
    ensure_user(m.from_user.id)
    bal, until = q("SELECT balance, vip_until FROM users WHERE id=?", (m.from_user.id,), one=True)
    vip = f"✅ Faol (tugash: {fmt_date(until)})" if until > time.time() else "❌ Yo'q"
    await m.answer(
        f"👤 ID: {m.from_user.id}\n💰 Hisob: {bal} so'm\n💎 VIP: {vip}\n\n"
        f"Hisobni to'ldirish uchun «{BTN_TOPUP}» tugmasini bosing.")


@dp.message(F.text == BTN_VIP)
async def vip_menu(m: Message, state: FSMContext):
    await state.clear()
    ensure_user(m.from_user.id)
    bal = q("SELECT balance FROM users WHERE id=?", (m.from_user.id,), one=True)[0]
    await m.answer(f"💎 VIP tariflar\n💰 Hisobingiz: {bal} so'm\n\nTarifni tanlang:",
                   reply_markup=plans_kb("buy", True))


@dp.callback_query(F.data.startswith("buy:"))
async def buy(c: CallbackQuery):
    plan = c.data.split(":")[1]
    name, days = PLANS[plan]
    uid = c.from_user.id
    ensure_user(uid)
    cost = price(plan)
    bal = q("SELECT balance FROM users WHERE id=?", (uid,), one=True)[0]
    if bal < cost:
        return await c.answer(f"Hisobingizda mablag' yetarli emas! Kerak: {cost}, bor: {bal}", show_alert=True)
    q("UPDATE users SET balance=balance-? WHERE id=?", (cost, uid), commit=True)
    until = add_vip(uid, days)
    q("INSERT INTO orders(user_id, months, price, ts) VALUES(?,?,?,?)",
      (uid, int(plan), cost, int(time.time())), commit=True)
    await c.message.answer(f"✅ {name} VIP tarif ulandi!\nTugash sanasi: {fmt_date(until)}")
    await c.answer()


# ---------- ADMIN KIRISH ----------
@dp.message(F.text == ADMIN_PASSWORD, StateFilter(None))
async def admin_login(m: Message):
    q("INSERT OR IGNORE INTO admins VALUES(?)", (m.from_user.id,), commit=True)
    await m.answer("🔐 Admin panelga xush kelibsiz!", reply_markup=admin_kb)


@dp.message(F.text == A_EXIT)
async def admin_exit(m: Message, state: FSMContext):
    await state.clear()
    q("DELETE FROM admins WHERE id=?", (m.from_user.id,), commit=True)
    await m.answer("Admin paneldan chiqdingiz.", reply_markup=user_kb)


# ---------- KINO JOYLASH ----------
@dp.message(F.text == A_ADD)
async def add_start(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await state.clear()
    await state.set_state(AddMovie.kind)
    await m.answer("Kino turini tanlang:", reply_markup=ikb([[("💎 VIP", "mt:1"), ("🆓 Oddiy", "mt:0")]]))


@dp.callback_query(AddMovie.kind, F.data.startswith("mt:"))
async def add_kind(c: CallbackQuery, state: FSMContext):
    await state.update_data(vip=int(c.data.split(":")[1]))
    await state.set_state(AddMovie.title)
    await c.message.answer("Kino nomini yozing:")
    await c.answer()


@dp.message(AddMovie.title, F.text)
async def add_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(AddMovie.code)
    await m.answer("Kino kodini yozing:")


@dp.message(AddMovie.code, F.text)
async def add_code(m: Message, state: FSMContext):
    code = m.text.strip()
    if q("SELECT 1 FROM movies WHERE code=?", (code,), one=True):
        return await m.answer("❗ Bu kod band. Boshqa kod yozing:")
    await state.update_data(code=code)
    await state.set_state(AddMovie.video)
    await m.answer("Kinoni (video yoki fayl) yuboring:")


@dp.message(AddMovie.video, F.video | F.document)
async def add_video(m: Message, state: FSMContext):
    if m.video:
        fid, ft = m.video.file_id, "video"
    else:
        fid, ft = m.document.file_id, "document"
    await state.update_data(file_id=fid, ftype=ft)
    d = await state.get_data()
    await state.set_state(AddMovie.confirm)
    await m.answer(
        f"Tekshiring:\nTuri: {'VIP' if d['vip'] else 'Oddiy'}\nNomi: {d['title']}\nKodi: {d['code']}",
        reply_markup=ikb([[("✅ Bajarish", "addok"), ("❌ Bekor qilish", "addno")]]))


@dp.callback_query(AddMovie.confirm, F.data.in_({"addok", "addno"}))
async def add_confirm(c: CallbackQuery, state: FSMContext):
    if c.data == "addok":
        d = await state.get_data()
        q("INSERT INTO movies VALUES(?,?,?,?,?)",
          (d["code"], d["title"], d["vip"], d["file_id"], d["ftype"]), commit=True)
        await c.message.answer("✅ Kino joylandi!")
    else:
        await c.message.answer("Bekor qilindi.")
    await state.clear()
    await c.answer()


# ---------- KINO O'CHIRISH ----------
@dp.message(F.text == A_DEL)
async def del_start(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await state.clear()
    await state.set_state(DelMovie.code)
    await m.answer("Qaysi kinoni o'chirmoqchisiz? Kino kodini yozing:")


@dp.message(DelMovie.code, F.text)
async def del_code(m: Message, state: FSMContext):
    code = m.text.strip()
    r = q("SELECT title FROM movies WHERE code=?", (code,), one=True)
    if not r:
        return await m.answer("❗ Bunday kodli kino topilmadi. Qayta yozing:")
    await state.update_data(code=code)
    await state.set_state(DelMovie.confirm)
    await m.answer(f"«{r[0]}» (kod: {code}) o'chirilsinmi?",
                   reply_markup=ikb([[("✅ Tasdiqlash", "delok"), ("❌ Bekor", "delno")]]))


@dp.callback_query(DelMovie.confirm, F.data.in_({"delok", "delno"}))
async def del_confirm(c: CallbackQuery, state: FSMContext):
    if c.data == "delok":
        d = await state.get_data()
        q("DELETE FROM movies WHERE code=?", (d["code"],), commit=True)
        await c.message.answer("🗑 Kino o'chirildi.")
    else:
        await c.message.answer("Bekor qilindi.")
    await state.clear()
    await c.answer()


# ---------- VIP BERISH ----------
@dp.message(F.text == A_VIP)
async def gv_start(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await state.clear()
    await state.set_state(GiveVip.uid)
    await m.answer("Foydalanuvchi ID sini yozing:")


@dp.message(GiveVip.uid, F.text)
async def gv_uid(m: Message, state: FSMContext):
    if not m.text.strip().isdigit():
        return await m.answer("❗ ID faqat raqam bo'lishi kerak:")
    await state.update_data(uid=int(m.text.strip()))
    await state.set_state(GiveVip.plan)
    await m.answer("Muddatni tanlang:", reply_markup=plans_kb("gv"))


@dp.callback_query(GiveVip.plan, F.data.startswith("gv:"))
async def gv_plan(c: CallbackQuery, state: FSMContext):
    plan = c.data.split(":")[1]
    name, days = PLANS[plan]
    uid = (await state.get_data())["uid"]
    until = add_vip(uid, days)
    q("INSERT INTO orders(user_id, months, price, ts) VALUES(?,?,?,?)",
      (uid, int(plan), 0, int(time.time())), commit=True)
    await c.message.answer(f"✅ {uid} ga {name} VIP berildi (tugash: {fmt_date(until)}).")
    try:
        await bot.send_message(uid, f"🎉 Sizga {name} VIP berildi!\nTugash sanasi: {fmt_date(until)}")
    except Exception:
        pass
    await state.clear()
    await c.answer()


# ---------- NARX BELGILASH ----------
@dp.message(F.text == A_PRICE)
async def sp_start(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await state.clear()
    await state.set_state(SetPrice.plan)
    await m.answer("Qaysi tarif narxini o'zgartirasiz?", reply_markup=plans_kb("sp", True))


@dp.callback_query(SetPrice.plan, F.data.startswith("sp:"))
async def sp_plan(c: CallbackQuery, state: FSMContext):
    await state.update_data(plan=c.data.split(":")[1])
    await state.set_state(SetPrice.value)
    await c.message.answer("Yangi narxni yozing (so'mda):")
    await c.answer()


@dp.message(SetPrice.value, F.text)
async def sp_value(m: Message, state: FSMContext):
    if not m.text.strip().isdigit():
        return await m.answer("❗ Faqat raqam yozing:")
    plan = (await state.get_data())["plan"]
    q("UPDATE prices SET price=? WHERE plan=?", (int(m.text.strip()), plan), commit=True)
    await m.answer(f"✅ {PLANS[plan][0]} tarif narxi {m.text.strip()} so'm qilindi.")
    await state.clear()


# ---------- HISOB TO'LDIRISH ----------
@dp.message(F.text == A_TOPUP)
async def tu_start(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await state.clear()
    await state.set_state(TopUp.uid)
    await m.answer("Foydalanuvchi ID sini yozing:")


@dp.message(TopUp.uid, F.text)
async def tu_uid(m: Message, state: FSMContext):
    if not m.text.strip().isdigit():
        return await m.answer("❗ ID faqat raqam bo'lishi kerak:")
    await state.update_data(uid=int(m.text.strip()))
    await state.set_state(TopUp.amount)
    await m.answer("Necha pul tashlamoqchisiz? (so'mda)")


@dp.message(TopUp.amount, F.text)
async def tu_amount(m: Message, state: FSMContext):
    if not m.text.strip().isdigit():
        return await m.answer("❗ Faqat raqam yozing:")
    amount = int(m.text.strip())
    uid = (await state.get_data())["uid"]
    ensure_user(uid)
    q("UPDATE users SET balance=balance+? WHERE id=?", (amount, uid), commit=True)
    await m.answer(f"✅ {uid} hisobiga {amount} so'm qo'shildi.")
    try:
        await bot.send_message(uid, f"💰 Hisobingiz {amount} so'mga to'ldirildi.")
    except Exception:
        pass
    await state.clear()


# ---------- FOYDALANUVCHI: HISOB TO'LDIRISH ----------
@dp.message(F.text == BTN_TOPUP)
async def user_topup(m: Message, state: FSMContext):
    await state.clear()
    ensure_user(m.from_user.id)
    card = get_setting("card")
    uname = get_setting("admin_username")
    await m.answer(
        "💳 <b>Hisobni to'ldirish</b>\n\n"
        "Quyidagi kartaga pul tashlang:\n"
        f"<code>{card}</code>\n\n"
        f"To'lov qilgach, chekni {uname} ga tashlang va ID raqamingizni yozing:\n"
        f"<code>{m.from_user.id}</code>\n\n"
        "Admin tekshirib, hisobingizni to'ldiradi ✅",
        parse_mode="HTML")


# ---------- ADMIN: KARTA / USERNAME ALMASHTIRISH ----------
@dp.message(F.text == A_CARD)
async def card_start(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await state.clear()
    await state.set_state(ChangeCard.value)
    await m.answer(f"Hozirgi karta: {get_setting('card')}\n\nYangi karta raqamini yozing:")


@dp.message(ChangeCard.value, F.text)
async def card_value(m: Message, state: FSMContext):
    set_setting("card", m.text.strip())
    await m.answer(f"✅ Karta almashtirildi:\n{m.text.strip()}")
    await state.clear()


@dp.message(F.text == A_UNAME)
async def uname_start(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await state.clear()
    await state.set_state(ChangeUname.value)
    await m.answer(f"Hozirgi username: {get_setting('admin_username')}\n\nYangi admin username kiriting (masalan: @username):")


@dp.message(ChangeUname.value, F.text)
async def uname_value(m: Message, state: FSMContext):
    u = m.text.strip()
    if not u.startswith("@"):
        u = "@" + u
    set_setting("admin_username", u)
    await m.answer(f"✅ Admin username almashtirildi: {u}")
    await state.clear()


# ---------- ZAKAZLAR ----------
@dp.message(F.text == A_ORD)
async def orders(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await state.clear()
    rows = q("SELECT user_id, months, price, ts FROM orders ORDER BY id DESC LIMIT 100")
    if not rows:
        return await m.answer("Zakazlar yo'q.")
    text = "📦 VIP zakazlar:\n\n"
    for uid, months, pr, ts in rows:
        text += f"ID: {uid} | {months} oy | {pr} so'm | {fmt_date(ts)}\n"
    await send_long(m, text)


# ---------- KINO KODI (oddiy matn) ----------
@dp.message(F.text, StateFilter(None))
async def by_code(m: Message):
    ensure_user(m.from_user.id)
    r = q("SELECT title, vip, file_id, ftype FROM movies WHERE code=?", (m.text.strip(),), one=True)
    if not r:
        return await m.answer("❌ Bunday kodli kino topilmadi.")
    title, vip, fid, ft = r
    if vip and not is_vip(m.from_user.id):
        return await m.answer("💎 Bu VIP kino. Ko'rish uchun «VIP tarif olish» tugmasini bosing.")
    cap = f"🎬 {title}"
    if ft == "video":
        await m.answer_video(fid, caption=cap)
    else:
        await m.answer_document(fid, caption=cap)


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())