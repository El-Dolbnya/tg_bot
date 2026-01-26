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
    
    # ✅ КОРОТКИЕ callback_data (max 64 символа)
    for i, finalist in enumerate(nomination["finalists"], 1):
        builder.add(InlineKeyboardButton(
            text=f"{i}. {finalist}", 
            callback_data=f"v{nomination['id']}:{i}"
        ))
    
    builder.add(InlineKeyboardButton(text="✏️ Свой", callback_data=f"c{nomination['id']}"))
    builder.add(InlineKeyboardButton(text="➡️ Пропуск", callback_data=f"s{nomination['id']}"))
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
    voters = cursor.fetchone()[0] or 0
    text += f"\n👥 Голосовало: {voters}"
    text += f"\n📑 {page + 1}/10"
    
    conn.close()
    
    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.add(InlineKeyboardButton("◀️ Назад", callback_data=f"fr:{page - 1}"))
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
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    await delete_old_messages(user_id)
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton("🚀 Начать голосование", callback_data="start_voting"))
    
    if user_id == ADMIN_ID:
        builder.row(
            InlineKeyboardButton("📊 Результаты", callback_data="final_results"),
            InlineKeyboardButton("📁 Экспорт", callback_data="admin_export")
        )
    
    await message.answer(
        "🎉 <b>ФИНАЛЬНОЕ ГОЛОСОВАНИЕ «Люди любят»</b>\n\n🏆 Выберите победителей!",
        reply_markup=builder.as_markup(), parse_mode="HTML"
    )

@dp.callback_query(F.data == "start_voting")
async def start_final_voting(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    await delete_old_messages(user_id)
    
    if not await check_subscription(user_id):
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton("📢 @new_people32", url="https://t.me/new_people32"),
            InlineKeyboardButton("📢 @genesis_bryansk", url="https://t.me/genesis_bryansk")
        )
        builder.add(InlineKeyboardButton("✅ Подписался", callback_data="check_sub"))
        
        await callback.message.answer(
            "❗️ Подпишись на <b>оба канала</b>:",
            reply_markup=builder.as_markup(), parse_mode="HTML"
        )
        await state.set_state(FinalVotingStates.checking_subscription)
        return
    
    conn = get_db_connection()
    cursor = conn.execute('SELECT COUNT(*) FROM final_votes WHERE user_id = ?', (user_id,))
    answered_count = cursor.fetchone()[0]
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
    nomination_id = data[0][1:]  # v1 → 1
    choice_num = int(data[1])     # 1,2,3
    
    nomination = NOMINATIONS[int(nomination_id) - 1]
    finalist_name = nomination["finalists"][choice_num - 1]
    
    conn = get_db_connection()
    conn.execute('''
        INSERT OR REPLACE INTO final_votes (user_id, nomination_id, nomination_title, finalist_name, is_custom)
        VALUES (?, ?, ?, ?, 0)
    ''', (user_id, nomination_id, nomination["title"], finalist_name, 0))
    conn.commit()
    conn.close()
    
    state_data = await state.get_data()
    current_index = state_data.get("current_index", 0)
    await delete_old_messages(user_id)
    await ask_next_nomination(callback.message, state, user_id, current_index + 1)

@dp.callback_query(F.data.startswith("c"))
async def request_custom_proposal(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    nomination_id = callback.data[1:]  # c1 → 1
    
    nomination = NOMINATIONS[int(nomination_id) - 1]
    await callback.message.answer(f"<b>{nomination['title']}</b>\n\n✏️ Напишите своего:", parse_mode="HTML")
    
    await state.update_data(nomination_id=nomination_id, nomination_title=nomination["title"])
    await state.set_state(FinalVotingStates.custom_proposal)

@dp.message(FinalVotingStates.custom_proposal)
async def save_custom_proposal(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if len(message.text) > 200:
        await message.answer("⚠️ До 200 символов.")
        return
    
    data = await state.get_data()
    nomination_id = data.get("nomination_id")
    nomination_title = data.get("nomination_title")
    
    conn = get_db_connection()
    # Кастомное предложение
    conn.execute('''
        INSERT INTO custom_proposals (user_id, nomination_id, nomination_title, proposal_text)
        VALUES (?, ?, ?, ?)
    ''', (user_id, nomination_id, nomination_title, message.text))
    
    # Голос за "СВОЙ"
    conn.execute('''
        INSERT OR REPLACE INTO final_votes (user_id, nomination_id, nomination_title, finalist_name, is_custom, custom_text)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, nomination_id, nomination_title, "СВОЙ", 1, message.text))
    
    conn.commit()
    conn.close()
    
    current_index = data.get("current_index", 0)
    await delete_old_messages(user_id)
    await ask_next_nomination(message, state, user_id, current_index + 1)

@dp.callback_query(F.data.startswith("s"))
async def skip_final_vote(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("➡️ Пропущено")
    user_id = callback.from_user.id
    
    nomination_id = callback.data[1:]  # s1 → 1
    nomination = NOMINATIONS[int(nomination_id) - 1]
    
    conn = get_db_connection()
    conn.execute('''
        INSERT OR REPLACE INTO final_votes (user_id, nomination_id, nomination_title, finalist_name)
        VALUES (?, ?, ?, ?)
    ''', (user_id, nomination_id, nomination["title"], "ПРОПУЩЕНО"))
    conn.commit()
    conn.close()
    
    state_data = await state.get_data()
    current_index = state_data.get("current_index", 0)
    await delete_old_messages(user_id)
    await ask_next_nomination(callback.message, state, user_id, current_index + 1)

# ========== АДМИН КОМАНДЫ ==========
@dp.message(Command("results"))
async def admin_results(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await delete_old_messages(ADMIN_ID)
    await show_final_results_page(message.chat.id, 0)

@dp.message(Command("finalresults"))
async def admin_final_results(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await delete_old_messages(ADMIN_ID)
    await show_final_results_page(message.chat.id, 0)

@dp.callback_query(F.data.startswith("fr:"))
async def handle_final_results_nav(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True)
        return
    page = int(callback.data.split(":")[1])
    await show_final_results_page(callback.message.chat.id, page, callback.message.message_id)
    await callback.answer()

@dp.message(Command("export"))
async def admin_export(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    conn = get_db_connection()
    cursor = conn.cursor()
    
    export_data = {"final_votes": []}
    cursor.execute('''
        SELECT nomination_title, finalist_name, is_custom, custom_text, username 
        FROM final_votes v LEFT JOIN users u ON v.user_id = u.user_id
    ''')
    
    for row in cursor.fetchall():
        export_data["final_votes"].append({
            "nomination": row[0],
            "finalist": row[1],
            "is_custom": bool(row[2]),
            "custom_text": row[3] or "",
            "user": row[4] or "unknown"
        })
    
    filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    filepath = os.path.join(JSON_EXPORT_PATH, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
        
    await message.answer_document(FSInputFile(filepath), caption="📁 Экспорт финала")
    conn.close()

@dp.message(Command("testvote"))
async def admin_test(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    
    user_id = message.from_user.id
    conn = get_db_connection()
    conn.execute('DELETE FROM final_votes WHERE user_id = ?', (user_id,))
    conn.execute('DELETE FROM votes WHERE user_id = ?', (user_id,))
    conn.execute('DELETE FROM custom_proposals WHERE user_id = ?', (user_id,))
    conn.execute('UPDATE users SET is_finished = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    await state.clear()
    await delete_old_messages(user_id)
    
    await message.answer("🔄 <b>✅ Тест активирован!</b>\n🚀 Голосование начато", parse_mode="HTML")
    
    if await check_subscription(user_id):
        await ask_next_nomination(message, state, user_id, 0)
    else:
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton("📢 @new_people32", url="https://t.me/new_people32"),
            InlineKeyboardButton("📢 @genesis_bryansk", url="https://t.me/genesis_bryansk")
        )
        builder.add(InlineKeyboardButton("✅ Подписался", callback_data="check_sub"))
        await message.answer("❗️ Подпишись на каналы:", reply_markup=builder.as_markup(), parse_mode="HTML")
        await state.set_state(FinalVotingStates.checking_subscription)

@dp.message(Command("finalrevote"))
async def user_final_revote(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    conn = get_db_connection()
    conn.execute('DELETE FROM final_votes WHERE user_id = ?', (user_id,))
    conn.execute('DELETE FROM custom_proposals WHERE user_id = ?', (user_id,))
    conn.execute('UPDATE users SET is_finished = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    await delete_old_messages(user_id)
    await state.clear()
    await message.answer("🔄 <b>Переголосование!</b>\n✅ /start", parse_mode="HTML")

@dp.message(Command("cleanup"))
async def admin_cleanup(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    deleted = cursor.execute('DELETE FROM bot_messages WHERE created_at < datetime("now", "-1 day")').rowcount
    conn.commit()
    
    cursor.execute('SELECT COUNT(*) FROM final_votes')
    final_votes = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users')
    users = cursor.fetchone()[0]
    conn.close()
    
    await message.answer(
        f"🧹 <b>Очистка завершена!</b>\n🗑️ Сообщений: {deleted}\n✅ Финальных голосов: {final_votes}\n👥 Пользователей: {users}",
        parse_mode="HTML"
    )

# ========== ЗАПУСК ==========
async def main():
    while True:
        try:
            logger.info("🚀 Бот запускается...")
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("✅ Бот запущен")
            await dp.start_polling(bot)
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
