import asyncio
import aiosqlite
import logging
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
        await db.execute("""CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, diamonds INTEGER DEFAULT 0, last_bonus TEXT, is_banned INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS content (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, content_type TEXT, added_by INTEGER)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_username TEXT, reward INTEGER DEFAULT 5, is_active INTEGER DEFAULT 1)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS support_tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, status TEXT DEFAULT 'open')""")
        await db.execute("""CREATE TABLE IF NOT EXISTS support_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER, user_id INTEGER, message TEXT, is_admin INTEGER DEFAULT 0)""")
        await db.commit()

# ==================== FSM ====================
class AdminAddContent(StatesGroup):
    waiting_file = State()

class AdminGiveDiamonds(StatesGroup):
    waiting_user = State()
    waiting_amount = State()

class SupportState(StatesGroup):
    waiting_message = State()

# ==================== МЕНЮ ====================
def main_menu(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Посмотреть фото (1 💎)", callback_data="watch_photo"),
         InlineKeyboardButton(text="🎥 Посмотреть видео (2 💎)", callback_data="watch_video")],
        [InlineKeyboardButton(text="🎁 Получить бонус (+10 💎)", callback_data="daily_bonus"),
         InlineKeyboardButton(text="📋 Задания", callback_data="tasks")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🛒 Магазин", callback_data="shop")],
        [InlineKeyboardButton(text="🛠 Поддержка", callback_data="support")],
        [InlineKeyboardButton(text="🔧 Админ-панель", callback_data="admin_menu")] if user_id == OWNER_ID else []
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Загрузить контент", callback_data="admin_add_content"),
         InlineKeyboardButton(text="📋 Управление заданиями", callback_data="admin_tasks")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
         InlineKeyboardButton(text="🚫 Бан/Разбан", callback_data="admin_ban")],
        [InlineKeyboardButton(text="🎟 Активные тикеты", callback_data="admin_tickets"),
         InlineKeyboardButton(text="💎 Выдать алмазики", callback_data="admin_give_diamonds")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
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
        text = (
            "🔒 <b>Доступ ограничен</b>\n\n"
            "Для использования бота необходимо подписаться на наш канал:\n"
            f"{REQUIRED_CHANNEL_LINK}\n\n"
            "После подписки нажми кнопку ниже 👇"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]])
        await message.answer(text, reply_markup=keyboard)
        return
    
    await message.answer(
        "🎮 <b>Video Games Bot</b>\n\n"
        "Добро пожаловать! 🎉\n\n"
        "Здесь ты можешь смотреть крутые фото и видео за алмазики 💎\n"
        "Выполняй задания и получай бонусы каждый день!",
        reply_markup=main_menu(message.from_user.id)
    )

async def get_or_create_user(user_id: int, username: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username or ""))
        await db.commit()

@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        await callback.message.edit_text(
            "✅ <b>Спасибо за подписку!</b>\n\n"
            "Теперь тебе доступен весь контент бота! 🚀",
            reply_markup=main_menu(callback.from_user.id)
        )
    else:
        await callback.answer("❌ Ты ещё не подписан на канал!", show_alert=True)

@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        diamonds = (await (await db.execute("SELECT diamonds FROM users WHERE user_id = ?", (callback.from_user.id,))).fetchone())[0] or 0
    await callback.message.edit_text(
        f"👤 <b>Твой профиль</b>\n\n"
        f"🆔 ID: <code>{callback.from_user.id}</code>\n"
        f"💎 Алмазики: <b>{diamonds}</b>\n\n"
        f"Смотри контент и выполняй задания, чтобы заработать ещё! 💪",
        reply_markup=main_menu(callback.from_user.id)
    )

@dp.callback_query(F.data == "daily_bonus")
async def daily_bonus(callback: CallbackQuery):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_NAME) as db:
        last = (await (await db.execute("SELECT last_bonus FROM users WHERE user_id = ?", (callback.from_user.id,))).fetchone())[0]
        if last == today:
            return await callback.answer("❌ Бонус уже получен сегодня! Приходи завтра 😊", show_alert=True)
        await db.execute("UPDATE users SET diamonds = diamonds + 10, last_bonus = ? WHERE user_id = ?", (today, callback.from_user.id))
        await db.commit()
    await callback.answer("🎁 +10 💎 Бонус получен!", show_alert=True)
    await profile(callback)

@dp.callback_query(F.data == "watch_photo")
async def watch_photo(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        diamonds = (await (await db.execute("SELECT diamonds FROM users WHERE user_id = ?", (callback.from_user.id,))).fetchone())[0] or 0
        if diamonds < 1:
            await callback.message.edit_text("❌ <b>Недостаточно алмазиков!</b>\n\nНужно минимум 1 💎", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")]]))
            return
        content = await (await db.execute("SELECT file_id FROM content WHERE content_type = 'photo' ORDER BY RANDOM() LIMIT 1")).fetchone()
        if not content:
            return await callback.answer("😔 Фото пока нет в базе!", show_alert=True)
        await db.execute("UPDATE users SET diamonds = diamonds - 1 WHERE user_id = ?", (callback.from_user.id,))
        await db.commit()
    await bot.send_photo(callback.from_user.id, content[0], caption=f"📸 <b>Вот твоё фото!</b>\n\n💎 Твой баланс: <b>{diamonds-1}</b>")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➡️ Следующее", callback_data="watch_photo"), InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")]])
    await bot.send_message(callback.from_user.id, "Что дальше? 👇", reply_markup=keyboard)

@dp.callback_query(F.data == "watch_video")
async def watch_video(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        diamonds = (await (await db.execute("SELECT diamonds FROM users WHERE user_id = ?", (callback.from_user.id,))).fetchone())[0] or 0
        if diamonds < 2:
            await callback.message.edit_text("❌ <b>Недостаточно алмазиков!</b>\n\nНужно минимум 2 💎", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")]]))
            return
        content = await (await db.execute("SELECT file_id FROM content WHERE content_type = 'video' ORDER BY RANDOM() LIMIT 1")).fetchone()
        if not content:
            return await callback.answer("😔 Видео пока нет в базе!", show_alert=True)
        await db.execute("UPDATE users SET diamonds = diamonds - 2 WHERE user_id = ?", (callback.from_user.id,))
        await db.commit()
    await bot.send_video(callback.from_user.id, content[0], caption=f"🎥 <b>Вот твоё видео!</b>\n\n💎 Твой баланс: <b>{diamonds-2}</b>")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➡️ Следующее", callback_data="watch_video"), InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")]])
    await bot.send_message(callback.from_user.id, "Что дальше? 👇", reply_markup=keyboard)

@dp.callback_query(F.data == "tasks")
async def tasks(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        tasks = await (await db.execute("SELECT channel_username, reward FROM tasks WHERE is_active = 1")).fetchall()
    text = "📋 <b>Активные задания</b>\n\n" + "\n".join([f"• Подпишись на {t[0]} → +{t[1]} 💎" for t in tasks]) if tasks else "😔 Пока нет активных заданий"
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "shop")
async def shop(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛒 <b>Магазин алмазиков</b>\n\n"
        "Хочешь купить алмазики?\n"
        "Напиши в поддержку — там обсудим цену и способ оплаты 💬",
        reply_markup=main_menu(callback.from_user.id)
    )

@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SupportState.waiting_message)
    await callback.message.edit_text("🛠 <b>Техническая поддержка</b>\n\nНапиши своё сообщение, и мы ответим в ближайшее время:")

@dp.message(SupportState.waiting_message)
async def support_save(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("INSERT INTO support_tickets (user_id) VALUES (?) RETURNING id", (message.from_user.id,))
        ticket_id = (await cursor.fetchone())[0]
        await db.execute("INSERT INTO support_messages (ticket_id, user_id, message) VALUES (?, ?, ?)", (ticket_id, message.from_user.id, message.text))
        await db.commit()
    await message.answer("✅ <b>Тикет создан!</b>\n\nМы ответим тебе в ближайшее время. Спасибо за обращение! 🙏")
    await state.clear()

# ==================== АДМИН-ПАНЕЛЬ ====================
@dp.callback_query(F.data == "admin_menu")
async def admin_menu_handler(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    await callback.message.edit_text("🔧 <b>Админ-панель — Video Games Bot</b>", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_add_content")
async def admin_add_content(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminAddContent.waiting_file)
    await callback.message.edit_text("📤 <b>Загрузка контента</b>\n\nКидай фото или видео (можно много подряд):")

@dp.message(AdminAddContent.waiting_file, F.photo | F.video)
async def save_content(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    content_type = "photo" if message.photo else "video"
    file_id = message.photo[-1].file_id if message.photo else message.video.file_id
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO content (file_id, content_type, added_by) VALUES (?, ?, ?)", (file_id, content_type, message.from_user.id))
        await db.commit()
    await message.answer(f"✅ <b>{content_type.capitalize()} успешно сохранён!</b>")

@dp.callback_query(F.data == "admin_tasks")
async def admin_tasks(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        tasks = await (await db.execute("SELECT id, channel_username, reward FROM tasks WHERE is_active = 1")).fetchall()
    text = "📋 <b>Управление заданиями</b>\n\n" + "\n".join([f"#{t[0]} | {t[1]} → +{t[2]} 💎" for t in tasks]) if tasks else "Заданий пока нет"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить задание", callback_data="admin_add_task"),
         InlineKeyboardButton(text="🗑 Удалить задание", callback_data="admin_delete_task")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        total_users = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        total_content = (await (await db.execute("SELECT COUNT(*) FROM content")).fetchone())[0]
        total_diamonds = (await (await db.execute("SELECT SUM(diamonds) FROM users")).fetchone())[0] or 0
    await callback.message.edit_text(
        f"📊 <b>Общая статистика</b>\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"📁 Контента в базе: <b>{total_content}</b>\n"
        f"💎 Всего алмазиков у игроков: <b>{total_diamonds}</b>",
        reply_markup=admin_menu()
    )

@dp.callback_query(F.data == "admin_give_diamonds")
async def admin_give_diamonds(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminGiveDiamonds.waiting_user)
    await callback.message.edit_text("💎 <b>Выдача алмазиков</b>\n\nВведи ID пользователя:")

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
        await message.answer(f"✅ <b>Успешно!</b> Выдано {amount} 💎 пользователю {data['user_id']}")
        try:
            await bot.send_message(data["user_id"], f"🎉 <b>Поздравляем!</b>\n\nТебе начислено <b>{amount} алмазиков</b>!\n\nСпасибо за игру! 🚀")
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
    text = "🎟 <b>Активные тикеты</b>\n\n" + "\n".join([f"#{t[0]} | Пользователь: {t[1]}" for t in tickets]) if tickets else "😊 Нет активных тикетов"
    await callback.message.edit_text(text, reply_markup=admin_menu())

# ==================== ЗАПУСК ====================
async def main():
    await init_db()
    logger.info("🚀 Video Games Bot запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())