import asyncio
import aiosqlite
import logging
import random
import string
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
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
            is_manager INTEGER DEFAULT 0,
            referrer_id INTEGER DEFAULT NULL
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
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        
        await db.commit()

# ==================== FSM ====================
class AdminAddContent(StatesGroup):
    waiting_file = State()

class AdminGiveDiamonds(StatesGroup):
    waiting_user = State()
    waiting_amount = State()

class AdminBroadcast(StatesGroup):
    waiting_text = State()

class AdminBan(StatesGroup):
    waiting_user_id = State()

class AdminCreatePromo(StatesGroup):
    waiting_code = State()
    waiting_diamonds = State()
    waiting_max_uses = State()

class SupportState(StatesGroup):
    waiting_message = State()

class AdminTicketReply(StatesGroup):
    waiting_reply = State()
    ticket_id = State()

# ==================== МЕНЮ ====================
def main_menu(user_id: int, is_manager: bool = False):
    buttons = [
        [InlineKeyboardButton(text="📸 Посмотреть фото (1 💎)", callback_data="watch_photo"),
         InlineKeyboardButton(text="🎥 Посмотреть видео (2 💎)", callback_data="watch_video")],
        [InlineKeyboardButton(text="🎁 Получить бонус (+10 💎)", callback_data="daily_bonus"),
         InlineKeyboardButton(text="📋 Задания", callback_data="tasks")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🛒 Магазин", callback_data="shop")],
        [InlineKeyboardButton(text="🎟 Промокод", callback_data="redeem_promo"),
         InlineKeyboardButton(text="🛠 Поддержка", callback_data="support")]
    ]
    
    if is_manager or user_id == OWNER_ID:
        buttons.append([InlineKeyboardButton(text="🔧 Менеджер-панель", callback_data="manager_menu" if is_manager else "admin_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Загрузить контент", callback_data="admin_add_content"),
         InlineKeyboardButton(text="📋 Управление заданиями", callback_data="admin_tasks")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
         InlineKeyboardButton(text="🚫 Бан/Разбан", callback_data="admin_ban")],
        [InlineKeyboardButton(text="🎟 Активные тикеты", callback_data="admin_tickets"),
         InlineKeyboardButton(text="💎 Выдать алмазики", callback_data="admin_give_diamonds")],
        [InlineKeyboardButton(text="🎟 Создать промокод", callback_data="admin_create_promo"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])

def manager_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
         InlineKeyboardButton(text="💎 Выдать алмазики", callback_data="admin_give_diamonds")],
        [InlineKeyboardButton(text="🎟 Активные тикеты", callback_data="admin_tickets"),
         InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])

# ==================== ПРОВЕРКА ПОДПИСКИ ====================
async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# ==================== ХЕНДЛЕРЫ ====================
@dp.message(CommandStart())
async def start(message: Message):
    await get_or_create_user(message.from_user.id, message.from_user.username)
    
    if not await is_subscribed(message.from_user.id):
        text = f"🔒 <b>Подпишись на канал</b>\n\n{REQUIRED_CHANNEL_LINK}\n\nПосле подписки нажми кнопку."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]])
        await message.answer(text, reply_markup=keyboard)
        return
    
    await message.answer(
        "🎮 <b>Video Games Bot</b>\n\n"
        "Добро пожаловать! 🎉\n\n"
        "Смотри фото и видео за алмазики 💎\n"
        "Выполняй задания и получай бонусы каждый день!",
        reply_markup=main_menu(message.from_user.id)
    )

async def get_or_create_user(user_id: int, username: str = None, referrer_id: int = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, referrer_id) VALUES (?, ?, ?)",
            (user_id, username or "", referrer_id)
        )
        await db.commit()

@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        await callback.message.edit_text("✅ Спасибо за подписку!", reply_markup=main_menu(callback.from_user.id))
    else:
        await callback.answer("❌ Ты ещё не подписан!", show_alert=True)

@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        row = await (await db.execute("SELECT diamonds, is_manager FROM users WHERE user_id = ?", (callback.from_user.id,))).fetchone()
        diamonds = row[0] if row else 0
        is_manager = row[1] if row else 0
    
    text = (
        f"👤 <b>Твой профиль</b>\n\n"
        f"🆔 ID: <code>{callback.from_user.id}</code>\n"
        f"💎 Алмазики: <b>{diamonds}</b>\n"
    )
    if is_manager:
        text += "⭐ Статус: <b>Менеджер</b>\n"
    
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "daily_bonus")
async def daily_bonus(callback: CallbackQuery):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_NAME) as db:
        last = (await (await db.execute("SELECT last_bonus FROM users WHERE user_id = ?", (callback.from_user.id,))).fetchone())[0]
        if last == today:
            return await callback.answer("❌ Бонус уже получен сегодня!", show_alert=True)
        await db.execute("UPDATE users SET diamonds = diamonds + 10, last_bonus = ? WHERE user_id = ?", (today, callback.from_user.id))
        await db.commit()
    await callback.answer("🎁 +10 💎 Бонус получен!", show_alert=True)
    await profile(callback)

@dp.callback_query(F.data == "watch_photo")
async def watch_photo(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        diamonds = (await (await db.execute("SELECT diamonds FROM users WHERE user_id = ?", (callback.from_user.id,))).fetchone())[0] or 0
        if diamonds < 1:
            await callback.message.edit_text("❌ Нужно 1 💎", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]]))
            return
        content = await (await db.execute("SELECT file_id FROM content WHERE content_type = 'photo' ORDER BY RANDOM() LIMIT 1")).fetchone()
        if not content:
            return await callback.answer("❌ Фото нет!", show_alert=True)
        await db.execute("UPDATE users SET diamonds = diamonds - 1 WHERE user_id = ?", (callback.from_user.id,))
        await db.commit()
    await bot.send_photo(callback.from_user.id, content[0], caption=f"📸 <b>Вот твоё фото!</b>\n\n💎 Баланс: <b>{diamonds-1}</b>")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➡️ Далее", callback_data="watch_photo"), InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]])
    await bot.send_message(callback.from_user.id, "Что дальше? 👇", reply_markup=keyboard)

@dp.callback_query(F.data == "watch_video")
async def watch_video(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        diamonds = (await (await db.execute("SELECT diamonds FROM users WHERE user_id = ?", (callback.from_user.id,))).fetchone())[0] or 0
        if diamonds < 2:
            await callback.message.edit_text("❌ Нужно 2 💎", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]]))
            return
        content = await (await db.execute("SELECT file_id FROM content WHERE content_type = 'video' ORDER BY RANDOM() LIMIT 1")).fetchone()
        if not content:
            return await callback.answer("❌ Видео нет!", show_alert=True)
        await db.execute("UPDATE users SET diamonds = diamonds - 2 WHERE user_id = ?", (callback.from_user.id,))
        await db.commit()
    await bot.send_video(callback.from_user.id, content[0], caption=f"🎥 <b>Вот твоё видео!</b>\n\n💎 Баланс: <b>{diamonds-2}</b>")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➡️ Далее", callback_data="watch_video"), InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]])
    await bot.send_message(callback.from_user.id, "Что дальше? 👇", reply_markup=keyboard)

@dp.callback_query(F.data == "tasks")
async def tasks(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        tasks = await (await db.execute("SELECT channel_username, reward FROM tasks WHERE is_active = 1")).fetchall()
    text = "📋 <b>Активные задания</b>\n\n" + "\n".join([f"• Подпишись на {t[0]} → +{t[1]} 💎" for t in tasks]) if tasks else "😔 Заданий пока нет"
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "shop")
async def shop(callback: CallbackQuery):
    await callback.message.edit_text("🛒 Напиши в поддержку для покупки алмазиков.", reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "redeem_promo")
async def redeem_promo_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state("redeem_promo_code")
    await callback.message.edit_text("🎟 Введи промокод:")

@dp.message(lambda m: True)
async def redeem_promo(message: Message, state: FSMContext):
    current = await state.get_state()
    if current != "redeem_promo_code": return
    
    code = message.text.strip().upper()
    async with aiosqlite.connect(DB_NAME) as db:
        promo = await (await db.execute("SELECT id, diamonds, max_uses, current_uses FROM promo_codes WHERE code = ?", (code,))).fetchone()
        if not promo:
            await message.answer("❌ Промокод не найден!")
            await state.clear()
            return
        
        if promo[3] >= promo[2]:
            await message.answer("❌ Промокод уже исчерпан!")
            await state.clear()
            return
        
        await db.execute("UPDATE promo_codes SET current_uses = current_uses + 1 WHERE id = ?", (promo[0],))
        await db.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", (promo[1], message.from_user.id))
        await db.commit()
    
    await message.answer(f"✅ Промокод активирован! +{promo[1]} 💎")
    await state.clear()

@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SupportState.waiting_message)
    await callback.message.edit_text("🛠 Напиши сообщение в поддержку:")

@dp.message(SupportState.waiting_message)
async def support_save(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("INSERT INTO support_tickets (user_id) VALUES (?) RETURNING id", (message.from_user.id,))
        ticket_id = (await cursor.fetchone())[0]
        await db.execute("INSERT INTO support_messages (ticket_id, user_id, message) VALUES (?, ?, ?)", (ticket_id, message.from_user.id, message.text))
        await db.commit()
    await message.answer("✅ Тикет создан!")
    await state.clear()

# ==================== АДМИН / МЕНЕДЖЕР ====================
@dp.callback_query(F.data == "admin_menu")
async def admin_menu_handler(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    await callback.message.edit_text("🔧 <b>Админ-панель</b>", reply_markup=admin_menu())

@dp.callback_query(F.data == "manager_menu")
async def manager_menu_handler(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        is_manager = (await (await db.execute("SELECT is_manager FROM users WHERE user_id = ?", (callback.from_user.id,))).fetchone())[0]
    if not is_manager and callback.from_user.id != OWNER_ID: return
    await callback.message.edit_text("⭐ <b>Менеджер-панель</b>", reply_markup=manager_menu())

@dp.callback_query(F.data == "admin_add_content")
async def admin_add_content(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminAddContent.waiting_file)
    await callback.message.edit_text("📤 Кидай фото или видео:")

@dp.message(AdminAddContent.waiting_file, F.photo | F.video)
async def save_content(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    content_type = "photo" if message.photo else "video"
    file_id = message.photo[-1].file_id if message.photo else message.video.file_id
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO content (file_id, content_type, added_by) VALUES (?, ?, ?)", (file_id, content_type, message.from_user.id))
        await db.commit()
    await message.answer(f"✅ {content_type.capitalize()} сохранён!")

@dp.callback_query(F.data == "admin_tasks")
async def admin_tasks(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        tasks = await (await db.execute("SELECT id, channel_username, reward FROM tasks WHERE is_active = 1")).fetchall()
    text = "📋 <b>Задания</b>\n" + "\n".join([f"#{t[0]} | {t[1]} → +{t[2]} 💎" for t in tasks]) if tasks else "Заданий нет"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add_task"),
         InlineKeyboardButton(text="🗑 Удалить", callback_data="admin_delete_task")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        total = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        content = (await (await db.execute("SELECT COUNT(*) FROM content")).fetchone())[0]
        diamonds = (await (await db.execute("SELECT SUM(diamonds) FROM users")).fetchone())[0] or 0
    await callback.message.edit_text(f"📊 <b>Статистика</b>\nПользователей: {total}\nКонтента: {content}\nАлмазиков: {diamonds}", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_give_diamonds")
async def admin_give_diamonds(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminGiveDiamonds.waiting_user)
    await callback.message.edit_text("💎 Введи ID пользователя:")

@dp.message(AdminGiveDiamonds.waiting_user)
async def give_diamonds_user(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    try:
        await state.update_data(user_id=int(message.text))
        await state.set_state(AdminGiveDiamonds.waiting_amount)
        await message.answer("Сколько алмазиков выдать?")
    except:
        await message.answer("❌ Неверный ID.")

@dp.message(AdminGiveDiamonds.waiting_amount)
async def give_diamonds_amount(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    try:
        amount = int(message.text)
        data = await state.get_data()
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", (amount, data["user_id"]))
            await db.commit()
        await message.answer(f"✅ Выдано {amount} 💎 пользователю {data['user_id']}")
        try:
            await bot.send_message(data["user_id"], f"🎉 Тебе начислено {amount} 💎!")
        except:
            pass
    except:
        await message.answer("❌ Неверное число.")
    await state.clear()

@dp.callback_query(F.data == "admin_tickets")
async def admin_tickets(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        tickets = await (await db.execute("SELECT id, user_id FROM support_tickets WHERE status = 'open' ORDER BY id DESC LIMIT 10")).fetchall()
    if not tickets:
        text = "🎟 Нет активных тикетов."
    else:
        text = "🎟 <b>Активные тикеты</b>\n" + "\n".join([f"#{t[0]} | {t[1]}" for t in tickets])
    await callback.message.edit_text(text, reply_markup=admin_menu())

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
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO promo_codes (code, diamonds, max_uses, created_by) VALUES (?, ?, ?, ?)",
            (data["code"], data["diamonds"], int(message.text), message.from_user.id)
        )
        await db.commit()
    await message.answer(f"✅ Промокод {data['code']} создан!")
    await state.clear()

# ==================== ЗАПУСК ====================
async def main():
    await init_db()
    logger.info("🚀 Video Games Bot запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())