import asyncio
import aiosqlite
import logging
import random
from datetime import datetime, timedelta
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

# Обязательная подписка
REQUIRED_CHANNEL_ID = -1003969378970
REQUIRED_CHANNEL_LINK = "https://t.me/rezerv_video_pita"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ==================== БАЗА ДАННЫХ ====================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Пользователи
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                diamonds INTEGER DEFAULT 0,
                last_bonus TEXT,
                is_banned INTEGER DEFAULT 0
            )
        """)

        # Контент (фото и видео)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT,
                content_type TEXT,  -- 'photo' или 'video'
                added_by INTEGER,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Задания (подписки)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_username TEXT,
                reward INTEGER DEFAULT 5,
                is_active INTEGER DEFAULT 1
            )
        """)

        # Тикеты поддержки
        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                status TEXT DEFAULT 'open'
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER,
                user_id INTEGER,
                message TEXT,
                is_admin INTEGER DEFAULT 0
            )
        """)

        await db.commit()
        logger.info("✅ База данных готова")


# ==================== FSM ====================
class AdminAddContent(StatesGroup):
    waiting_file = State()

class AdminAddTask(StatesGroup):
    waiting_channel = State()
    waiting_reward = State()

class SupportState(StatesGroup):
    waiting_message = State()


# ==================== МЕНЮ ====================
def main_menu(user_id: int):
    buttons = [
        [InlineKeyboardButton(text="📸 Посмотреть фото (1 💎)", callback_data="watch_photo"),
         InlineKeyboardButton(text="🎥 Посмотреть видео (2 💎)", callback_data="watch_video")],
        [InlineKeyboardButton(text="🎁 Получить бонус (+10 💎)", callback_data="daily_bonus"),
         InlineKeyboardButton(text="📋 Задания", callback_data="tasks")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🛒 Магазин", callback_data="shop")],
        [InlineKeyboardButton(text="🛠 Поддержка", callback_data="support")]
    ]
    if user_id == OWNER_ID:
        buttons.append([InlineKeyboardButton(text="🔧 Админ-панель", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Загрузить контент", callback_data="admin_add_content"),
         InlineKeyboardButton(text="📋 Управление заданиями", callback_data="admin_tasks")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
         InlineKeyboardButton(text="🚫 Бан/Разбан", callback_data="admin_ban")],
        [InlineKeyboardButton(text="🎟 Тикеты", callback_data="admin_tickets"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="💎 Выдать алмазики", callback_data="admin_give_diamonds"),
         InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])


# ==================== ХЕНДЛЕРЫ ====================
@dp.message(CommandStart())
async def start(message: Message):
    await get_or_create_user(message.from_user.id, message.from_user.username)
    
    if not await is_subscribed(message.from_user.id):
        text = (
            "🔒 <b>Для использования бота нужно подписаться на канал</b>\n\n"
            f"Подпишись: {REQUIRED_CHANNEL_LINK}\n\n"
            "После подписки нажми кнопку ниже."
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]
        ])
        await message.answer(text, reply_markup=keyboard)
        return
    
    await message.answer(
        "🎮 <b>Video Games Bot</b>\n\n"
        "Смотри фото и видео за алмазики 💎\n"
        "Выполняй задания и получай бонусы!",
        reply_markup=main_menu(message.from_user.id)
    )


async def get_or_create_user(user_id: int, username: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username or "")
        )
        await db.commit()


async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False


@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        await callback.message.edit_text(
            "✅ <b>Спасибо за подписку!</b>\n\nДобро пожаловать!",
            reply_markup=main_menu(callback.from_user.id)
        )
    else:
        await callback.answer("❌ Ты ещё не подписан на канал!", show_alert=True)


@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT diamonds FROM users WHERE user_id = ?", (callback.from_user.id,))
        diamonds = (await cursor.fetchone())[0] or 0

    text = (
        f"👤 <b>Твой профиль</b>\n\n"
        f"🆔 ID: <code>{callback.from_user.id}</code>\n"
        f"💎 Алмазики: <b>{diamonds}</b>\n\n"
        f"Смотри контент и выполняй задания!"
    )
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))


@dp.callback_query(F.data == "daily_bonus")
async def daily_bonus(callback: CallbackQuery):
    user_id = callback.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT last_bonus FROM users WHERE user_id = ?", (user_id,))
        last_bonus = (await cursor.fetchone())[0]

        if last_bonus == today:
            return await callback.answer("❌ Бонус уже получен сегодня!", show_alert=True)

        await db.execute(
            "UPDATE users SET diamonds = diamonds + 10, last_bonus = ? WHERE user_id = ?",
            (today, user_id)
        )
        await db.commit()

    await callback.answer("✅ +10 💎 Бонус получен!", show_alert=True)
    await profile(callback)


@dp.callback_query(F.data == "watch_photo")
async def watch_photo(callback: CallbackQuery):
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT diamonds FROM users WHERE user_id = ?", (user_id,))
        diamonds = (await cursor.fetchone())[0] or 0

        if diamonds < 1:
            await callback.message.edit_text(
                "❌ <b>Недостаточно алмазиков!</b>\n\nНужно 1 💎",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
                ])
            )
            return

        cursor = await db.execute(
            "SELECT file_id FROM content WHERE content_type = 'photo' ORDER BY RANDOM() LIMIT 1"
        )
        content = await cursor.fetchone()

        if not content:
            return await callback.answer("❌ Фото пока нет в базе!", show_alert=True)

        await db.execute("UPDATE users SET diamonds = diamonds - 1 WHERE user_id = ?", (user_id,))
        await db.commit()

    await bot.send_photo(
        user_id, 
        content[0], 
        caption=f"📸 <b>Вот твоё фото!</b>\n\n💎 Твой баланс: <b>{diamonds - 1}</b>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Далее", callback_data="watch_photo"),
         InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
    ])
    await bot.send_message(user_id, "Что дальше?", reply_markup=keyboard)
    await callback.answer("✅ -1 💎", show_alert=True)


@dp.callback_query(F.data == "watch_video")
async def watch_video(callback: CallbackQuery):
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT diamonds FROM users WHERE user_id = ?", (user_id,))
        diamonds = (await cursor.fetchone())[0] or 0

        if diamonds < 2:
            await callback.message.edit_text(
                "❌ <b>Недостаточно алмазиков!</b>\n\nНужно 2 💎",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
                ])
            )
            return

        cursor = await db.execute(
            "SELECT file_id FROM content WHERE content_type = 'video' ORDER BY RANDOM() LIMIT 1"
        )
        content = await cursor.fetchone()

        if not content:
            return await callback.answer("❌ Видео пока нет в базе!", show_alert=True)

        await db.execute("UPDATE users SET diamonds = diamonds - 2 WHERE user_id = ?", (user_id,))
        await db.commit()

    await bot.send_video(
        user_id, 
        content[0], 
        caption=f"🎥 <b>Вот твоё видео!</b>\n\n💎 Твой баланс: <b>{diamonds - 2}</b>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Далее", callback_data="watch_video"),
         InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
    ])
    await bot.send_message(user_id, "Что дальше?", reply_markup=keyboard)
    await callback.answer("✅ -2 💎", show_alert=True)


@dp.callback_query(F.data == "tasks")
async def tasks(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT channel_username, reward FROM tasks WHERE is_active = 1")
        tasks_list = await cursor.fetchall()

    if not tasks_list:
        text = "📋 <b>Задания</b>\n\nПока нет активных заданий."
    else:
        text = "📋 <b>Задания</b>\n\n"
        for channel, reward in tasks_list:
            text += f"• Подпишись на {channel} → +{reward} 💎\n"

    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))


@dp.callback_query(F.data == "shop")
async def shop(callback: CallbackQuery):
    text = (
        "🛒 <b>Магазин алмазиков</b>\n\n"
        "Хочешь купить алмазики?\n"
        "Напиши в поддержку — там обсудим цену и способ оплаты."
    )
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))


@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SupportState.waiting_message)
    await callback.message.edit_text("🛠 <b>Поддержка</b>\n\nНапиши своё сообщение:")


@dp.message(SupportState.waiting_message)
async def support_save(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "INSERT INTO support_tickets (user_id) VALUES (?) RETURNING id",
            (message.from_user.id,)
        )
        ticket_id = (await cursor.fetchone())[0]
        await db.execute(
            "INSERT INTO support_messages (ticket_id, user_id, message) VALUES (?, ?, ?)",
            (ticket_id, message.from_user.id, message.text)
        )
        await db.commit()

    await message.answer("✅ Тикет создан! Мы ответим скоро.")
    try:
        await bot.send_message(OWNER_ID, f"🎟 Новый тикет #{ticket_id} от @{message.from_user.username}")
    except:
        pass
    await state.clear()


# ==================== АДМИН ПАНЕЛЬ ====================
@dp.callback_query(F.data == "admin_menu")
async def admin_menu_handler(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        return
    await callback.message.edit_text("🔧 <b>Админ-панель — Video Games Bot</b>", reply_markup=admin_menu())


@dp.callback_query(F.data == "admin_add_content")
async def admin_add_content(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        return
    await state.set_state(AdminAddContent.waiting_file)
    await callback.message.edit_text("📤 Кидай фото или видео (можно много подряд):")


@dp.message(AdminAddContent.waiting_file, F.photo | F.video)
async def admin_save_content(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return

    content_type = "photo" if message.photo else "video"
    file_id = message.photo[-1].file_id if message.photo else message.video.file_id

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO content (file_id, content_type, added_by) VALUES (?, ?, ?)",
            (file_id, content_type, message.from_user.id)
        )
        await db.commit()

    await message.answer(f"✅ {content_type.capitalize()} сохранён!")


@dp.callback_query(F.data == "admin_tasks")
async def admin_tasks(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, channel_username, reward FROM tasks WHERE is_active = 1")
        tasks = await cursor.fetchall()

    text = "📋 <b>Активные задания</b>\n\n"
    for tid, channel, reward in tasks:
        text += f"#{tid} | {channel} → +{reward} 💎\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить задание", callback_data="admin_add_task"),
         InlineKeyboardButton(text="🗑 Удалить задание", callback_data="admin_delete_task")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        return
    await state.set_state("admin_broadcast_text")
    await callback.message.edit_text("📢 Введи текст для рассылки:")


@dp.callback_query(F.data == "admin_ban")
async def admin_ban(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        return
    await state.set_state("admin_ban_user")
    await callback.message.edit_text("🚫 Введи ID пользователя для бана/разбана:")


@dp.message(lambda m: True)
async def handle_admin_actions(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if message.from_user.id != OWNER_ID:
        return

    if current_state == "admin_ban_user":
        try:
            uid = int(message.text)
            async with aiosqlite.connect(DB_NAME) as db:
                cursor = await db.execute("SELECT is_banned FROM users WHERE user_id = ?", (uid,))
                row = await cursor.fetchone()
                if row:
                    new_status = 0 if row[0] == 1 else 1
                    await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (new_status, uid))
                    await db.commit()
                    await message.answer(f"✅ Пользователь {uid} {'разбанен' if new_status == 0 else 'забанен'}.")
                else:
                    await message.answer("❌ Пользователь не найден.")
        except:
            await message.answer("❌ Неверный ID.")
        await state.clear()

    elif current_state == "admin_broadcast_text":
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT user_id FROM users WHERE is_banned = 0")
            users = await cursor.fetchall()

        count = 0
        for (uid,) in users:
            try:
                await bot.send_message(uid, f"📢 <b>Сообщение от админа:</b>\n\n{message.text}")
                count += 1
            except:
                pass
        await message.answer(f"✅ Разослано {count} пользователям.")
        await state.clear()


@dp.message(lambda m: True)
async def handle_broadcast(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "admin_broadcast_text" or message.from_user.id != OWNER_ID:
        return

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id FROM users WHERE is_banned = 0")
        users = await cursor.fetchall()

    count = 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, f"📢 <b>Сообщение от админа:</b>\n\n{message.text}")
            count += 1
        except:
            pass

    await message.answer(f"✅ Разослано {count} пользователям.")
    await state.clear()


# ==================== ЗАПУСК ====================
async def main():
    await init_db()
    logger.info("🚀 Video Games Bot запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())