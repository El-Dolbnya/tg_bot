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
from aiogram.types import FSInputFile
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ========== КОНФИГУРАЦИЯ ПУТЕЙ ==========
VOLUME_PATH = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "/data")
DB_PATH = os.path.join(VOLUME_PATH, 'voting.db')
JSON_EXPORT_PATH = os.path.join(VOLUME_PATH, 'exports')
os.makedirs(JSON_EXPORT_PATH, exist_ok=True)

BOT_TOKEN = os.getenv("BOT_TOKEN")

print("=== DEBUG ENV ===")
print(f"BOT_TOKEN length: {len(os.getenv('BOT_TOKEN', 'NOT_FOUND'))}")
print(f"DB_PATH: {DB_PATH}")
print("=== END DEBUG ===")

if not BOT_TOKEN:
    print("CRITICAL: BOT_TOKEN is empty!")
    exit(1)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

# ========== КОНФИГУРАЦИЯ ==========
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1001178736983"))
CHANNEL_ID_2 = int(os.getenv("CHANNEL_ID_2", "-1003633293081"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "1388134102"))

# Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

# ========== НОМИНАЦИИ И ФИНАЛИСТЫ ==========
NOMINATIONS = [
    {"id": "1", "title": "1. Общественное пространство года", "finalists": ["Курган Бессмертия", "Парк-музей имени А. К. Толстого", "Набережная"]},
    {"id": "2", "title": "2. Уютное место года", "finalists": ["Щебетун ДК", "Дача", "MIKALE"]},
    {"id": "3", "title": "3. Кофейня года", "finalists": ["MIKALE", "Механика Кофе", "Твоя кофейня"]},
    {"id": "4", "title": "4. Гастропроект года", "finalists": ["Фиби", "Итальянцы", "Тёрки"]},
    {"id": "5", "title": "5. Ночная локация года", "finalists": ["ЦЕНЗУРА", "Taco Boys", "ROLLINGS"]},
    {"id": "6", "title": "6. Открытие года", "finalists": ["Аэротермы", "Тёрки", "ЧебурекМи"]},
    {"id": "7", "title": "7. Событие года", "finalists": ["Премия БРЯ", "'Рок-выпускной' от Брянского шума", "Брянский Кофейный Фестиваль"]},
    {"id": "8", "title": "8. Личность года", "finalists": ["Роман Формин - фотохудожник, живописец и график, основатель и руководитель 'Брянского музея истории фотографии''", "Мария Охременко - директор частной школы №1", "Сергей Лапенков - поэт, композитор, музыкант, лидер группы 'Лис и Лапландия'"]},
    {"id": "9", "title": "9. Сообщество года", "finalists": ["Пространство", "БРЯ", "Новые люди"]},
    {"id": "10", "title": "10. Инициатива года", "finalists": ["Путеводитель Брянск", "Субботники от Пространства", "Памятник «ЦИРК» у Брянского Цирка"]},
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
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
        last_active DATETIME DEFAULT CURRENT_TIMESTAMP, is_finished BOOLEAN DEFAULT 0
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, nomination_id TEXT,
        nomination_title TEXT, answer_text TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, nomination_id)
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS final_votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, nomination_id TEXT,
        nomination_title TEXT, finalist_name TEXT, is_custom BOOLEAN DEFAULT 0,
        custom_text TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, nomination_id)
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS custom_proposals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, nomination_id TEXT,
        nomination_title TEXT, proposal_text TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS bot_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message_id INTEGER,
        chat_id INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    conn.commit()
    conn.close()
    logger.info("✅ БД готова")

init_db()

# ========== FSM ==========
class FinalVotingStates(StatesGroup):
    checking_subscription = State()
    voting_process = State()
    custom_proposal = State()
    finished = State()

# ========== ФУНКЦИИ ==========
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
            "🎉 <b>Спасибо за голосование!</b>\n\n✅ Ваши голоса учтены!\n\n<i>/finalrevote - изменить</i>",
            parse_mode="HTML"
        )
        await state.set_state(FinalVotingStates.finished)
        return

    nomination = NOMINATIONS[current_index]
    builder = InlineKeyboardBuilder()
    
    for i, finalist in enumerate(nomination["finalists"], 1):
        builder.button(text=f"{i}. {finalist}", callback_data=f"v{nomination['id']}:{i}")
    
    builder.button(text="✏️ Свой", callback_data=f"c{nomination['id']}")
    builder.button(text="➡️ Пропуск", callback_data=f"s{nomination['id']}")
    builder.adjust(2)
    
    text = f"<b>🏆 {nomination['title']}</b>\n\n👥 <b>Выберите финалиста:</b>\n📊 {current_index + 1}/10"
    
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
    
    text =## ✅ **ПОЛНЫЙ РАБОЧИЙ КОД (100% aiogram 3.x)**

```python
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
from aiogram.types import FSInputFile
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ========== КОНФИГУРАЦИЯ ПУТЕЙ ==========
VOLUME_PATH = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "/data")
DB_PATH = os.path.join(VOLUME_PATH, 'voting.db')
JSON_EXPORT_PATH = os.path.join(VOLUME_PATH, 'exports')
os.makedirs(JSON_EXPORT_PATH, exist_ok=True)

BOT_TOKEN = os.getenv("BOT_TOKEN")

print("=== DEBUG ENV ===")
print(f"BOT_TOKEN length: {len(os.getenv('BOT_TOKEN', 'NOT_FOUND'))}")
print(f"DB_PATH: {DB_PATH}")
print("=== END DEBUG ===")

if not BOT_TOKEN:
    print("CRITICAL: BOT_TOKEN is empty!")
    exit(1)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

# ========== КОНФИГУРАЦИЯ ==========
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1001178736983"))
CHANNEL_ID_2 = int(os.getenv("CHANNEL_ID_2", "-1003633293081"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "1388134102"))

# Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

# ========== НОМИНАЦИИ И ФИНАЛИСТЫ ==========
NOMINATIONS = [
    {"id": "1", "title": "1. Общественное пространство года", "finalists": ["Курган Бессмертия", "Парк-музей имени А. К. Толстого", "Набережная"]},
    {"id": "2", "title": "2. Уютное место года", "finalists": ["Щебетун ДК", "Дача", "MIKALE"]},
    {"id": "3", "title": "3. Кофейня года", "finalists": ["MIKALE", "Механика Кофе", "Твоя кофейня"]},
    {"id": "4", "title": "4. Гастропроект года", "finalists": ["Фиби", "Итальянцы", "Тёрки"]},
    {"id": "5", "title": "5. Ночная локация года", "finalists": ["ЦЕНЗУРА", "Taco Boys", "ROLLINGS"]},
    {"id": "6", "title": "6. Открытие года", "finalists": ["Аэротермы", "Тёрки", "ЧебурекМи"]},
    {"id": "7", "title": "7. Событие года", "finalists": ["Премия БРЯ", "'Рок-выпускной' от Брянского шума", "Брянский Кофейный Фестиваль"]},
    {"id": "8", "title": "8. Личность года", "finalists": ["Роман Формин - фотохудожник, живописец и график, основатель и руководитель 'Брянского музея истории фотографии''", "Мария Охременко - директор частной школы №1", "Сергей Лапенков - поэт, композитор, музыкант, лидер группы 'Лис и Лапландия'"]},
    {"id": "9", "title": "9. Сообщество года", "finalists": ["Пространство", "БРЯ", "Новые люди"]},
    {"id": "10", "title": "10. Инициатива года", "finalists": ["Путеводитель Брянск", "Субботники от Пространства", "Памятник «ЦИРК» у Брянского Цирка"]},
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
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
        last_active DATETIME DEFAULT CURRENT_TIMESTAMP, is_finished BOOLEAN DEFAULT 0
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, nomination_id TEXT,
        nomination_title TEXT, answer_text TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, nomination_id)
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS final_votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, nomination_id TEXT,
        nomination_title TEXT, finalist_name TEXT, is_custom BOOLEAN DEFAULT 0,
        custom_text TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, nomination_id)
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS custom_proposals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, nomination_id TEXT,
        nomination_title TEXT, proposal_text TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS bot_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message_id INTEGER,
        chat_id INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    conn.commit()
    conn.close()
    logger.info("✅ БД готова")

init_db()

# ========== FSM ==========
class FinalVotingStates(StatesGroup):
    checking_subscription = State()
    voting_process = State()
    custom_proposal = State()
    finished = State()

# ========== ФУНКЦИИ ==========
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
            "🎉 <b>Спасибо за голосование!</b>\n\n✅ Ваши голоса учтены!\n\n<i>/finalrevote - изменить</i>",
            parse_mode="HTML"
        )
        await state.set_state(FinalVotingStates.finished)
        return

    nomination = NOMINATIONS[current_index]
    builder = InlineKeyboardBuilder()
    
    for i, finalist in enumerate(nomination["finalists"], 1):
        builder.button(text=f"{i}. {finalist}", callback_data=f"v{nomination['id']}:{i}")
    
    builder.button(text="✏️ Свой", callback_data=f"c{nomination['id']}")
    builder.button(text="➡️ Пропуск", callback_data=f"s{nomination['id']}")
    builder.adjust(2)
    
    text = f"<b>🏆 {nomination['title']}</b>\n\n👥 <b>Выберите финалиста:</b>\n📊 {current_index + 1}/10"
    
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
    voters = cursor.fetchone() or 0
    text += f"\n👥 Голосовало: {voters}"
    text += f"\n📑 {page + 1}/10"
    
    conn.close()
    
    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="◀️ Назад", callback_data=f"fr:{page - 1}")
    if page < len(NOMINATIONS) - 1:
        builder.button(text="Вперед ▶️", callback_data=f"fr:{page + 1}")
    builder.adjust(2)
    
    if edit_message_id:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=edit_message_id, text=text, 
                                      reply_markup=builder.as_markup(), parse_mode="HTML")
        except:
            pass
    else:
        await bot.send_message(chat_id, text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ========== ХЕНДЛЕРЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    await delete_old_messages(user_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Начать голосование", callback_data="start_voting")
    
    if user_id == ADMIN_ID:
        builder.button(text="📊 Результаты", callback_data="final_results")
        builder.button(text="📁 Экспорт", callback_data="admin_export")
        builder.adjust(2)
    
    await message.answer(
        "🎉 <b>ФИНАЛЬНОЕ ГОЛОСОВАНИЕ «Люди любят»</b>\n\n🏆 Выберите победителей!", 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "start_voting")
async def start_final_voting(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    await delete_old_messages(user_id)
    
    if not await check_subscription(user_id):
        builder = InlineKeyboardBuilder()
        builder.button(text="📢 @new_people32", url="https://t.me/new_people32")
        builder.button(text="📢 @genesis_bryansk", url="https://t.me/genesis_bryansk")
        builder.button(text="✅ Подписался", callback_data="check_sub")
        builder.adjust(2)
        
        await callback.message.answer(
            "❗️ Подпишись на <b>оба канала</b>:",
            reply_markup=builder.as_markup(), parse_mode="HTML"
        )
        await state.set_state(FinalVotingStates.checking_subscription)
        return
    
    conn = get_db_connection()
    cursor = conn.execute('SELECT COUNT(*) FROM final_votes WHERE user_id = ?', (user_id,))
    answered_count = cursor.fetchone()
    conn.close()
    
    await ask_next_nomination(callback.message, state, user_id, answered_count)

@dp.callback_query(F.data == "check_sub", FinalVotingStates.checking_subscription)
async def check_sub(callback: types.CallbackQuery, state: FSMContext):
    if await check_subscription(callback.from_user.id):
        await callback.message.delete()
        await callback.answer("✅ Отлично!")
        await ask_next_nomination(callback.message, state, callback.from_user.id, 0)
    else:
        await callback.answer("❌ Подпишись на оба!", show_alert=True)

@dp.callback_query(F.data.startswith("v"))
async def process_finalist_vote(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("✅ Голос учтён!")
    user_id = callback.from_user.id
    
    data = callback.data.split(":")
    nomination_id = data[1:]  # v1 → 1
    choice_num = int(d
