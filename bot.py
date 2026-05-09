import asyncio
import aiosqlite
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "8793552076:AAHE1_NE2NZU8w_xjcEDH9kSOIuEiygdGak"
OWNER_ID = 8032626504
DB_NAME = "video_games_bot.db"
REQUIRED_CHANNEL_ID = -1003969378970
REQUIRED_CHANNEL_LINK = "https://t.me/rezerv_video_pita"

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
            is_manager INTEGER DEFAULT 0
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS content (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            file_id TEXT, 
            content_type TEXT, 
            added_by INTEGER
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            channel_username TEXT, 
            reward INTEGER DEFAULT 5, 
            is_active INTEGER DEFAULT 1
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            user_id INTEGER, 
            status TEXT DEFAULT 'open'
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            ticket_id INTEGER, 
            user_id INTEGER, 
            message TEXT, 
            is_admin INTEGER DEFAULT 0
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS promo_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            code TEXT UNIQUE, 
            diamonds INTEGER, 
            max_uses INTEGER, 
            current_uses INTEGER DEFAULT 0, 
            created_by INTEGER
        )""")
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

class SupportState(StatesGroup):
    waiting_message = State()

class AdminTicketReply(StatesGroup):
    waiting_reply = State()
    ticket_id = State()

class RedeemPromo(StatesGroup):
    waiting_code = State()

class AdminAddTask(StatesGroup):
    waiting_data = State()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

async def get_user_info(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        row = await (await db.execute(
            "SELECT diamonds, is_banned, is_manager FROM users WHERE user_id = ?", (user_id,)
        )).fetchone()
        if row:
            return {"diamonds": row[0], "is_banned": row[1], "is_manager": row[2]}
        return {"diamonds": 0, "is_banned": 0, "is_manager": 0}

async def check_banned(user_id: int) -> bool:
    info = await get_user_info(user_id)
    return info["is_banned"] == 1

async def is_admin_or_manager(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    info = await get_user_info(user_id)
    return info["is_manager"] == 1

# ==================== МЕНЮ ====================
def main_menu(user_id: int):
    keyboard = [
        [InlineKeyboardButton(text="📸 Фото (1 💎)", callback_data="watch_photo"),
         InlineKeyboardButton(text="🎥 Видео (2 💎)", callback_data="watch_video")],
        [InlineKeyboardButton(text="🎁 Бонус +10 💎", callback_data="daily_bonus"),
         InlineKeyboardButton(text="📋 Задания", callback_data="tasks")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🛒 Магазин", callback_data="shop")],
        [InlineKeyboardButton(text="🎟 Промокод", callback_data="redeem_promo"),
         InlineKeyboardButton(text="🛠 Поддержка", callback_data="support")]
    ]
    
    info = None  # будет заполнено позже
    # В реальном коде лучше передавать is_manager, но для простоты проверяем здесь
    # (в handler мы уже знаем)
    
    if user_id == OWNER_ID:
        keyboard.append([InlineKeyboardButton(text="🔧 АДМИН-ПАНЕЛЬ", callback_data="admin_menu")])
    else:
        # Проверяем, является ли менеджером (в реальном использовании лучше кэшировать)
        pass  # менеджерскую кнопку добавим в хендлере
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Загрузить контент", callback_data="admin_add_content"),
         InlineKeyboardButton(text="📋 Задания", callback_data="admin_tasks")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
         InlineKeyboardButton(text="🚫 Бан/Разбан", callback_data="admin_ban")],
        [InlineKeyboardButton(text="🎟 Тикеты поддержки", callback_data="admin_tickets"),
         InlineKeyboardButton(text="💎 Выдать алмазики", callback_data="admin_give_diamonds")],
        [InlineKeyboardButton(text="💎 Массово алмазики", callback_data="admin_mass_give"),
         InlineKeyboardButton(text="👑 Статус менеджера", callback_data="admin_manager_menu")],
        [InlineKeyboardButton(text="🎟 Создать промокод", callback_data="admin_create_promo"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="main_menu")]
    ])

def manager_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Выдать алмазики", callback_data="manager_give_diamonds"),
         InlineKeyboardButton(text="🚫 Бан/Разбан", callback_data="manager_ban")],
        [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="manager_broadcast"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="manager_stats")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="main_menu")]
    ])

def manager_status_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выдать статус менеджера", callback_data="admin_give_manager"),
         InlineKeyboardButton(text="❌ Снять статус менеджера", callback_data="admin_remove_manager")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
    ])

# ==================== ХЕНДЛЕРЫ ====================
@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username)
    
    if await check_banned(user_id):
        await message.answer("🚫 Ты забанен и не можешь пользоваться ботом.")
        return
    
    if not await is_subscribed(user_id):
        text = (f"🔒 <b>Чтобы пользоваться ботом, подпишись на канал</b>\n\n"
                f"{REQUIRED_CHANNEL_LINK}\n\n"
                f"После подписки нажми кнопку ниже 👇")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]
        ])
        await message.answer(text, reply_markup=keyboard)
        return
    
    welcome_text = (
        "🎮 <b>Добро пожаловать в Video Games Bot!</b>\n\n"
        "Здесь ты можешь смотреть эксклюзивные фото и видео за алмазики 💎\n"
        "Получай ежедневный бонус, выполняй задания и приглашай друзей!"
    )
    await message.answer(welcome_text, reply_markup=main_menu(user_id))

async def get_or_create_user(user_id: int, username: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
            (user_id, username or "")
        )
        await db.commit()

@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await is_subscribed(user_id):
        await callback.message.edit_text(
            "✅ <b>Спасибо за подписку!</b>\n\nТеперь тебе доступен весь функционал бота.",
            reply_markup=main_menu(user_id)
        )
    else:
        await callback.answer("❌ Ты ещё не подписан на канал!", show_alert=True)

@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    info = await get_user_info(user_id)
    
    status = "👑 Администратор" if user_id == OWNER_ID else ("🛡️ Менеджер" if info["is_manager"] else "👤 Обычный пользователь")
    
    text = (
        f"👤 <b>Твой профиль</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💎 Алмазики: <b>{info['diamonds']}</b>\n"
        f"📌 Статус: <b>{status}</b>\n\n"
        f"{'🚫 Ты забанен' if info['is_banned'] else '✅ Аккаунт активен'}"
    )
    await callback.message.edit_text(text, reply_markup=main_menu(user_id))

@dp.callback_query(F.data == "daily_bonus")
async def daily_bonus(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await check_banned(user_id):
        await callback.answer("🚫 Ты забанен!", show_alert=True)
        return
    
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_NAME) as db:
        last = (await (await db.execute(
            "SELECT last_bonus FROM users WHERE user_id = ?", (user_id,)
        )).fetchone())[0]
        
        if last == today:
            await callback.answer("❌ Бонус уже получен сегодня! Приходи завтра.", show_alert=True)
            return
        
        await db.execute(
            "UPDATE users SET diamonds = diamonds + 10, last_bonus = ? WHERE user_id = ?", 
            (today, user_id)
        )
        await db.commit()
    
    await callback.answer("🎁 +10 💎 начислено!", show_alert=True)
    await profile(callback)

@dp.callback_query(F.data == "watch_photo")
async def watch_photo(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await check_banned(user_id):
        await callback.answer("🚫 Ты забанен!", show_alert=True)
        return
    
    info = await get_user_info(user_id)
    if info["diamonds"] < 1:
        await callback.message.edit_text(
            "❌ <b>Недостаточно алмазиков!</b>\n\n"
            "Нужно минимум 1 💎 для просмотра фото.\n"
            "Получи бонус или выполни задания!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")]
            ])
        )
        return
    
    async with aiosqlite.connect(DB_NAME) as db:
        content = await (await db.execute(
            "SELECT file_id FROM content WHERE content_type = 'photo' ORDER BY RANDOM() LIMIT 1"
        )).fetchone()
        
        if not content:
            await callback.answer("😔 Пока нет загруженных фото. Загрузи через админку!", show_alert=True)
            return
        
        await db.execute("UPDATE users SET diamonds = diamonds - 1 WHERE user_id = ?", (user_id,))
        await db.commit()
    
    await bot.send_photo(
        user_id, 
        content[0], 
        caption=f"📸 <b>Вот твоё фото!</b>\n\n💎 Остаток: {info['diamonds'] - 1}"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Ещё фото", callback_data="watch_photo"),
         InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")]
    ])
    await bot.send_message(user_id, "Что дальше?", reply_markup=keyboard)

@dp.callback_query(F.data == "watch_video")
async def watch_video(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await check_banned(user_id):
        await callback.answer("🚫 Ты забанен!", show_alert=True)
        return
    
    info = await get_user_info(user_id)
    if info["diamonds"] < 2:
        await callback.message.edit_text(
            "❌ <b>Недостаточно алмазиков!</b>\n\n"
            "Нужно минимум 2 💎 для просмотра видео.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")]
            ])
        )
        return
    
    async with aiosqlite.connect(DB_NAME) as db:
        content = await (await db.execute(
            "SELECT file_id FROM content WHERE content_type = 'video' ORDER BY RANDOM() LIMIT 1"
        )).fetchone()
        
        if not content:
            await callback.answer("😔 Пока нет загруженных видео!", show_alert=True)
            return
        
        await db.execute("UPDATE users SET diamonds = diamonds - 2 WHERE user_id = ?", (user_id,))
        await db.commit()
    
    await bot.send_video(
        user_id, 
        content[0], 
        caption=f"🎥 <b>Вот твоё видео!</b>\n\n💎 Остаток: {info['diamonds'] - 2}"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Ещё видео", callback_data="watch_video"),
         InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")]
    ])
    await bot.send_message(user_id, "Что дальше?", reply_markup=keyboard)

@dp.callback_query(F.data == "tasks")
async def tasks(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        tasks_list = await (await db.execute(
            "SELECT channel_username, reward FROM tasks WHERE is_active = 1"
        )).fetchall()
    
    if not tasks_list:
        text = "📋 <b>Задания</b>\n\nПока нет активных заданий. Загляни позже!"
    else:
        text = "📋 <b>Активные задания</b>\n\n"
        for t in tasks_list:
            text += f"• Подпишись на {t[0]} → <b>+{t[1]} 💎</b>\n"
        text += "\nПосле выполнения напиши в поддержку для начисления."
    
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "shop")
async def shop(callback: CallbackQuery):
    text = (
        "🛒 <b>Магазин алмазиков</b>\n\n"
        "Хочешь купить алмазики за реальные деньги?\n\n"
        "Напиши в поддержку — менеджер предложит выгодные пакеты!"
    )
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "redeem_promo")
async def redeem_promo_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RedeemPromo.waiting_code)
    await callback.message.edit_text(
        "🎟 <b>Активация промокода</b>\n\n"
        "Введи код промокода (например: BONUS2026):"
    )

@dp.message(RedeemPromo.waiting_code)
async def redeem_promo(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        promo = await (await db.execute(
            "SELECT id, diamonds, max_uses, current_uses FROM promo_codes WHERE code = ?", (code,)
        )).fetchone()
        
        if not promo:
            await message.answer("❌ Промокод не найден или уже не действует.")
            await state.clear()
            return
        
        if promo[3] >= promo[2]:
            await message.answer("❌ Этот промокод уже полностью использован!")
            await state.clear()
            return
        
        await db.execute("UPDATE promo_codes SET current_uses = current_uses + 1 WHERE id = ?", (promo[0],))
        await db.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", (promo[1], user_id))
        await db.commit()
    
    await message.answer(f"✅ <b>Промокод активирован!</b>\n\nТебе начислено +{promo[1]} 💎")
    await state.clear()
    await message.answer("🎮 Главное меню:", reply_markup=main_menu(user_id))

@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SupportState.waiting_message)
    await callback.message.edit_text(
        "🛠 <b>Поддержка</b>\n\n"
        "Опиши свою проблему или вопрос максимально подробно.\n"
        "Мы ответим в течение 24 часов."
    )

@dp.message(SupportState.waiting_message)
async def support_save(message: Message, state: FSMContext):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "INSERT INTO support_tickets (user_id) VALUES (?) RETURNING id", (user_id,)
        )
        ticket_id = (await cursor.fetchone())[0]
        await db.execute(
            "INSERT INTO support_messages (ticket_id, user_id, message) VALUES (?, ?, ?)", 
            (ticket_id, user_id, message.text)
        )
        await db.commit()
    
    await message.answer(
        f"✅ <b>Тикет #{ticket_id} создан!</b>\n\n"
        "Спасибо за обращение. Менеджер свяжется с тобой в ближайшее время."
    )
    await state.clear()
    await message.answer("🎮 Главное меню:", reply_markup=main_menu(user_id))

# ==================== АДМИН-ПАНЕЛЬ ====================
@dp.callback_query(F.data == "admin_menu")
async def admin_menu_handler(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ только для владельца!", show_alert=True)
        return
    await callback.message.edit_text(
        "🔧 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "Выбери действие:",
        reply_markup=admin_menu()
    )

@dp.callback_query(F.data == "admin_add_content")
async def admin_add_content(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminAddContent.waiting_file)
    await callback.message.edit_text(
        "📤 <b>Загрузка контента</b>\n\n"
        "Пришли фото или видео, которое хочешь добавить в базу.\n"
        "Оно будет случайно показываться пользователям."
    )

@dp.message(AdminAddContent.waiting_file, F.photo | F.video)
async def save_content(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    content_type = "photo" if message.photo else "video"
    file_id = message.photo[-1].file_id if message.photo else message.video.file_id
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO content (file_id, content_type, added_by) VALUES (?, ?, ?)", 
            (file_id, content_type, message.from_user.id)
        )
        await db.commit()
    
    await message.answer(f"✅ <b>{content_type.capitalize()} успешно добавлено!</b>")
    await state.clear()
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_tasks")
async def admin_tasks(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        tasks = await (await db.execute(
            "SELECT id, channel_username, reward FROM tasks WHERE is_active = 1"
        )).fetchall()
    
    text = "📋 <b>Управление заданиями</b>\n\n"
    if tasks:
        for t in tasks:
            text += f"#{t[0]} | {t[1]} → +{t[2]} 💎\n"
    else:
        text += "Пока нет активных заданий."
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить задание", callback_data="admin_add_task"),
         InlineKeyboardButton(text="🗑 Удалить задание", callback_data="admin_delete_task")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)

@dp.callback_query(F.data == "admin_add_task")
async def admin_add_task_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminAddTask.waiting_data)
    await callback.message.edit_text(
        "➕ <b>Добавление задания</b>\n\n"
        "Введи в одном сообщении:\n"
        "<code>@channel_username награда</code>\n\n"
        "Пример: <code>@my_channel 15</code>"
    )

@dp.message(AdminAddTask.waiting_data)
async def admin_add_task_save(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    try:
        parts = message.text.strip().split()
        channel = parts[0]
        reward = int(parts[1])
        
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO tasks (channel_username, reward) VALUES (?, ?)", 
                (channel, reward)
            )
            await db.commit()
        
        await message.answer(f"✅ Задание для {channel} (+{reward} 💎) добавлено!")
    except:
        await message.answer("❌ Неверный формат. Пример: @channel 10")
    
    await state.clear()
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_delete_task")
async def admin_delete_task(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        tasks = await (await db.execute(
            "SELECT id, channel_username FROM tasks WHERE is_active = 1"
        )).fetchall()
    
    if not tasks:
        await callback.answer("Заданий нет", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🗑 #{t[0]} {t[1]}", callback_data=f"delete_task_{t[0]}")] for t in tasks
    ] + [[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_tasks")]])
    
    await callback.message.edit_text("Выбери задание для удаления:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("delete_task_"))
async def delete_task_confirm(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    task_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tasks SET is_active = 0 WHERE id = ?", (task_id,))
        await db.commit()
    await callback.answer("✅ Задание деактивировано")
    await admin_tasks(callback)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        total_users = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        total_content = (await (await db.execute("SELECT COUNT(*) FROM content")).fetchone())[0]
        total_diamonds = (await (await db.execute("SELECT SUM(diamonds) FROM users")).fetchone())[0] or 0
        managers = (await (await db.execute("SELECT COUNT(*) FROM users WHERE is_manager = 1")).fetchone())[0]
        open_tickets = (await (await db.execute("SELECT COUNT(*) FROM support_tickets WHERE status = 'open'")).fetchone())[0]
    
    text = (
        f"📊 <b>Полная статистика</b>\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"🛡️ Менеджеров: <b>{managers}</b>\n"
        f"📸 Контента: <b>{total_content}</b>\n"
        f"💎 Алмазиков всего: <b>{total_diamonds}</b>\n"
        f"🎟 Открытых тикетов: <b>{open_tickets}</b>"
    )
    await callback.message.edit_text(text, reply_markup=admin_menu())

# ==================== МАССОВАЯ ВЫДАЧА АЛМАЗИКОВ ====================
@dp.callback_query(F.data == "admin_mass_give")
async def admin_mass_give_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminMassGiveDiamonds.waiting_amount)
    await callback.message.edit_text(
        "💎 <b>Массовая выдача алмазиков</b>\n\n"
        "Введи количество алмазиков, которое получит <b>КАЖДЫЙ</b> пользователь:\n\n"
        "⚠️ Это действие нельзя отменить!"
    )

@dp.message(AdminMassGiveDiamonds.waiting_amount)
async def admin_mass_give_confirm(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    try:
        amount = int(message.text)
        if amount <= 0:
            await message.answer("❌ Количество должно быть больше 0")
            return
        
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE users SET diamonds = diamonds + ? WHERE is_banned = 0", 
                (amount,)
            )
            await db.commit()
            affected = (await (await db.execute("SELECT changes()")).fetchone())[0]
        
        await message.answer(
            f"✅ <b>Успешно!</b>\n\n"
            f"Выдано +{amount} 💎 каждому из {affected} активных пользователей."
        )
    except:
        await message.answer("❌ Неверное число!")
    
    await state.clear()
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

# ==================== УПРАВЛЕНИЕ МЕНЕДЖЕРАМИ ====================
@dp.callback_query(F.data == "admin_manager_menu")
async def admin_manager_menu(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    await callback.message.edit_text(
        "👑 <b>Управление менеджерами</b>\n\n"
        "Менеджеры имеют доступ к ограниченной админ-панели:\n"
        "• Выдача алмазиков\n"
        "• Бан/разбан\n"
        "• Рассылка\n"
        "• Просмотр статистики",
        reply_markup=manager_status_menu()
    )

@dp.callback_query(F.data == "admin_give_manager")
async def admin_give_manager_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminGiveManager.waiting_user_id)
    await callback.message.edit_text(
        "✅ <b>Выдача статуса менеджера</b>\n\n"
        "Введи ID пользователя, которому хочешь дать права менеджера:"
    )

@dp.message(AdminGiveManager.waiting_user_id)
async def admin_give_manager_confirm(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    try:
        uid = int(message.text)
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET is_manager = 1 WHERE user_id = ?", (uid,))
            await db.commit()
        await message.answer(f"✅ Пользователь {uid} теперь <b>менеджер</b>!")
        try:
            await bot.send_message(uid, "🎉 Поздравляем! Тебе выдали статус <b>Менеджера</b>!")
        except:
            pass
    except:
        await message.answer("❌ Ошибка. Проверь ID.")
    await state.clear()
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_remove_manager")
async def admin_remove_manager_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminRemoveManager.waiting_user_id)
    await callback.message.edit_text(
        "❌ <b>Снятие статуса менеджера</b>\n\n"
        "Введи ID пользователя, у которого хочешь снять права:"
    )

@dp.message(AdminRemoveManager.waiting_user_id)
async def admin_remove_manager_confirm(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    try:
        uid = int(message.text)
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET is_manager = 0 WHERE user_id = ?", (uid,))
            await db.commit()
        await message.answer(f"✅ У пользователя {uid} снят статус менеджера.")
    except:
        await message.answer("❌ Ошибка.")
    await state.clear()
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

# ==================== ТИКЕТЫ ПОДДЕРЖКИ (С ПАГИНАЦИЕЙ) ====================
TICKETS_PER_PAGE = 5

@dp.callback_query(F.data == "admin_tickets")
async def admin_tickets(callback: CallbackQuery, page: int = 0):
    if callback.from_user.id != OWNER_ID: return
    await show_tickets_page(callback.message, page)

async def show_tickets_page(message, page: int = 0):
    offset = page * TICKETS_PER_PAGE
    async with aiosqlite.connect(DB_NAME) as db:
        tickets = await (await db.execute(
            "SELECT id, user_id FROM support_tickets WHERE status = 'open' ORDER BY id DESC LIMIT ? OFFSET ?",
            (TICKETS_PER_PAGE, offset)
        )).fetchall()
        total = (await (await db.execute("SELECT COUNT(*) FROM support_tickets WHERE status = 'open'")).fetchone())[0]
    
    total_pages = (total + TICKETS_PER_PAGE - 1) // TICKETS_PER_PAGE
    
    if not tickets:
        text = "🎟 <b>Активные тикеты</b>\n\nНа данный момент открытых тикетов нет."
        keyboard = admin_menu()
    else:
        text = f"🎟 <b>Активные тикеты</b> (стр. {page+1}/{total_pages})\n\n"
        for t in tickets:
            text += f"#{t[0]} | Пользователь {t[1]}\n"
        
        keyboard_buttons = []
        for t in tickets:
            keyboard_buttons.append([InlineKeyboardButton(
                text=f"✉️ Ответить #{t[0]}", 
                callback_data=f"reply_ticket_{t[0]}"
            )])
        
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"tickets_page_{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"tickets_page_{page+1}"))
        
        if nav:
            keyboard_buttons.append(nav)
        keyboard_buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await message.edit_text(text, reply_markup=keyboard)

@dp.callback_query(F.data.startswith("tickets_page_"))
async def tickets_pagination(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    page = int(callback.data.split("_")[2])
    await show_tickets_page(callback.message, page)

@dp.callback_query(F.data.startswith("reply_ticket_"))
async def reply_ticket_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    ticket_id = int(callback.data.split("_")[2])
    await state.set_state(AdminTicketReply.waiting_reply)
    await state.update_data(ticket_id=ticket_id)
    await callback.message.edit_text(
        f"✍️ <b>Ответ на тикет #{ticket_id}</b>\n\n"
        "Напиши сообщение, которое получит пользователь:"
    )

@dp.message(AdminTicketReply.waiting_reply)
async def reply_ticket_send(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    data = await state.get_data()
    ticket_id = data["ticket_id"]
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO support_messages (ticket_id, user_id, message, is_admin) VALUES (?, ?, ?, 1)", 
            (ticket_id, message.from_user.id, message.text)
        )
        user_id = (await (await db.execute(
            "SELECT user_id FROM support_tickets WHERE id = ?", (ticket_id,)
        )).fetchone())[0]
        await db.commit()
    
    try:
        await bot.send_message(
            user_id, 
            f"📩 <b>Ответ от поддержки</b> (тикет #{ticket_id})\n\n{message.text}"
        )
    except:
        pass
    
    await message.answer(f"✅ Ответ отправлен пользователю.")
    await state.clear()
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

# ==================== МЕНЕДЖЕРСКАЯ ПАНЕЛЬ ====================
@dp.callback_query(F.data == "manager_menu")
async def manager_menu_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await is_admin_or_manager(user_id) and user_id != OWNER_ID:
        await callback.answer("❌ У тебя нет прав менеджера!", show_alert=True)
        return
    await callback.message.edit_text(
        "🛡️ <b>ПАНЕЛЬ МЕНЕДЖЕРА</b>\n\n"
        "Ты можешь помогать пользователям и управлять ботом в рамках своих прав.",
        reply_markup=manager_menu()
    )

@dp.callback_query(F.data == "manager_give_diamonds")
async def manager_give_diamonds(callback: CallbackQuery, state: FSMContext):
    if not await is_admin_or_manager(callback.from_user.id):
        await callback.answer("❌ Нет прав!", show_alert=True)
        return
    await state.set_state(AdminGiveDiamonds.waiting_user)
    await callback.message.edit_text("💎 Введи ID пользователя, которому выдать алмазики:")

@dp.callback_query(F.data == "manager_ban")
async def manager_ban(callback: CallbackQuery, state: FSMContext):
    if not await is_admin_or_manager(callback.from_user.id):
        await callback.answer("❌ Нет прав!", show_alert=True)
        return
    await state.set_state(AdminBan.waiting_user_id)
    await callback.message.edit_text("🚫 Введи ID пользователя для бана/разбана:")

@dp.callback_query(F.data == "manager_broadcast")
async def manager_broadcast(callback: CallbackQuery, state: FSMContext):
    if not await is_admin_or_manager(callback.from_user.id):
        await callback.answer("❌ Нет прав!", show_alert=True)
        return
    await state.set_state(AdminBroadcast.waiting_text)
    await callback.message.edit_text("📢 Введи текст для рассылки всем пользователям:")

@dp.callback_query(F.data == "manager_stats")
async def manager_stats(callback: CallbackQuery):
    if not await is_admin_or_manager(callback.from_user.id):
        await callback.answer("❌ Нет прав!", show_alert=True)
        return
    async with aiosqlite.connect(DB_NAME) as db:
        total = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        open_tickets = (await (await db.execute("SELECT COUNT(*) FROM support_tickets WHERE status = 'open'")).fetchone())[0]
    text = f"📊 <b>Статистика для менеджера</b>\n\n👥 Пользователей: {total}\n🎟 Открытых тикетов: {open_tickets}"
    await callback.message.edit_text(text, reply_markup=manager_menu())

# ==================== ОБЩИЕ АДМИН/МЕНЕДЖЕР ХЕНДЛЕРЫ ====================
@dp.callback_query(F.data == "admin_give_diamonds")
async def admin_give_diamonds(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminGiveDiamonds.waiting_user)
    await callback.message.edit_text("💎 Введи ID пользователя:")

@dp.message(AdminGiveDiamonds.waiting_user)
async def give_diamonds_user(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID and not await is_admin_or_manager(message.from_user.id):
        return
    try:
        await state.update_data(user_id=int(message.text))
        await state.set_state(AdminGiveDiamonds.waiting_amount)
        await message.answer("Сколько алмазиков выдать?")
    except:
        await message.answer("❌ Неверный ID.")

@dp.message(AdminGiveDiamonds.waiting_amount)
async def give_diamonds_amount(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id != OWNER_ID and not await is_admin_or_manager(user_id):
        return
    try:
        amount = int(message.text)
        data = await state.get_data()
        target = data["user_id"]
        
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", (amount, target))
            await db.commit()
        
        await message.answer(f"✅ Выдано {amount} 💎 пользователю {target}")
        try:
            await bot.send_message(target, f"🎉 Тебе начислено +{amount} 💎 от менеджера!")
        except:
            pass
    except:
        await message.answer("❌ Неверное число.")
    await state.clear()
    if user_id == OWNER_ID:
        await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())
    else:
        await message.answer("🛡️ Менеджер-панель:", reply_markup=manager_menu())

@dp.callback_query(F.data == "admin_ban")
async def admin_ban(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminBan.waiting_user_id)
    await callback.message.edit_text("🚫 Введи ID пользователя для бана/разбана:")

@dp.message(AdminBan.waiting_user_id)
async def do_ban(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID and not await is_admin_or_manager(message.from_user.id):
        return
    try:
        uid = int(message.text)
        async with aiosqlite.connect(DB_NAME) as db:
            row = await (await db.execute("SELECT is_banned FROM users WHERE user_id = ?", (uid,))).fetchone()
            if row:
                new = 0 if row[0] == 1 else 1
                await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (new, uid))
                await db.commit()
                status = "разбанен" if new == 0 else "забанен"
                await message.answer(f"✅ Пользователь {uid} {status}.")
            else:
                await message.answer("❌ Пользователь не найден.")
    except:
        await message.answer("❌ Ошибка.")
    await state.clear()
    if message.from_user.id == OWNER_ID:
        await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())
    else:
        await message.answer("🛡️ Менеджер-панель:", reply_markup=manager_menu())

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminBroadcast.waiting_text)
    await callback.message.edit_text("📢 Введи текст для рассылки:")

@dp.message(AdminBroadcast.waiting_text)
async def do_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID and not await is_admin_or_manager(message.from_user.id):
        return
    async with aiosqlite.connect(DB_NAME) as db:
        users = await (await db.execute("SELECT user_id FROM users WHERE is_banned = 0")).fetchall()
    
    count = 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, f"📢 <b>Сообщение от команды:</b>\n\n{message.text}")
            count += 1
            await asyncio.sleep(0.03)
        except:
            pass
    
    await message.answer(f"✅ Разослано {count} пользователям.")
    await state.clear()
    if message.from_user.id == OWNER_ID:
        await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())
    else:
        await message.answer("🛡️ Менеджер-панель:", reply_markup=manager_menu())

@dp.callback_query(F.data == "admin_create_promo")
async def admin_create_promo(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminCreatePromo.waiting_code)
    await callback.message.edit_text("🎟 Введи код промокода:")

@dp.message(AdminCreatePromo.waiting_code)
async def create_promo_code(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    await state.update_data(code=message.text.strip().upper())
    await state.set_state(AdminCreatePromo.waiting_diamonds)
    await message.answer("Сколько алмазиков давать?")

@dp.message(AdminCreatePromo.waiting_diamonds)
async def create_promo_diamonds(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    await state.update_data(diamonds=int(message.text))
    await state.set_state(AdminCreatePromo.waiting_max_uses)
    await message.answer("Максимальное количество активаций?")

@dp.message(AdminCreatePromo.waiting_max_uses)
async def create_promo_max_uses(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    data = await state.get_data()
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO promo_codes (code, diamonds, max_uses, created_by) VALUES (?, ?, ?, ?)", 
                (data["code"], data["diamonds"], int(message.text), message.from_user.id)
            )
            await db.commit()
        await message.answer(f"✅ Промокод {data['code']} создан!")
    except aiosqlite.IntegrityError:
        await message.answer("❌ Такой промокод уже существует!")
    await state.clear()
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.message.edit_text(
        "🎮 <b>Video Games Bot</b>\n\nВыбери действие:",
        reply_markup=main_menu(user_id)
    )

# ==================== ЗАПУСК ====================
async def main():
    await init_db()
    logger.info("🚀 Video Games Bot v2 запущен успешно!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
