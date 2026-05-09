import asyncio
import aiosqlite
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "8793552076:AAHE1_NE2NZU8w_xjcEDH9kSOIuEiygdGak"
OWNER_ID = 8032626504
DB_NAME = "video_games_bot.db"
REQUIRED_CHANNEL_ID = -1003969378970
REQUIRED_CHANNEL_LINK = "https://t.me/rezerv_video_pita"
REFERRAL_BONUS = 15  # ← ИЗМЕНИ ЗДЕСЬ, если хочешь другую награду

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ==================== БАЗА ДАННЫХ ====================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            diamonds INTEGER DEFAULT 0,
            last_bonus TEXT,
            is_banned INTEGER DEFAULT 0,
            is_manager INTEGER DEFAULT 0,
            referrer_id INTEGER DEFAULT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_content_type ON content(content_type)")
        await db.execute("""CREATE TABLE IF NOT EXISTS content (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, content_type TEXT, added_by INTEGER)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_username TEXT, reward INTEGER DEFAULT 5, is_active INTEGER DEFAULT 1)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS support_tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, status TEXT DEFAULT 'open')""")
        await db.execute("""CREATE TABLE IF NOT EXISTS support_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER, user_id INTEGER, message TEXT, is_admin INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS promo_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, diamonds INTEGER, max_uses INTEGER, current_uses INTEGER DEFAULT 0, created_by INTEGER)""")
        await db.commit()

# ==================== FSM ====================
class AdminAddContent(StatesGroup):
    waiting_file = State()
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
class SupportState(StatesGroup):
    waiting_message = State()
class AdminTicketReply(StatesGroup):
    waiting_reply = State()
    ticket_id = State()
class RedeemPromo(StatesGroup):
    waiting_code = State()
class AdminAddTask(StatesGroup):
    waiting_data = State()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ====================
async def get_user_info(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        row = await (await db.execute(
            "SELECT diamonds, is_banned, is_manager, referrer_id FROM users WHERE user_id = ?", (user_id,)
        )).fetchone()
        return {"diamonds": row[0] if row else 0, "is_banned": row[1] if row else 0, "is_manager": row[2] if row else 0, "referrer_id": row[3] if row else None}

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
    """Выдаёт бонус рефереру, если он ещё не был выдан"""
    async with aiosqlite.connect(DB_NAME) as db:
        row = await (await db.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))).fetchone()
        if not row or not row[0]: return
        
        referrer_id = row[0]
        # Проверяем, не был ли уже выдан бонус
        already_given = await (await db.execute(
            "SELECT 1 FROM users WHERE user_id = ? AND referrer_id = ?", (user_id, referrer_id)
        )).fetchone()
        
        if already_given:
            return  # уже выдали
        
        await db.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", (REFERRAL_BONUS, referrer_id))
        await db.commit()
        
        try:
            await bot.send_message(referrer_id, f"🎉 <b>Новый реферал!</b>\n\n+{REFERRAL_BONUS} 💎 за приглашение!")
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
        [InlineKeyboardButton(text="📤 Загрузить контент", callback_data="admin_add_content"),
         InlineKeyboardButton(text="📋 Задания", callback_data="admin_tasks")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
         InlineKeyboardButton(text="🚫 Бан/Разбан", callback_data="admin_ban")],
        [InlineKeyboardButton(text="🎟 Тикеты", callback_data="admin_tickets"),
         InlineKeyboardButton(text="💎 Выдать алмазики", callback_data="admin_give_diamonds")],
        [InlineKeyboardButton(text="💎 Массово алмазики", callback_data="admin_mass_give"),
         InlineKeyboardButton(text="👑 Менеджеры", callback_data="admin_manager_menu")],
        [InlineKeyboardButton(text="📊 Статистика пользователей", callback_data="admin_view_user"),
         InlineKeyboardButton(text="🎟 Промокод", callback_data="admin_create_promo")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])

def manager_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Выдать алмазики", callback_data="manager_give_diamonds"),
         InlineKeyboardButton(text="🚫 Бан/Разбан", callback_data="manager_ban")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="manager_broadcast"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="manager_stats")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])

# ==================== ХЕНДЛЕРЫ ====================
@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    args = message.text.split()
    referrer_id = None
    
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1][4:])
        except:
            pass
    
    await get_or_create_user(user_id, message.from_user.username, referrer_id)
    
    if await check_banned(user_id):
        await message.answer("🚫 Ты забанен.")
        return
    
    if not await is_subscribed(user_id):
        text = f"🔒 <b>Подпишись на канал</b>\n\n{REQUIRED_CHANNEL_LINK}\n\nПосле подписки нажми кнопку."
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]])
        await message.answer(text, reply_markup=kb)
        return
    
    # Выдаём реферальный бонус ТОЛЬКО после успешной подписки
    await give_referral_bonus(user_id)
    
    await message.answer("🎮 <b>Video Games Bot</b>\n\nСмотри контент за алмазики!", reply_markup=await main_menu(user_id))

@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await is_subscribed(user_id):
        await give_referral_bonus(user_id)  # Выдаём бонус при первой успешной проверке
        await callback.message.edit_text("✅ Спасибо за подписку!", reply_markup=await main_menu(user_id))
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
    
    text = (
        f"👥 <b>Реферальная программа</b>\n\n"
        f"Приглашай друзей и получай <b>+{REFERRAL_BONUS} 💎</b> за каждого!\n\n"
        f"🔗 Твоя ссылка:\n<code>{ref_link}</code>\n\n"
        f"👥 Приглашено: <b>{ref_count}</b> человек"
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="main_menu")]
    ]))

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
            text = (
                f"👤 <b>Статистика</b>\n\n"
                f"🆔 {row[0]}\n"
                f"👤 @{row[1] or 'нет'}\n"
                f"💎 Алмазики: <b>{row[2]}</b>\n"
                f"🚫 Забанен: {'Да' if row[3] else 'Нет'}\n"
                f"🛡️ Менеджер: {'Да' if row[4] else 'Нет'}\n"
                f"👥 Рефералов: <b>{ref_count}</b>\n"
                f"📅 Регистрация: {row[6][:10] if row[6] else '—'}"
            )
            if row[5]:
                text += f"\n🔗 Приглашён: {row[5]}"
        await message.answer(text)
    except:
        await message.answer("❌ Ошибка")
    await state.clear()
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_mass_give")
async def admin_mass_give_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
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

# ==================== ТИКЕТЫ ====================
TICKETS_PER_PAGE = 5

@dp.callback_query(F.data == "admin_tickets")
async def admin_tickets(callback: CallbackQuery, page: int = 0):
    if callback.from_user.id != OWNER_ID: return
    await show_tickets_page(callback.message, page)

async def show_tickets_page(message, page: int = 0):
    offset = page * TICKETS_PER_PAGE
    async with aiosqlite.connect(DB_NAME) as db:
        tickets = await (await db.execute(
            "SELECT id, user_id FROM support_tickets WHERE status='open' ORDER BY id DESC LIMIT ? OFFSET ?",
            (TICKETS_PER_PAGE, offset)
        )).fetchall()
        total = (await (await db.execute("SELECT COUNT(*) FROM support_tickets WHERE status='open'")).fetchone())[0]
    total_pages = max(1, (total + TICKETS_PER_PAGE - 1) // TICKETS_PER_PAGE)
    
    if not tickets:
        text = "🎟 Нет активных тикетов"
        kb = admin_menu()
    else:
        text = f"🎟 <b>Тикеты</b> (стр. {page+1}/{total_pages})\n"
        kb_list = []
        for t in tickets:
            text += f"#{t[0]} | {t[1]}\n"
            kb_list.append([
                InlineKeyboardButton(text=f"✉️ #{t[0]}", callback_data=f"reply_ticket_{t[0]}"),
                InlineKeyboardButton(text="🔒 Закрыть", callback_data=f"close_ticket_{t[0]}")
            ])
        nav = []
        if page > 0: nav.append(InlineKeyboardButton(text="◀️", callback_data=f"tickets_page_{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages-1: nav.append(InlineKeyboardButton(text="▶️", callback_data=f"tickets_page_{page+1}"))
        if nav: kb_list.append(nav)
        kb_list.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_list)
    await message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("tickets_page_"))
async def tickets_page(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    page = int(callback.data.split("_")[2])
    await show_tickets_page(callback.message, page)

@dp.callback_query(F.data.startswith("close_ticket_"))
async def close_ticket_admin(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    ticket_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        user_id = (await (await db.execute("SELECT user_id FROM support_tickets WHERE id=?", (ticket_id,))).fetchone())[0]
        await db.execute("UPDATE support_tickets SET status='closed' WHERE id=?", (ticket_id,))
        await db.commit()
    try:
        await bot.send_message(user_id, f"🔒 Тикет #{ticket_id} закрыт администратором.")
    except:
        pass
    await callback.answer("✅ Закрыт")
    await show_tickets_page(callback.message, 0)

@dp.callback_query(F.data.startswith("reply_ticket_"))
async def reply_ticket_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    ticket_id = int(callback.data.split("_")[2])
    await state.set_state(AdminTicketReply.waiting_reply)
    await state.update_data(ticket_id=ticket_id)
    try:
        user_id = (await (await db.execute("SELECT user_id FROM support_tickets WHERE id=?", (ticket_id,))).fetchone())[0]
        await bot.send_message(user_id, f"🛠 Агент взял тикет #{ticket_id} в работу.")
    except:
        pass
    await callback.message.edit_text(f"✍️ Ответ на тикет #{ticket_id}:", reply_markup=cancel_keyboard())

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
    if callback.from_user.id != OWNER_ID: return
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
    if message.from_user.id != OWNER_ID: return
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

# ==================== ЗАПУСК ====================
async def main():
    await init_db()
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="help", description="Помощь"),
    ]
    await bot.set_my_commands(commands)
    logger.info("🚀 Bot v8 Final запущен! Рефка работает только после подписки.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

