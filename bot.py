import asyncio
import aiosqlite
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, InputMediaPhoto, InputMediaVideo
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "8793552076:AAHE1_NE2NZU8w_xjcEDH9kSOIuEiygdGak"
OWNER_ID = 8032626504
DB_NAME = "video_games_bot.db"
REQUIRED_CHANNEL_ID = -1003969378970
REQUIRED_CHANNEL_LINK = "https://t.me/rezerv_video_pita"
REFERRAL_BONUS = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ==================== БАЗА ДАННЫХ ====================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, diamonds INTEGER DEFAULT 0,
            last_bonus TEXT, is_banned INTEGER DEFAULT 0, is_manager INTEGER DEFAULT 0,
            referrer_id INTEGER DEFAULT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            referral_paid INTEGER DEFAULT 0
        )""")
        # Для существующих БД добавляем колонку, если её нет
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referral_paid INTEGER DEFAULT 0")
        except aiosqlite.OperationalError:
            pass  # колонка уже существует
        await db.execute("""CREATE TABLE IF NOT EXISTS content (
            id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, content_type TEXT, added_by INTEGER
        )""")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_content_type ON content(content_type)")
        await db.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, channel_username TEXT, reward INTEGER DEFAULT 5, is_active INTEGER DEFAULT 1
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, status TEXT DEFAULT 'open'
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER, user_id INTEGER, message TEXT, is_admin INTEGER DEFAULT 0
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS promo_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, diamonds INTEGER, max_uses INTEGER,
            current_uses INTEGER DEFAULT 0, created_by INTEGER
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS packs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, description TEXT, price INTEGER DEFAULT 20,
            is_active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS pack_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pack_id INTEGER, file_id TEXT, content_type TEXT,
            added_by INTEGER, added_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS user_packs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, pack_id INTEGER,
            purchased_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id, pack_id)
        )""")
        await db.commit()

# ==================== FSM ====================
class AdminAddContent(StatesGroup):
    waiting_file = State()
class BulkUpload(StatesGroup):
    uploading = State()
class AdminGiveDiamonds(StatesGroup):
    waiting_user = State()
    waiting_amount = State()
class AdminMassGiveDiamonds(StatesGroup):
    waiting_amount = State()
class AdminBroadcast(StatesGroup):
    waiting_text = State()
class AdminBan(StatesGroup):
    waiting_user_id = State()
class AdminCreatePromo(StatesGroup):
    waiting_code = State()
    waiting_diamonds = State()
    waiting_max_uses = State()
class AdminGiveManager(StatesGroup):
    waiting_user_id = State()
class AdminRemoveManager(StatesGroup):
    waiting_user_id = State()
class AdminViewUser(StatesGroup):
    waiting_user_id = State()
class AdminResetDiamonds(StatesGroup):
    waiting_user_id = State()
class SupportState(StatesGroup):
    waiting_message = State()
class AdminTicketReply(StatesGroup):
    waiting_reply = State()
    ticket_id = State()
class RedeemPromo(StatesGroup):
    waiting_code = State()
class AdminAddTask(StatesGroup):
    waiting_data = State()
class AdminCreatePack(StatesGroup):
    waiting_name = State()
    waiting_desc = State()
    waiting_price = State()
class AdminEditPack(StatesGroup):
    pack_id = State()
    field = State()  # name, desc, price
class AdminPackManage(StatesGroup):
    pack_id = State()
class AdminAddPackContent(StatesGroup):
    pack_id = State()
    content_type = State()  # photo or video
class AdminRemovePackContent(StatesGroup):
    pack_id = State()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ====================
async def get_user_info(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        row = await (await db.execute(
            "SELECT diamonds, is_banned, is_manager, referrer_id FROM users WHERE user_id = ?", (user_id,)
        )).fetchone()
        return {"diamonds": row[0] if row else 0, "is_banned": row[1] if row else 0,
                "is_manager": row[2] if row else 0, "referrer_id": row[3] if row else None}

async def check_banned(user_id: int) -> bool:
    info = await get_user_info(user_id)
    return info["is_banned"] == 1

async def is_admin_or_manager(user_id: int) -> bool:
    if user_id == OWNER_ID: return True
    info = await get_user_info(user_id)
    return info.get("is_manager", 0) == 1

async def get_or_create_user(user_id: int, username: str = None, referrer_id: int = None):
    async with aiosqlite.connect(DB_NAME) as db:
        existing = await (await db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))).fetchone()
        if existing: return
        await db.execute("INSERT INTO users (user_id, username, referrer_id) VALUES (?, ?, ?)", (user_id, username or "", referrer_id))
        await db.commit()

async def give_referral_bonus(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        row = await (await db.execute(
            "SELECT referrer_id, COALESCE(referral_paid, 0) FROM users WHERE user_id = ?", (user_id,)
        )).fetchone()
        if not row or not row[0] or row[1] == 1: return
        await db.execute(
            "UPDATE users SET diamonds = diamonds + ?, referral_paid = 1 WHERE user_id = ?",
            (REFERRAL_BONUS, user_id)
        )
        await db.commit()
        try:
            await bot.send_message(row[0], f"🎉 <b>Новый реферал!</b>\n\n+{REFERRAL_BONUS} 💎")
        except:
            pass

async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Отмена", callback_data="cancel_fsm")]])

@dp.callback_query(F.data == "cancel_fsm")
async def cancel_fsm(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Отменено.", reply_markup=await main_menu(callback.from_user.id))

# ==================== МЕНЮ ====================
async def main_menu(user_id: int):
    info = await get_user_info(user_id)
    keyboard = [
        [InlineKeyboardButton(text="📸 Посмотреть фото (1 💎)", callback_data="watch_photo"),
         InlineKeyboardButton(text="🎥 Посмотреть видео (2 💎)", callback_data="watch_video")],
        [InlineKeyboardButton(text="🎁 Получить бонус (+10 💎)", callback_data="daily_bonus"),
         InlineKeyboardButton(text="📋 Задания", callback_data="tasks")],
        [InlineKeyboardButton(text="📦 Пакеты контента", callback_data="packs_browse"),
         InlineKeyboardButton(text="🎒 Мои паки", callback_data="my_packs")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🛒 Магазин", callback_data="shop")],
        [InlineKeyboardButton(text="🎟 Промокод", callback_data="redeem_promo"),
         InlineKeyboardButton(text="🛠 Поддержка", callback_data="support")],
        [InlineKeyboardButton(text="🎟 Мои тикеты", callback_data="my_tickets"),
         InlineKeyboardButton(text="👥 Реферальная программа", callback_data="my_referrals")]
    ]
    if user_id == OWNER_ID:
        keyboard.append([InlineKeyboardButton(text="🔧 АДМИН-ПАНЕЛЬ", callback_data="admin_menu")])
    elif info["is_manager"] == 1:
        keyboard.append([InlineKeyboardButton(text="🛡️ МЕНЕДЖЕР-ПАНЕЛЬ", callback_data="manager_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Управление паками", callback_data="admin_packs"),
         InlineKeyboardButton(text="📤 Загрузить контент (обычный)", callback_data="admin_add_content")],
        [InlineKeyboardButton(text="📤 МАССОВАЯ ЗАГРУЗКА", callback_data="bulk_upload_start"),
         InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🚫 Бан/Разбан", callback_data="admin_ban"),
         InlineKeyboardButton(text="🎟 Тикеты", callback_data="admin_tickets")],
        [InlineKeyboardButton(text="💎 Выдать алмазики", callback_data="admin_give_diamonds"),
         InlineKeyboardButton(text="💎 Массово алмазики", callback_data="admin_mass_give")],
        [InlineKeyboardButton(text="👑 Менеджеры", callback_data="admin_manager_menu"),
         InlineKeyboardButton(text="📊 Все пользователи", callback_data="admin_all_users")],
        [InlineKeyboardButton(text="🎟 Промокод", callback_data="admin_create_promo"),
         InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])

def manager_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Выдать алмазики", callback_data="manager_give_diamonds"),
         InlineKeyboardButton(text="💎 Массово алмазики", callback_data="manager_mass_give")],
        [InlineKeyboardButton(text="🎟 Тикеты", callback_data="manager_tickets"),
         InlineKeyboardButton(text="🎟 Промокоды", callback_data="manager_promo")],
        [InlineKeyboardButton(text="🚫 Бан/Разбан", callback_data="manager_ban"),
         InlineKeyboardButton(text="📢 Рассылка", callback_data="manager_broadcast")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="manager_stats"),
         InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])

# ==================== ХЕНДЛЕРЫ ====================
@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try: referrer_id = int(args[1][4:])
        except: pass

    await get_or_create_user(user_id, message.from_user.username, referrer_id)

    if await check_banned(user_id):
        await message.answer("🚫 Ты забанен.")
        return

    if not await is_subscribed(user_id):
        text = f"🔒 <b>Подпишись на канал</b>\n\n{REQUIRED_CHANNEL_LINK}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]])
        await message.answer(text, reply_markup=kb)
        return

    await give_referral_bonus(user_id)
    await message.answer("🎮 <b>Video Games Bot</b>", reply_markup=await main_menu(user_id))

@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        await give_referral_bonus(callback.from_user.id)
        await callback.message.edit_text("✅ Спасибо за подписку!", reply_markup=await main_menu(callback.from_user.id))
    else:
        await callback.answer("❌ Ты ещё не подписан!", show_alert=True)

@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    info = await get_user_info(user_id)
    status = "👑 Админ" if user_id == OWNER_ID else ("🛡️ Менеджер" if info["is_manager"] else "👤 Игрок")
    text = f"👤 <b>Профиль</b>\n\n🆔 {user_id}\n💎 Алмазики: <b>{info['diamonds']}</b>\n📌 Статус: <b>{status}</b>"
    await callback.message.edit_text(text, reply_markup=await main_menu(user_id))

@dp.callback_query(F.data == "daily_bonus")
async def daily_bonus(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await check_banned(user_id):
        await callback.answer("🚫 Забанен", show_alert=True)
        return
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_NAME) as db:
        last = (await (await db.execute("SELECT last_bonus FROM users WHERE user_id = ?", (user_id,))).fetchone())[0]
        if last == today:
            await callback.answer("❌ Бонус уже брал сегодня!", show_alert=True)
            return
        await db.execute("UPDATE users SET diamonds = diamonds + 10, last_bonus = ? WHERE user_id = ?", (today, user_id))
        await db.commit()
    await callback.answer("🎁 +10 💎!", show_alert=True)
    await profile(callback)

@dp.callback_query(F.data == "watch_photo")
async def watch_photo(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await check_banned(user_id):
        await callback.answer("🚫 Забанен", show_alert=True)
        return
    info = await get_user_info(user_id)
    if info["diamonds"] < 1:
        await callback.message.edit_text("❌ Нужно 1 💎", reply_markup=await main_menu(user_id))
        return
    async with aiosqlite.connect(DB_NAME) as db:
        content = await (await db.execute("SELECT file_id FROM content WHERE content_type = 'photo' ORDER BY RANDOM() LIMIT 1")).fetchone()
        if not content:
            await callback.answer("❌ Фото нет", show_alert=True)
            return
        await db.execute("UPDATE users SET diamonds = diamonds - 1 WHERE user_id = ?", (user_id,))
        await db.commit()
    await bot.send_photo(user_id, content[0], caption=f"📸 Фото!\n💎 Остаток: {info['diamonds']-1}")
    await bot.send_message(user_id, "Что дальше?", reply_markup=await main_menu(user_id))

@dp.callback_query(F.data == "watch_video")
async def watch_video(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await check_banned(user_id):
        await callback.answer("🚫 Забанен", show_alert=True)
        return
    info = await get_user_info(user_id)
    if info["diamonds"] < 2:
        await callback.message.edit_text("❌ Нужно 2 💎", reply_markup=await main_menu(user_id))
        return
    async with aiosqlite.connect(DB_NAME) as db:
        content = await (await db.execute("SELECT file_id FROM content WHERE content_type = 'video' ORDER BY RANDOM() LIMIT 1")).fetchone()
        if not content:
            await callback.answer("❌ Видео нет", show_alert=True)
            return
        await db.execute("UPDATE users SET diamonds = diamonds - 2 WHERE user_id = ?", (user_id,))
        await db.commit()
    await bot.send_video(user_id, content[0], caption=f"🎥 Видео!\n💎 Остаток: {info['diamonds']-2}")
    await bot.send_message(user_id, "Что дальше?", reply_markup=await main_menu(user_id))

@dp.callback_query(F.data == "tasks")
async def tasks(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        tasks = await (await db.execute("SELECT channel_username, reward FROM tasks WHERE is_active = 1")).fetchall()
    text = "📋 <b>Задания</b>\n" + "\n".join([f"• {t[0]} → +{t[1]} 💎" for t in tasks]) if tasks else "Заданий нет"
    await callback.message.edit_text(text, reply_markup=await main_menu(callback.from_user.id))

@dp.callback_query(F.data == "shop")
async def shop(callback: CallbackQuery):
    await callback.message.edit_text("🛒 Напиши в поддержку для покупки алмазиков.", reply_markup=await main_menu(callback.from_user.id))

@dp.callback_query(F.data == "redeem_promo")
async def redeem_promo_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RedeemPromo.waiting_code)
    await callback.message.edit_text("🎟 Введи промокод:", reply_markup=cancel_keyboard())

@dp.message(RedeemPromo.waiting_code)
async def redeem_promo(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        promo = await (await db.execute("SELECT id, diamonds, max_uses, current_uses FROM promo_codes WHERE code = ?", (code,))).fetchone()
        if not promo or promo[3] >= promo[2]:
            await message.answer("❌ Промокод недействителен!")
            await state.clear()
            return
        await db.execute("UPDATE promo_codes SET current_uses = current_uses + 1 WHERE id = ?", (promo[0],))
        await db.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", (promo[1], user_id))
        await db.commit()
    await message.answer(f"✅ +{promo[1]} 💎 активировано!")
    await state.clear()
    await message.answer("🎮 Меню:", reply_markup=await main_menu(user_id))

@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SupportState.waiting_message)
    await callback.message.edit_text("🛠 Напиши сообщение в поддержку:", reply_markup=cancel_keyboard())

@dp.message(SupportState.waiting_message)
async def support_save(message: Message, state: FSMContext):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("INSERT INTO support_tickets (user_id) VALUES (?) RETURNING id", (user_id,))
        ticket_id = (await cursor.fetchone())[0]
        await db.execute("INSERT INTO support_messages (ticket_id, user_id, message) VALUES (?, ?, ?)", (ticket_id, user_id, message.text))
        await db.commit()
    await message.answer(f"✅ Тикет #{ticket_id} создан!")
    await state.clear()
    await message.answer("🎮 Меню:", reply_markup=await main_menu(user_id))

# ==================== МОИ ТИКЕТЫ ====================
@dp.callback_query(F.data == "my_tickets")
async def my_tickets(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        tickets = await (await db.execute("SELECT id, status FROM support_tickets WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,))).fetchall()
    if not tickets:
        await callback.message.edit_text("🎟 У тебя нет тикетов.", reply_markup=await main_menu(user_id))
        return
    text = "🎟 <b>Твои тикеты</b>\n\n"
    kb_list = []
    for t in tickets:
        emoji = "🟢" if t[1] == "open" else "🔴"
        text += f"{emoji} #{t[0]} — {'Открыт' if t[1]=='open' else 'Закрыт'}\n"
        if t[1] == "open":
            kb_list.append([InlineKeyboardButton(text=f"🔒 Закрыть #{t[0]}", callback_data=f"close_my_ticket_{t[0]}")])
    kb_list.append([InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("close_my_ticket_"))
async def close_my_ticket(callback: CallbackQuery):
    user_id = callback.from_user.id
    ticket_id = int(callback.data.split("_")[3])
    async with aiosqlite.connect(DB_NAME) as db:
        owner = await (await db.execute("SELECT user_id FROM support_tickets WHERE id = ?", (ticket_id,))).fetchone()
        if not owner or owner[0] != user_id:
            await callback.answer("❌ Это не твой тикет!", show_alert=True)
            return
        await db.execute("UPDATE support_tickets SET status = 'closed' WHERE id = ?", (ticket_id,))
        await db.commit()
    await callback.answer("✅ Закрыто")
    await my_tickets(callback)

# ==================== РЕФЕРАЛЬНАЯ ПРОГРАММА ====================
@dp.callback_query(F.data == "my_referrals")
async def my_referrals(callback: CallbackQuery):
    user_id = callback.from_user.id
    ref_link = f"https://t.me/{(await bot.get_me()).username}?start=ref_{user_id}"
    async with aiosqlite.connect(DB_NAME) as db:
        ref_count = (await (await db.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))).fetchone())[0]
    text = f"👥 <b>Реферальная программа</b>\n\nПриглашай друзей и получай <b>+{REFERRAL_BONUS} 💎</b>!\n\n🔗 Твоя ссылка:\n<code>{ref_link}</code>\n👥 Приглашено: <b>{ref_count}</b>"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]]))

# ==================== МАССОВАЯ ЗАГРУЗКА ====================
@dp.callback_query(F.data == "bulk_upload_start")
async def bulk_upload_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(BulkUpload.uploading)
    msg = await callback.message.edit_text(
        "📤 <b>МАССОВАЯ ЗАГРУЗКА АКТИВИРОВАНА</b>\n\n"
        "Кидай фото и видео подряд. Бот будет сохранять всё автоматически.\n\n"
        "Чтобы завершить — напиши <b>/start</b> или нажми кнопку ниже.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Завершить загрузку", callback_data="bulk_upload_finish")]
        ])
    )
    await state.update_data(counter_msg_id=msg.message_id, count=0)

@dp.message(BulkUpload.uploading, F.photo | F.video)
async def bulk_save_content(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    content_type = "photo" if message.photo else "video"
    file_id = message.photo[-1].file_id if message.photo else message.video.file_id
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO content (file_id, content_type, added_by) VALUES (?, ?, ?)", 
                         (file_id, content_type, message.from_user.id))
        await db.commit()
    
    data = await state.get_data()
    new_count = data.get("count", 0) + 1
    await state.update_data(count=new_count)
    
    try:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=data["counter_msg_id"],
            text=f"📤 <b>МАССОВАЯ ЗАГРУЗКА</b>\n\nСохранено: <b>{new_count}</b> файлов\nТип последнего: {content_type}\n\nПродолжай кидать контент или напиши /start для выхода.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Завершить загрузку", callback_data="bulk_upload_finish")]
            ])
        )
    except:
        pass
    await asyncio.sleep(0.75)

@dp.callback_query(F.data == "bulk_upload_finish")
async def bulk_upload_finish(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    count = data.get("count", 0)
    await state.clear()
    await callback.message.edit_text(
        f"✅ <b>Загрузка завершена!</b>\n\nВсего сохранено: <b>{count}</b> файлов.",
        reply_markup=admin_menu()
    )

@dp.message(CommandStart(), BulkUpload.uploading)
async def exit_bulk_upload(message: Message, state: FSMContext):
    data = await state.get_data()
    count = data.get("count", 0)
    await state.clear()
    await message.answer(
        f"✅ <b>Массовый режим завершён.</b>\n\nСохранено: <b>{count}</b> файлов.",
        reply_markup=await main_menu(message.from_user.id)
    )

# ==================== АДМИН ====================
@dp.callback_query(F.data == "admin_menu")
async def admin_menu_handler(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    await callback.message.edit_text("🔧 <b>АДМИН-ПАНЕЛЬ</b>", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_add_content")
async def admin_add_content(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminAddContent.waiting_file)
    await callback.message.edit_text("📤 Кидай фото или видео:", reply_markup=cancel_keyboard())

@dp.message(AdminAddContent.waiting_file, F.photo | F.video)
async def save_content(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    content_type = "photo" if message.photo else "video"
    file_id = message.photo[-1].file_id if message.photo else message.video.file_id
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO content (file_id, content_type, added_by) VALUES (?, ?, ?)", (file_id, content_type, message.from_user.id))
        await db.commit()
    await message.answer(f"✅ {content_type.capitalize()} успешно сохранено!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в админ-панель", callback_data="admin_menu")]
    ]))
    await state.clear()

@dp.callback_query(F.data == "admin_tasks")
async def admin_tasks(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        tasks = await (await db.execute("SELECT id, channel_username, reward FROM tasks WHERE is_active = 1")).fetchall()
    text = "📋 <b>Задания</b>\n" + "\n".join([f"#{t[0]} | {t[1]} → +{t[2]} 💎" for t in tasks]) if tasks else "Заданий нет"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add_task"),
         InlineKeyboardButton(text="🗑 Удалить", callback_data="admin_delete_task")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data == "admin_add_task")
async def admin_add_task_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminAddTask.waiting_data)
    await callback.message.edit_text("➕ Введи: @канал награда", reply_markup=cancel_keyboard())

@dp.message(AdminAddTask.waiting_data)
async def admin_add_task_save(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    try:
        ch, rew = message.text.split()
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT INTO tasks (channel_username, reward) VALUES (?, ?)", (ch, int(rew)))
            await db.commit()
        await message.answer("✅ Задание добавлено!")
    except:
        await message.answer("❌ Неверный формат")
    await state.clear()
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_delete_task")
async def admin_delete_task(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        tasks = await (await db.execute("SELECT id, channel_username FROM tasks WHERE is_active = 1")).fetchall()
    if not tasks:
        await callback.answer("Нет заданий", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🗑 #{t[0]} {t[1]}", callback_data=f"delete_task_{t[0]}")] for t in tasks
    ] + [[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_tasks")]])
    await callback.message.edit_text("Выбери для удаления:", reply_markup=kb)

@dp.callback_query(F.data.startswith("delete_task_"))
async def delete_task_confirm(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    task_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tasks SET is_active = 0 WHERE id = ?", (task_id,))
        await db.commit()
    await callback.answer("✅ Удалено")
    await admin_tasks(callback)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        total = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        content = (await (await db.execute("SELECT COUNT(*) FROM content")).fetchone())[0]
        diamonds = (await (await db.execute("SELECT SUM(diamonds) FROM users")).fetchone())[0] or 0
        managers = (await (await db.execute("SELECT COUNT(*) FROM users WHERE is_manager=1")).fetchone())[0]
        open_tickets = (await (await db.execute("SELECT COUNT(*) FROM support_tickets WHERE status='open'")).fetchone())[0]
    text = f"📊 <b>Статистика</b>\n👥 {total} | 🛡️ {managers} менеджеров\n📸 {content} контента\n💎 {diamonds} алмазиков\n🎟 {open_tickets} тикетов"
    await callback.message.edit_text(text, reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_all_users")
async def admin_all_users(callback: CallbackQuery, page: int = 0):
    if callback.from_user.id != OWNER_ID: return
    USERS_PER_PAGE = 50
    offset = page * USERS_PER_PAGE
    async with aiosqlite.connect(DB_NAME) as db:
        users = await (await db.execute(
            "SELECT user_id, username, diamonds, is_banned, is_manager FROM users ORDER BY user_id DESC LIMIT ? OFFSET ?",
            (USERS_PER_PAGE, offset)
        )).fetchall()
        total = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
    total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    
    if not users:
        text = "👥 Нет пользователей"
        kb = admin_menu()
    else:
        text = f"👥 <b>Все пользователи</b> (стр. {page+1}/{total_pages})\n\n"
        for u in users:
            status = "🚫" if u[3] else ("🛡️" if u[4] else "👤")
            text += f"{status} {u[0]} | @{u[1] or 'нет'} | 💎 {u[2]}\n"
        
        kb_list = []
        for u in users:
            kb_list.append([InlineKeyboardButton(text=f"👤 {u[0]}", callback_data=f"view_user_{u[0]}")])
        
        nav = []
        if page > 0: nav.append(InlineKeyboardButton(text="◀️", callback_data=f"all_users_page_{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages-1: nav.append(InlineKeyboardButton(text="▶️", callback_data=f"all_users_page_{page+1}"))
        if nav: kb_list.append(nav)
        kb_list.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_list)
    
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("all_users_page_"))
async def all_users_page(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    page = int(callback.data.split("_")[3])
    await admin_all_users(callback, page)

@dp.callback_query(F.data.startswith("view_user_"))
async def view_user_from_list(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    uid = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        row = await (await db.execute(
            "SELECT user_id, username, diamonds, is_banned, is_manager, referrer_id, created_at FROM users WHERE user_id = ?", (uid,)
        )).fetchone()
        if not row:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        ref_count = (await (await db.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (uid,))).fetchone())[0]
        text = f"👤 <b>Пользователь {uid}</b>\n\n💎 Алмазики: <b>{row[2]}</b>\n🚫 Забанен: {'Да' if row[3] else 'Нет'}\n🛡️ Менеджер: {'Да' if row[4] else 'Нет'}\n👥 Рефералов: <b>{ref_count}</b>"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Обнулить алмазики", callback_data=f"reset_diamonds_{uid}")],
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="admin_all_users")]
    ]))

@dp.callback_query(F.data.startswith("reset_diamonds_"))
async def reset_diamonds_confirm(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    uid = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET diamonds = 0 WHERE user_id = ?", (uid,))
        await db.commit()
    await callback.answer("✅ Алмазики обнулены!", show_alert=True)
    await admin_all_users(callback)

@dp.callback_query(F.data == "admin_view_user")
async def admin_view_user_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminViewUser.waiting_user_id)
    await callback.message.edit_text("Введи ID пользователя:", reply_markup=cancel_keyboard())

@dp.message(AdminViewUser.waiting_user_id)
async def admin_view_user(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    try:
        uid = int(message.text)
        async with aiosqlite.connect(DB_NAME) as db:
            row = await (await db.execute(
                "SELECT user_id, username, diamonds, is_banned, is_manager, referrer_id, created_at FROM users WHERE user_id = ?", (uid,)
            )).fetchone()
            if not row:
                await message.answer("❌ Пользователь не найден")
                await state.clear()
                return
            ref_count = (await (await db.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (uid,))).fetchone())[0]
            text = f"👤 <b>Статистика</b>\n\n🆔 {row[0]}\n👤 @{row[1] or 'нет'}\n💎 Алмазики: <b>{row[2]}</b>\n🚫 Забанен: {'Да' if row[3] else 'Нет'}\n🛡️ Менеджер: {'Да' if row[4] else 'Нет'}\n👥 Рефералов: <b>{ref_count}</b>"
        await message.answer(text)
    except:
        await message.answer("❌ Ошибка")
    await state.clear()
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_mass_give")
async def admin_mass_give_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID and not await is_admin_or_manager(callback.from_user.id): return
    await state.set_state(AdminMassGiveDiamonds.waiting_amount)
    await callback.message.edit_text("💎 Введи количество для всех:", reply_markup=cancel_keyboard())

@dp.message(AdminMassGiveDiamonds.waiting_amount)
async def admin_mass_give(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    try:
        amount = int(message.text)
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET diamonds = diamonds + ? WHERE is_banned=0", (amount,))
            await db.commit()
        await message.answer(f"✅ +{amount} 💎 выдано всем!")
    except:
        await message.answer("❌ Ошибка")
    await state.clear()
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_manager_menu")
async def admin_manager_menu(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    await callback.message.edit_text("👑 <b>Управление менеджерами</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выдать статус", callback_data="admin_give_manager"),
         InlineKeyboardButton(text="❌ Снять статус", callback_data="admin_remove_manager")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
    ]))

@dp.callback_query(F.data == "admin_give_manager")
async def admin_give_manager_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminGiveManager.waiting_user_id)
    await callback.message.edit_text("Введи ID для выдачи статуса менеджера:", reply_markup=cancel_keyboard())

@dp.message(AdminGiveManager.waiting_user_id)
async def admin_give_manager(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    try:
        uid = int(message.text)
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET is_manager=1 WHERE user_id=?", (uid,))
            await db.commit()
        await message.answer(f"✅ {uid} теперь менеджер!")
        try: await bot.send_message(uid, "🎉 Тебе выдали статус Менеджера!")
        except: pass
    except:
        await message.answer("❌ Ошибка")
    await state.clear()
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_remove_manager")
async def admin_remove_manager_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminRemoveManager.waiting_user_id)
    await callback.message.edit_text("Введи ID для снятия статуса менеджера:", reply_markup=cancel_keyboard())

@dp.message(AdminRemoveManager.waiting_user_id)
async def admin_remove_manager(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    try:
        uid = int(message.text)
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET is_manager=0 WHERE user_id=?", (uid,))
            await db.commit()
        await message.answer(f"✅ Статус снят у {uid}")
    except:
        await message.answer("❌ Ошибка")
    await state.clear()
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

# ==================== ТИКЕТЫ С ПРОСМОТРОМ ====================
TICKETS_PER_PAGE = 5

@dp.callback_query(F.data == "admin_tickets")
async def admin_tickets(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID and not await is_admin_or_manager(callback.from_user.id): return
    is_mgr = await is_admin_or_manager(callback.from_user.id) and callback.from_user.id != OWNER_ID
    await show_tickets_page(callback.message, 0, is_manager=is_mgr)

@dp.callback_query(F.data == "manager_tickets")
async def manager_tickets(callback: CallbackQuery):
    if not await is_admin_or_manager(callback.from_user.id): return
    await show_tickets_page(callback.message, 0, is_manager=True)

async def show_tickets_page(message, page: int = 0, is_manager: bool = False):
    offset = page * TICKETS_PER_PAGE
    async with aiosqlite.connect(DB_NAME) as db:
        tickets = await (await db.execute(
            "SELECT id, user_id FROM support_tickets WHERE status='open' ORDER BY id DESC LIMIT ? OFFSET ?",
            (TICKETS_PER_PAGE, offset)
        )).fetchall()
        total = (await (await db.execute("SELECT COUNT(*) FROM support_tickets WHERE status='open'")).fetchone())[0]
    total_pages = max(1, (total + TICKETS_PER_PAGE - 1) // TICKETS_PER_PAGE)
    
    back_cb = "manager_menu" if is_manager else "admin_menu"
    back_text = "◀️ Назад в менеджер" if is_manager else "◀️ Назад в админ"
    if not tickets:
        text = "🎟 Нет активных тикетов"
        kb = manager_menu() if is_manager else admin_menu()
    else:
        text = f"🎟 <b>Активные тикеты</b> (стр. {page+1}/{total_pages})\n\nНажми на тикет, чтобы прочитать сообщения."
        kb_list = []
        for t in tickets:
            kb_list.append([InlineKeyboardButton(text=f"#{t[0]} | Пользователь {t[1]}", callback_data=f"view_ticket_{t[0]}")])
        nav = []
        if page > 0: nav.append(InlineKeyboardButton(text="◀️", callback_data=f"tickets_page_{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages-1: nav.append(InlineKeyboardButton(text="▶️", callback_data=f"tickets_page_{page+1}"))
        if nav: kb_list.append(nav)
        kb_list.append([InlineKeyboardButton(text=back_text, callback_data=back_cb)])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_list)
    await message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("tickets_page_"))
async def tickets_page(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID and not await is_admin_or_manager(callback.from_user.id): return
    page = int(callback.data.split("_")[2])
    is_mgr = await is_admin_or_manager(callback.from_user.id) and callback.from_user.id != OWNER_ID
    await show_tickets_page(callback.message, page, is_manager=is_mgr)

@dp.callback_query(F.data.startswith("view_ticket_"))
async def view_ticket(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID and not await is_admin_or_manager(callback.from_user.id): return
    ticket_id = int(callback.data.split("_")[2])
    
    async with aiosqlite.connect(DB_NAME) as db:
        messages = await (await db.execute(
            "SELECT user_id, message, is_admin FROM support_messages WHERE ticket_id = ? ORDER BY id ASC LIMIT 12",
            (ticket_id,)
        )).fetchall()
        user_id = (await (await db.execute("SELECT user_id FROM support_tickets WHERE id = ?", (ticket_id,))).fetchone())[0]
    
    if not messages:
        text = f"🎟 <b>Тикет #{ticket_id}</b> (Пользователь {user_id})\n\nСообщений пока нет."
    else:
        text = f"🎟 <b>Тикет #{ticket_id}</b> (Пользователь {user_id})\n\n"
        for msg in messages:
            prefix = "👤 Пользователь:" if msg[2] == 0 else "🛡️ Админ:"
            text += f"{prefix} {msg[1][:80]}{'...' if len(msg[1]) > 80 else ''}\n\n"
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Ответить", callback_data=f"reply_ticket_{ticket_id}")],
        [InlineKeyboardButton(text="🔒 Закрыть тикет", callback_data=f"close_ticket_{ticket_id}")],
        [InlineKeyboardButton(text="◀️ Назад к тикетам", callback_data="admin_tickets")]
    ]))

@dp.callback_query(F.data.startswith("close_ticket_"))
async def close_ticket_admin(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID and not await is_admin_or_manager(callback.from_user.id): return
    ticket_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        user_id = (await (await db.execute("SELECT user_id FROM support_tickets WHERE id=?", (ticket_id,))).fetchone())[0]
        await db.execute("UPDATE support_tickets SET status='closed' WHERE id=?", (ticket_id,))
        await db.commit()
    try:
        await bot.send_message(user_id, f"🔒 Тикет #{ticket_id} закрыт администратором.")
    except:
        pass
    await callback.answer("✅ Тикет закрыт")
    await show_tickets_page(callback.message, 0)

@dp.callback_query(F.data.startswith("reply_ticket_"))
async def reply_ticket_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID and not await is_admin_or_manager(callback.from_user.id): return
    ticket_id = int(callback.data.split("_")[2])
    await state.set_state(AdminTicketReply.waiting_reply)
    await state.update_data(ticket_id=ticket_id)
    async with aiosqlite.connect(DB_NAME) as db:
        user_id = (await (await db.execute("SELECT user_id FROM support_tickets WHERE id=?", (ticket_id,))).fetchone())[0]
    try:
        await bot.send_message(user_id, f"🛠 Агент взял тикет #{ticket_id} в работу.")
    except:
        pass
    await callback.message.edit_text(f"✍️ Напиши ответ на тикет #{ticket_id}:", reply_markup=cancel_keyboard())

@dp.message(AdminTicketReply.waiting_reply)
async def reply_ticket_send(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    data = await state.get_data()
    ticket_id = data["ticket_id"]
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO support_messages (ticket_id, user_id, message, is_admin) VALUES (?, ?, ?, 1)", 
                         (ticket_id, message.from_user.id, message.text))
        user_id = (await (await db.execute("SELECT user_id FROM support_tickets WHERE id=?", (ticket_id,))).fetchone())[0]
        await db.commit()
    try:
        await bot.send_message(user_id, f"📩 Ответ (тикет #{ticket_id}):\n\n{message.text}")
    except:
        pass
    await message.answer("✅ Ответ отправлен!")
    await state.clear()
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

# ==================== МЕНЕДЖЕРСКАЯ ПАНЕЛЬ ====================
@dp.callback_query(F.data == "manager_menu")
async def manager_menu_handler(callback: CallbackQuery):
    if not await is_admin_or_manager(callback.from_user.id):
        await callback.answer("❌ Нет прав!", show_alert=True)
        return
    await callback.message.edit_text("🛡️ <b>МЕНЕДЖЕР-ПАНЕЛЬ</b>", reply_markup=manager_menu())

@dp.callback_query(F.data == "manager_give_diamonds")
async def manager_give_diamonds(callback: CallbackQuery, state: FSMContext):
    if not await is_admin_or_manager(callback.from_user.id): return
    await state.set_state(AdminGiveDiamonds.waiting_user)
    await callback.message.edit_text("💎 Введи ID пользователя:", reply_markup=cancel_keyboard())

@dp.callback_query(F.data == "manager_mass_give")
async def manager_mass_give(callback: CallbackQuery, state: FSMContext):
    if not await is_admin_or_manager(callback.from_user.id): return
    await state.set_state(AdminMassGiveDiamonds.waiting_amount)
    await callback.message.edit_text("💎 Введи количество для всех:", reply_markup=cancel_keyboard())

@dp.callback_query(F.data == "manager_promo")
async def manager_promo(callback: CallbackQuery, state: FSMContext):
    if not await is_admin_or_manager(callback.from_user.id): return
    await state.set_state(AdminCreatePromo.waiting_code)
    await callback.message.edit_text("🎟 Введи код промокода:", reply_markup=cancel_keyboard())

@dp.callback_query(F.data == "manager_ban")
async def manager_ban(callback: CallbackQuery, state: FSMContext):
    if not await is_admin_or_manager(callback.from_user.id): return
    await state.set_state(AdminBan.waiting_user_id)
    await callback.message.edit_text("🚫 Введи ID:", reply_markup=cancel_keyboard())

@dp.callback_query(F.data == "manager_broadcast")
async def manager_broadcast(callback: CallbackQuery, state: FSMContext):
    if not await is_admin_or_manager(callback.from_user.id): return
    await state.set_state(AdminBroadcast.waiting_text)
    await callback.message.edit_text("📢 Текст рассылки:", reply_markup=cancel_keyboard())

@dp.callback_query(F.data == "manager_stats")
async def manager_stats(callback: CallbackQuery):
    if not await is_admin_or_manager(callback.from_user.id): return
    async with aiosqlite.connect(DB_NAME) as db:
        total = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        open_tickets = (await (await db.execute("SELECT COUNT(*) FROM support_tickets WHERE status='open'")).fetchone())[0]
    await callback.message.edit_text(f"📊 Пользователей: {total}\n🎟 Тикетов: {open_tickets}", reply_markup=manager_menu())

# ==================== ОБЩИЕ ХЕНДЛЕРЫ ====================
@dp.callback_query(F.data == "admin_give_diamonds")
async def admin_give_diamonds(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminGiveDiamonds.waiting_user)
    await callback.message.edit_text("💎 Введи ID пользователя:", reply_markup=cancel_keyboard())

@dp.message(AdminGiveDiamonds.waiting_user)
async def give_diamonds_user(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID and not await is_admin_or_manager(message.from_user.id): return
    try:
        await state.update_data(user_id=int(message.text))
        await state.set_state(AdminGiveDiamonds.waiting_amount)
        await message.answer("Сколько алмазиков?", reply_markup=cancel_keyboard())
    except:
        await message.answer("❌ Неверный ID")

@dp.message(AdminGiveDiamonds.waiting_amount)
async def give_diamonds_amount(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id != OWNER_ID and not await is_admin_or_manager(user_id): return
    try:
        amount = int(message.text)
        data = await state.get_data()
        target = data["user_id"]
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", (amount, target))
            await db.commit()
        await message.answer(f"✅ +{amount} 💎 пользователю {target}")
        try: await bot.send_message(target, f"🎉 +{amount} 💎!")
        except: pass
    except:
        await message.answer("❌ Ошибка")
    await state.clear()
    if user_id == OWNER_ID:
        await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())
    else:
        await message.answer("🛡️ Менеджер-панель:", reply_markup=manager_menu())

@dp.callback_query(F.data == "admin_ban")
async def admin_ban(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminBan.waiting_user_id)
    await callback.message.edit_text("🚫 Введи ID:", reply_markup=cancel_keyboard())

@dp.message(AdminBan.waiting_user_id)
async def do_ban(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID and not await is_admin_or_manager(message.from_user.id): return
    try:
        uid = int(message.text)
        async with aiosqlite.connect(DB_NAME) as db:
            row = await (await db.execute("SELECT is_banned FROM users WHERE user_id=?", (uid,))).fetchone()
            if row:
                new = 0 if row[0] == 1 else 1
                await db.execute("UPDATE users SET is_banned=? WHERE user_id=?", (new, uid))
                await db.commit()
                await message.answer(f"✅ {uid} {'разбанен' if new==0 else 'забанен'}")
    except:
        await message.answer("❌ Ошибка")
    await state.clear()
    if message.from_user.id == OWNER_ID:
        await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())
    else:
        await message.answer("🛡️ Менеджер-панель:", reply_markup=manager_menu())

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminBroadcast.waiting_text)
    await callback.message.edit_text("📢 Текст рассылки:", reply_markup=cancel_keyboard())

@dp.message(AdminBroadcast.waiting_text)
async def do_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID and not await is_admin_or_manager(message.from_user.id): return
    async with aiosqlite.connect(DB_NAME) as db:
        users = await (await db.execute("SELECT user_id FROM users WHERE is_banned=0")).fetchall()
    count = 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, f"📢 Сообщение:\n\n{message.text}")
            count += 1
            await asyncio.sleep(0.03)
        except: pass
    await message.answer(f"✅ Разослано {count}")
    await state.clear()
    if message.from_user.id == OWNER_ID:
        await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())
    else:
        await message.answer("🛡️ Менеджер-панель:", reply_markup=manager_menu())

@dp.callback_query(F.data == "admin_create_promo")
async def admin_create_promo(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID and not await is_admin_or_manager(callback.from_user.id): return
    await state.set_state(AdminCreatePromo.waiting_code)
    await callback.message.edit_text("🎟 Код промокода:", reply_markup=cancel_keyboard())

@dp.message(AdminCreatePromo.waiting_code)
async def create_promo_code(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    await state.update_data(code=message.text.strip().upper())
    await state.set_state(AdminCreatePromo.waiting_diamonds)
    await message.answer("Сколько алмазиков?", reply_markup=cancel_keyboard())

@dp.message(AdminCreatePromo.waiting_diamonds)
async def create_promo_diamonds(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    await state.update_data(diamonds=int(message.text))
    await state.set_state(AdminCreatePromo.waiting_max_uses)
    await message.answer("Макс. использований?", reply_markup=cancel_keyboard())

@dp.message(AdminCreatePromo.waiting_max_uses)
async def create_promo_max_uses(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID and not await is_admin_or_manager(message.from_user.id): return
    data = await state.get_data()
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT INTO promo_codes (code, diamonds, max_uses, created_by) VALUES (?, ?, ?, ?)", 
                             (data["code"], data["diamonds"], int(message.text), message.from_user.id))
            await db.commit()
        await message.answer(f"✅ Промокод {data['code']} создан!")
    except aiosqlite.IntegrityError:
        await message.answer("❌ Такой код уже есть!")
    await state.clear()
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text("🎮 <b>Video Games Bot</b>", reply_markup=await main_menu(callback.from_user.id))

# ==================== ПАКИ КОНТЕНТА ====================
async def show_pack_manage(chat_id: int, pack_id: int):
    """Helper to show pack management menu"""
    async with aiosqlite.connect(DB_NAME) as db:
        pack = await (await db.execute("SELECT id, name, description, price, is_active FROM packs WHERE id=?", (pack_id,))).fetchone()
        content_count = (await (await db.execute("SELECT COUNT(*) FROM pack_content WHERE pack_id=?", (pack_id,))).fetchone())[0]
    if not pack:
        return
    status = "✅ Активен" if pack[4] else "❌ Неактивен"
    text = f"📦 <b>Пак #{pack[0]}: {pack[1]}</b>\n\n💰 Цена: {pack[3]} 💎\n📝 Описание: {pack[2] or '—'}\n📊 Контента: {content_count} шт.\nСтатус: {status}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить название", callback_data=f"edit_pack_name_{pack_id}"),
         InlineKeyboardButton(text="✏️ Изменить цену", callback_data=f"edit_pack_price_{pack_id}")],
        [InlineKeyboardButton(text="✏️ Изменить описание", callback_data=f"edit_pack_desc_{pack_id}"),
         InlineKeyboardButton(text="🔄 Переключить активность", callback_data=f"toggle_pack_{pack_id}")],
        [InlineKeyboardButton(text="➕ Добавить фото", callback_data=f"add_pack_photo_{pack_id}"),
         InlineKeyboardButton(text="➕ Добавить видео", callback_data=f"add_pack_video_{pack_id}")],
        [InlineKeyboardButton(text="📋 Управление контентом", callback_data=f"list_pack_content_{pack_id}")],
        [InlineKeyboardButton(text="🗑 Удалить пак", callback_data=f"delete_pack_{pack_id}")],
        [InlineKeyboardButton(text="◀️ Назад к пакам", callback_data="admin_packs")]
    ])
    await bot.send_message(chat_id, text, reply_markup=kb)

# User handlers for packs
@dp.callback_query(F.data == "packs_browse")
async def packs_browse(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await check_banned(user_id):
        await callback.answer("🚫 Забанен", show_alert=True)
        return
    async with aiosqlite.connect(DB_NAME) as db:
        packs = await (await db.execute("SELECT id, name, description, price FROM packs WHERE is_active=1 ORDER BY id DESC")).fetchall()
    if not packs:
        await callback.message.edit_text("📦 Пакетов пока нет.", reply_markup=await main_menu(user_id))
        return
    text = "📦 <b>Доступные пакеты контента</b>\n\nВыберите пак для покупки (разовый платёж, контент ваш навсегда):\n"
    kb_list = []
    for p in packs:
        desc = (p[2] or "")[:60] + "..." if p[2] and len(p[2]) > 60 else (p[2] or "Без описания")
        text += f"\n• <b>{p[1]}</b> — {p[3]} 💎\n  {desc}\n"
        kb_list.append([InlineKeyboardButton(text=f"🛒 Купить «{p[1]}» ({p[3]}💎)", callback_data=f"buy_pack_{p[0]}")])
    kb_list.append([InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("buy_pack_"))
async def buy_pack(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await check_banned(user_id):
        await callback.answer("🚫 Забанен", show_alert=True)
        return
    pack_id = int(callback.data.split("_")[2])
    info = await get_user_info(user_id)
    async with aiosqlite.connect(DB_NAME) as db:
        pack = await (await db.execute("SELECT price, name FROM packs WHERE id=? AND is_active=1", (pack_id,))).fetchone()
        if not pack:
            await callback.answer("❌ Пак не найден или неактивен!", show_alert=True)
            return
        price = pack[0]
        if info["diamonds"] < price:
            await callback.answer(f"❌ Нужно минимум {price} 💎", show_alert=True)
            return
        owned = await (await db.execute("SELECT 1 FROM user_packs WHERE user_id=? AND pack_id=?", (user_id, pack_id))).fetchone()
        if owned:
            await callback.answer("✅ У вас уже есть этот пак!", show_alert=True)
            return
        await db.execute("UPDATE users SET diamonds = diamonds - ? WHERE user_id = ?", (price, user_id))
        await db.execute("INSERT INTO user_packs (user_id, pack_id) VALUES (?, ?)", (user_id, pack_id))
        await db.commit()
    await callback.answer(f"✅ Пак «{pack[1]}» куплен за {price} 💎! Проверьте в 'Мои паки'", show_alert=True)
    await callback.message.edit_text("🎒 Перейдите в «Мои паки» чтобы открыть контент.", reply_markup=await main_menu(user_id))

@dp.callback_query(F.data == "my_packs")
async def my_packs(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        packs = await (await db.execute("""
            SELECT p.id, p.name, p.description, p.price, up.purchased_at 
            FROM user_packs up JOIN packs p ON up.pack_id = p.id 
            WHERE up.user_id = ? ORDER BY up.purchased_at DESC
        """, (user_id,))).fetchall()
    if not packs:
        await callback.message.edit_text("🎒 У вас пока нет купленных паков.\n\nКупите в разделе «Пакеты контента»", reply_markup=await main_menu(user_id))
        return
    text = "🎒 <b>Ваши паки</b>\n\n"
    kb_list = []
    for p in packs:
        text += f"• <b>{p[1]}</b> (куплен {p[4][:10]})\n"
        kb_list.append([InlineKeyboardButton(text=f"📂 Открыть «{p[1]}»", callback_data=f"open_pack_{p[0]}")])
    kb_list.append([InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("open_pack_"))
async def open_pack(callback: CallbackQuery):
    user_id = callback.from_user.id
    pack_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        pack = await (await db.execute("SELECT name, description FROM packs WHERE id=?", (pack_id,))).fetchone()
        owns = await (await db.execute("SELECT 1 FROM user_packs WHERE user_id=? AND pack_id=?", (user_id, pack_id))).fetchone()
    if not owns or not pack:
        await callback.answer("❌ Нет доступа к этому паку", show_alert=True)
        return
    text = f"📦 <b>{pack[0]}</b>\n\n{pack[1] or 'Описание отсутствует.'}\n\nКонтент доступен бесплатно и навсегда!"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎞 Посмотреть весь контент", callback_data=f"view_pack_content_{pack_id}")],
        [InlineKeyboardButton(text="◀️ Назад к моим пакам", callback_data="my_packs")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("view_pack_content_"))
async def view_pack_content(callback: CallbackQuery):
    user_id = callback.from_user.id
    pack_id = int(callback.data.split("_")[3])
    async with aiosqlite.connect(DB_NAME) as db:
        owns = await (await db.execute("SELECT 1 FROM user_packs WHERE user_id=? AND pack_id=?", (user_id, pack_id))).fetchone()
        contents = await (await db.execute("SELECT file_id, content_type FROM pack_content WHERE pack_id=? ORDER BY id ASC", (pack_id,))).fetchall()
        pack_name = (await (await db.execute("SELECT name FROM packs WHERE id=?", (pack_id,))).fetchone())[0]
    if not owns:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    if not contents:
        await callback.answer("📭 В паке пока нет контента", show_alert=True)
        return
    await callback.answer(f"📤 Отправляю {len(contents)} файлов в альбомах...", show_alert=True)
    media_items = []
    for file_id, ctype in contents:
        if ctype == "photo":
            media = InputMediaPhoto(media=file_id, caption=f"📸 Из пака: {pack_name}")
        elif ctype == "video":
            media = InputMediaVideo(media=file_id, caption=f"🎥 Из пака: {pack_name}")
        else:
            continue
        media_items.append(media)
    # Отправляем батчами по 10 (поддерживает 50+ контента без спама и флуда)
    sent = 0
    for i in range(0, len(media_items), 10):
        batch = media_items[i:i+10]
        try:
            await bot.send_media_group(user_id, batch)
            sent += len(batch)
            await asyncio.sleep(0.5)  # защита от flood
        except Exception as e:
            logger.warning(f"Failed to send media group for pack {pack_id}: {e}")
    await bot.send_message(user_id, f"✅ Просмотрено {sent} файлов из пака «{pack_name}»!", reply_markup=await main_menu(user_id))

# Admin packs management
@dp.callback_query(F.data == "admin_packs")
async def admin_packs(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        packs = await (await db.execute("SELECT id, name, price, is_active FROM packs ORDER BY id DESC")).fetchall()
    text = "📦 <b>Управление паками контента</b>\n\nЗдесь вы можете создавать, редактировать и наполнять паки.\n"
    kb_list = [[InlineKeyboardButton(text="➕ Создать новый пак", callback_data="admin_create_pack_start")]]
    if packs:
        text += "\nСписок паков:\n"
        for p in packs:
            status = "✅" if p[3] else "❌"
            text += f"{status} #{p[0]} {p[1]} — {p[2]}💎\n"
            kb_list.append([InlineKeyboardButton(text=f"⚙️ #{p[0]} {p[1][:20]}", callback_data=f"pack_manage_{p[0]}")])
    else:
        text += "\nПакетов пока нет — создайте первый!"
    kb_list.append([InlineKeyboardButton(text="◀️ Назад в админ-панель", callback_data="admin_menu")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("pack_manage_"))
async def pack_manage(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    pack_id = int(callback.data.split("_")[2])
    await show_pack_manage(callback.message.chat.id, pack_id)

@dp.callback_query(F.data.startswith("edit_pack_name_"))
async def edit_pack_name_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    pack_id = int(callback.data.split("_")[3])
    await state.set_state(AdminEditPack.field)
    await state.update_data(pack_id=pack_id, field="name")
    await callback.message.edit_text("✏️ Введите новое название пака:", reply_markup=cancel_keyboard())

@dp.callback_query(F.data.startswith("edit_pack_price_"))
async def edit_pack_price_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    pack_id = int(callback.data.split("_")[3])
    await state.set_state(AdminEditPack.field)
    await state.update_data(pack_id=pack_id, field="price")
    await callback.message.edit_text("💰 Введите новую цену в 💎 (минимум 20):", reply_markup=cancel_keyboard())

@dp.callback_query(F.data.startswith("edit_pack_desc_"))
async def edit_pack_desc_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    pack_id = int(callback.data.split("_")[3])
    await state.set_state(AdminEditPack.field)
    await state.update_data(pack_id=pack_id, field="desc")
    await callback.message.edit_text("📝 Введите новое описание пака:", reply_markup=cancel_keyboard())

@dp.message(AdminEditPack.field)
async def edit_pack_field_save(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    data = await state.get_data()
    pack_id = data["pack_id"]
    field = data["field"]
    new_value = message.text.strip()
    if field == "price":
        try:
            new_value = int(new_value)
            if new_value < 20:
                await message.answer("❌ Минимальная цена 20 💎")
                return
        except:
            await message.answer("❌ Цена должна быть целым числом")
            return
    async with aiosqlite.connect(DB_NAME) as db:
        if field == "name":
            await db.execute("UPDATE packs SET name=? WHERE id=?", (new_value, pack_id))
        elif field == "price":
            await db.execute("UPDATE packs SET price=? WHERE id=?", (new_value, pack_id))
        elif field == "desc":
            await db.execute("UPDATE packs SET description=? WHERE id=?", (new_value, pack_id))
        await db.commit()
    await state.clear()
    await message.answer("✅ Изменения сохранены!")
    await show_pack_manage(message.chat.id, pack_id)

@dp.callback_query(F.data.startswith("toggle_pack_"))
async def toggle_pack(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    pack_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        current = (await (await db.execute("SELECT is_active FROM packs WHERE id=?", (pack_id,))).fetchone())[0]
        new_status = 0 if current else 1
        await db.execute("UPDATE packs SET is_active=? WHERE id=?", (new_status, pack_id))
        await db.commit()
    await callback.answer("✅ Статус изменён!")
    await show_pack_manage(callback.message.chat.id, pack_id)

@dp.callback_query(F.data.startswith("add_pack_photo_"))
async def add_pack_photo_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    pack_id = int(callback.data.split("_")[3])
    await state.set_state(AdminAddPackContent.content_type)
    await state.update_data(pack_id=pack_id, content_type="photo")
    await callback.message.edit_text("📤 Отправьте фото для добавления в пак:", reply_markup=cancel_keyboard())

@dp.callback_query(F.data.startswith("add_pack_video_"))
async def add_pack_video_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    pack_id = int(callback.data.split("_")[3])
    await state.set_state(AdminAddPackContent.content_type)
    await state.update_data(pack_id=pack_id, content_type="video")
    await callback.message.edit_text("📤 Отправьте видео для добавления в пак:", reply_markup=cancel_keyboard())

@dp.message(AdminAddPackContent.content_type, F.photo | F.video)
async def save_pack_content(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    data = await state.get_data()
    pack_id = data.get("pack_id")
    ctype = data.get("content_type")
    if not pack_id or not ctype:
        await message.answer("❌ Ошибка состояния, попробуйте снова")
        await state.clear()
        return
    if ctype == "photo" and message.photo:
        file_id = message.photo[-1].file_id
    elif ctype == "video" and message.video:
        file_id = message.video.file_id
    else:
        await message.answer("❌ Неверный тип медиа для выбранного действия")
        return
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO pack_content (pack_id, file_id, content_type, added_by) VALUES (?, ?, ?, ?)", 
                         (pack_id, file_id, ctype, message.from_user.id))
        await db.commit()
    await message.answer("✅ Контент успешно добавлен в пак!")
    await state.clear()
    await show_pack_manage(message.chat.id, pack_id)

@dp.callback_query(F.data.startswith("list_pack_content_"))
async def list_pack_content(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    pack_id = int(callback.data.split("_")[3])
    async with aiosqlite.connect(DB_NAME) as db:
        contents = await (await db.execute("SELECT id, content_type FROM pack_content WHERE pack_id=? ORDER BY id", (pack_id,))).fetchall()
        pack_name = (await (await db.execute("SELECT name FROM packs WHERE id=?", (pack_id,))).fetchone())[0]
    if not contents:
        await callback.message.edit_text(f"📋 В паке «{pack_name}» нет контента.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data=f"pack_manage_{pack_id}")]]))
        return
    text = f"📋 <b>Контент пака «{pack_name}»</b>\nНажмите на кнопку, чтобы удалить:\n\n"
    kb_list = []
    for c in contents:
        emoji = "📸" if c[1] == "photo" else "🎥"
        kb_list.append([InlineKeyboardButton(text=f"{emoji} Удалить #{c[0]}", callback_data=f"remove_pack_content_{c[0]}")])
    kb_list.append([InlineKeyboardButton(text="◀️ Назад к паку", callback_data=f"pack_manage_{pack_id}")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("remove_pack_content_"))
async def remove_pack_content(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    content_id = int(callback.data.split("_")[3])
    async with aiosqlite.connect(DB_NAME) as db:
        pack_id_row = await (await db.execute("SELECT pack_id FROM pack_content WHERE id=?", (content_id,))).fetchone()
        if pack_id_row:
            pack_id = pack_id_row[0]
            await db.execute("DELETE FROM pack_content WHERE id=?", (content_id,))
            await db.commit()
            await callback.answer("✅ Контент удалён!")
            await list_pack_content_by_id(callback.message.chat.id, pack_id)
        else:
            await callback.answer("❌ Не найдено")

async def list_pack_content_by_id(chat_id: int, pack_id: int):
    """Helper for refresh after delete"""
    async with aiosqlite.connect(DB_NAME) as db:
        contents = await (await db.execute("SELECT id, content_type FROM pack_content WHERE pack_id=? ORDER BY id", (pack_id,))).fetchall()
        pack_name = (await (await db.execute("SELECT name FROM packs WHERE id=?", (pack_id,))).fetchone())[0]
    if not contents:
        await bot.send_message(chat_id, f"📋 В паке «{pack_name}» нет контента.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data=f"pack_manage_{pack_id}")]]))
        return
    text = f"📋 <b>Контент пака «{pack_name}»</b>\nНажмите на кнопку, чтобы удалить:\n\n"
    kb_list = []
    for c in contents:
        emoji = "📸" if c[1] == "photo" else "🎥"
        kb_list.append([InlineKeyboardButton(text=f"{emoji} Удалить #{c[0]}", callback_data=f"remove_pack_content_{c[0]}")])
    kb_list.append([InlineKeyboardButton(text="◀️ Назад к паку", callback_data=f"pack_manage_{pack_id}")])
    await bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("delete_pack_"))
async def delete_pack(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    pack_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM pack_content WHERE pack_id=?", (pack_id,))
        await db.execute("DELETE FROM user_packs WHERE pack_id=?", (pack_id,))
        await db.execute("DELETE FROM packs WHERE id=?", (pack_id,))
        await db.commit()
    await callback.answer("🗑 Пак и весь его контент удалены!")
    await admin_packs(callback)

# Create pack wizard
@dp.callback_query(F.data == "admin_create_pack_start")
async def admin_create_pack_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminCreatePack.waiting_name)
    await callback.message.edit_text("➕ Введите название нового пака (например: 'Летний вайб 2026'):", reply_markup=cancel_keyboard())

@dp.message(AdminCreatePack.waiting_name)
async def create_pack_name(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    name = message.text.strip()[:50]
    await state.update_data(name=name)
    await state.set_state(AdminCreatePack.waiting_desc)
    await message.answer("📝 Введите описание пака (или отправьте /skip чтобы пропустить):", reply_markup=cancel_keyboard())

@dp.message(AdminCreatePack.waiting_desc)
async def create_pack_desc(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    desc = "" if message.text.strip().lower() == "/skip" else message.text.strip()[:200]
    await state.update_data(desc=desc)
    await state.set_state(AdminCreatePack.waiting_price)
    await message.answer("💰 Введите цену пака в алмазиках (минимум 20, например 25):", reply_markup=cancel_keyboard())

@dp.message(AdminCreatePack.waiting_price)
async def create_pack_price(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    try:
        price = int(message.text.strip())
        if price < 20:
            await message.answer("❌ Минимальная цена — 20 💎. Попробуйте ещё раз:")
            return
    except:
        await message.answer("❌ Введите число. Попробуйте ещё раз:")
        return
    data = await state.get_data()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO packs (name, description, price) VALUES (?, ?, ?)", 
                         (data["name"], data["desc"], price))
        await db.commit()
    await state.clear()
    await message.answer(f"✅ Пак «{data['name']}» успешно создан за {price} 💎!")
    async with aiosqlite.connect(DB_NAME) as db:
        packs = await (await db.execute("SELECT id, name, price, is_active FROM packs ORDER BY id DESC LIMIT 5")).fetchall()
    text = "📦 Пак создан! Список последних паков:\n"
    for p in packs:
        text += f"• #{p[0]} {p[1]} — {p[2]}💎\n"
    await message.answer(text, reply_markup=admin_menu())

# ==================== ЗАПУСК ====================
async def main():
    await init_db()
    commands = [BotCommand(command="start", description="Главное меню")]
    await bot.set_my_commands(commands)
    logger.info("🚀 Bot v12 Full запущен! Исправлены рефералы (бонус только 1 раз) и улучшена обработка тикетов.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())