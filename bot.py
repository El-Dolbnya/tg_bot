import asyncio
import json
import sqlite3
from datetime import datetime, time
from typing import Dict, List, Optional
import logging
import os
import sys

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.filters import Command, CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ========== КОНФИГУРАЦИЯ ПУТЕЙ ==========
VOLUME_PATH = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "/data")

# ✅ ИСПОЛЬЗУЕМ ТОТ ЖЕ ФАЙЛ БД - ВСЕ ДАННЫЕ СОХРАНЯТСЯ!
DB_PATH = os.path.join(VOLUME_PATH, 'voting.db')  # ← ОРИГИНАЛЬНОЕ ИМЯ!

JSON_EXPORT_PATH = os.path.join(VOLUME_PATH, 'exports')
os.makedirs(JSON_EXPORT_PATH, exist_ok=True)

BOT_TOKEN = os.getenv("BOT_TOKEN")

print("=== DEBUG ENV ===")
print(f"BOT_TOKEN length: {len(os.getenv('BOT_TOKEN', 'NOT_FOUND'))}")
print(f"DB_PATH: {DB_PATH}")
print(f"All keys: {list(os.environ.keys())}")
print("=== END DEBUG ===")

if not BOT_TOKEN:
    print("CRITICAL: BOT_TOKEN is empty!")
    exit(1)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

# ========== КОНФИГУРАЦИЯ ==========
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1001178736983"))
CHANNEL_ID_2 = int(os.getenv("CHANNEL_ID_2", "-1003633293081"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@new_people32")
CHANNEL_USERNAME_2 = os.getenv("CHANNEL_USERNAME_2", "@genesis_bryansk")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1388134102"))

os.makedirs(JSON_EXPORT_PATH, exist_ok=True)

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ========== НОМИНАЦИИ И ФИНАЛИСТЫ ==========
NOMINATIONS = [
    {
        "id": "public_space",
        "title": "1. Общественное пространство года",
        "finalists": ["Курган", "Парк Толстого", "Набережная"]
    },
    {
        "id": "cozy_place",
        "title": "2. Уютное место года",
        "finalists": ["Щебетун ДК", "Дача", "Микале"]
    },
    {
        "id": "coffee_shop",
        "title": "3. Кофейня года",
        "finalists": ["Микале", "Механика", "Твоя кофейня"]
    },
    {
        "id": "gastro_project",
        "title": "4. Гастропроект года",
        "finalists": ["Фиби", "Итальянцы", "Терки"]
    },
    {
        "id": "night_location",
        "title": "5. Ночная локация года",
        "finalists": ["Цензура", "Тако Бойс", "Роллингс"]
    },
    {
        "id": "discovery",
        "title": "6. Открытие года",
        "finalists": ["Аэротермы", "Терки", "Чебурекми"]
    },
    {
        "id": "event",
        "title": "7. Событие года",
        "finalists": ["Премия БРЯ", "\"Рок-выпускной\" от Брянского Шума", "Фестиваль кофе от Микале"]
    },
    {
        "id": "person",
        "title": "8. Личность года",
        "finalists": ["Роман Формин", "Мария Охременко", "Сергей Лапенков"]
    },
    {
        "id": "community",
        "title": "9. Сообщество года",
        "finalists": ["Пространство", "БРЯ", "Партийный актив \"Новые люди\""]
    },
    {
        "id": "initiative",
        "title": "10. Инициатива года",
        "finalists": ["Путеводитель Брянска", "субботники от Пространства", "памятник детству (Слон на цирке)"]
    }
]

# ========== БАЗА ДАННЫХ ==========
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # СТАРЫЕ ТАБЛИЦЫ (СОХРАНЯЮТСЯ!)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_active DATETIME DEFAULT CURRENT_TIMESTAMP,
        is_finished BOOLEAN DEFAULT 0
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        nomination_id TEXT,
        nomination_title TEXT,
        answer_text TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, nomination_id)
    )
    ''')

    # ✅ НОВЫЕ ТАБЛИЦЫ ДЛЯ ФИНАЛЬНОГО ГОЛОСОВАНИЯ
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS final_votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        nomination_id TEXT,
        nomination_title TEXT,
        finalist_name TEXT,
        is_custom BOOLEAN DEFAULT 0,
        custom_text TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, nomination_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS custom_proposals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        nomination_id TEXT,
        nomination_title TEXT,
        proposal_text TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS bot_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message_id INTEGER,
        chat_id INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.commit()
    conn.close()
    logger.info("✅ БД инициализирована (все старые данные сохранены)")

init_db()

# ========== FSM ==========
class FinalVotingStates(StatesGroup):
    checking_subscription = State()
    voting_process = State()
    custom_proposal = State()
    finished = State()

# Остальной код идентичен предыдущему...
# (функции save_message_id, delete_old_messages, check_subscription, ask_next_nomination, show_final_results_page)

def save_message_id(user_id: int, message_id: int, chat_id: int):
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO bot_messages (user_id, message_id, chat_id) VALUES (?, ?, ?)', 
                     (user_id, message_id, chat_id))
        conn.commit()
    finally:
        conn.close()

async def delete_old_messages(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT message_id, chat_id FROM bot_messages WHERE user_id = ?', (user_id,))
        messages = cursor.fetchall()
        
        for msg_id, chat_id in messages:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                await asyncio.sleep(0.05)
            except:
                pass
        
        cursor.execute('DELETE FROM bot_messages WHERE user_id = ?', (user_id,))
        conn.commit()
    finally:
        conn.close()

async def check_subscription(user_id: int) -> bool:
    channels = [CHANNEL_ID, CHANNEL_ID_2]
    for channel_id in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except:
            return False
    return True

async def ask_next_nomination(message: types.Message, state: FSMContext, user_id: int, current_index: int):
    if current_index >= len(NOMINATIONS):
        conn = get_db_connection()
        conn.execute('UPDATE users SET is_finished = 1 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        
        await message.answer(
            "🎉 <b>Спасибо за голосование!</b>\n\n"
            "✅ Ваши голоса учтены!\n\n"
            "<i>Изменить: <code>/finalrevote</code></i>",
            parse_mode="HTML"
        )
        await state.set_state(FinalVotingStates.finished)
        return

    nomination = NOMINATIONS[current_index]
    builder = InlineKeyboardBuilder()
    
    for i, finalist in enumerate(nomination["finalists"], 1):
        builder.add(InlineKeyboardButton(
            text=f"{i}. {finalist}", 
            callback_data=f"vote:{nomination['id']}:{finalist}"
        ))
    
    builder.add(InlineKeyboardButton(text="✏️ Предложить своего", callback_data=f"custom:{nomination['id']}"))
    builder.add(InlineKeyboardButton(text="➡️ Пропустить", callback_data=f"skip:{nomination['id']}"))
    builder.adjust(2)
    
    text = (
        f"<b>🏆 {nomination['title']}</b>\n\n"
        f"👥 <b>Выберите финалиста:</b>\n\n"
        f"📊 {current_index + 1}/{len(NOMINATIONS)}"
    )
    
    msg = await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    save_message_id(user_id, msg.message_id, msg.chat.id)
    
    await state.update_data(current_index=current_index)
    await state.set_state(FinalVotingStates.voting_process)

async def show_final_results_page(chat_id: int, page: int = 0, edit_message_id: int = None):
    if page < 0 or page >= len(NOMINATIONS):
        return
    
    nomination = NOMINATIONS[page]
    conn = get_db_connection()
    cursor = conn.cursor()
    
    text = f"📊 <b>ФИНАЛЬНОЕ ГОЛОСОВАНИЕ</b>\n\n🔸 <b>{nomination['title']}</b>\n\n"
    
    cursor.execute('''
        SELECT finalist_name, COUNT(*) as cnt 
        FROM final_votes 
        WHERE nomination_id = ? AND finalist_name != 'ПРОПУЩЕНО'
        GROUP BY finalist_name 
        ORDER BY cnt DESC
    ''', (nomination['id'],))
    
    votes = cursor.fetchall()
    if votes:
        for finalist, cnt in votes:
            text += f"🥇 {finalist}: {cnt}\n"
    else:
        text += "📭 Нет голосов\n"
    
    cursor.execute('SELECT COUNT(DISTINCT user_id) FROM final_votes WHERE nomination_id = ?', (nomination['id'],))
    voters = cursor.fetchone()[0] or 0
    text += f"\n👥 Голосовало: {voters}"
    
    conn.close()
    text += f"\n📑 {page + 1}/{len(NOMINATIONS)}"
    
    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.add(InlineKeyboardButton("◀️ Назад", callback_data=f"final_results:{page - 1}"))
    if page < len(NOMINATIONS) - 1:
        builder.add(InlineKeyboardButton("Вперед ▶️", callback_data=f"final_results:{page + 1}"))
    builder.adjust(2)
    
    if edit_message_id:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=edit_message_id, text=text, 
                                      reply_markup=builder.as_markup(), parse_mode="HTML")
        except:
            msg = await bot.send_message(chat_id, text, reply_markup=builder.as_markup(), parse_mode="HTML")
            save_message_id(ADMIN_ID, msg.message_id, msg.chat.id)
    else:
        msg = await bot.send_message(chat_id, text, reply_markup=builder.as_markup(), parse_mode="HTML")
        save_message_id(ADMIN_ID, msg.message_id, msg.chat.id)

# ========== ХЕНДЛЕРЫ (сокращённая версия) ==========
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    await delete_old_messages(user_id)
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton("🚀 Финальное голосование", callback_data="start_final_voting"))
    builder.row(
        InlineKeyboardButton("📊 Результаты (админ)", callback_data="admin_results"),
        InlineKeyboardButton("📁 Экспорт (админ)", callback_data="admin_export")
    )
    
    await message.answer(
        "🎉 <b>ФИНАЛЬНОЕ ГОЛОСОВАНИЕ «Люди любят»</b>\n\n🏆 Выберите победителей!",
        reply_markup=builder.as_markup(), parse_mode="HTML"
    )

# ... (все остальные хендлеры как в предыдущем коде - vote:, custom:, skip:, admin команды)

# ========== АДМИН КОМАНДЫ ==========
@dp.message(Command("finalresults"))
async def admin_final_results(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await delete_old_messages(ADMIN_ID)
    await show_final_results_page(message.chat.id, 0)

@dp.message(Command("finalexport"))
async def admin_final_export(message: types.Message):
    if message.from_user.id
