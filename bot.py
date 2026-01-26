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

# ✅ ТОТ ЖЕ ФАЙЛ БД - ВСЕ ДАННЫЕ СОХРАНЯЮТСЯ!
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
    
    # ✅ СТАРЫЕ ТАБЛИЦЫ (СОХРАНЯЮТСЯ!)
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
    logger.info("✅ БД готова (все старые данные сохранены)")

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
            "🎉 <b>Спасибо за голосование!</b>\n\n"
            "✅ Ваши голоса учтены!\n\n"
            "<i>Изменить: <code>/finalrevote</code> | <code>/revote</code></i>",
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

# ========== ХЕНДЛЕРЫ ==========
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    await delete_old_messages(user_id)
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton("🚀 Финальное голосование", callback_data="start_final_voting"))
    
    if user_id == ADMIN_ID:
        builder.row(
            InlineKeyboardButton("📊 Результаты", callback_data="admin_final_results"),
            InlineKeyboardButton("📁 Экспорт", callback_data="admin_final_export")
        )
    
    await message.answer(
        "🎉 <b>ФИНАЛЬНОЕ ГОЛОСОВАНИЕ «Люди любят»</b>\n\n🏆 Выберите победителей!",
        reply_markup=builder.as_markup(), parse_mode="HTML"
    )

@dp.callback_query(F.data == "start_final_voting")
async def start_final_voting(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    await delete_old_messages(user_id)
    
    if not await check_subscription(user_id):
        builder = InlineKeyboardBuilder()
        builder.add(
            InlineKeyboardButton(text="📢 1-й канал", url="https://t.me/new_people32"),
            InlineKeyboardButton(text="📢 2-й канал", url="https://t.me/genesis_bryansk")
        )
        builder.add(InlineKeyboardButton(text="✅ Подписался", callback_data="check_final_sub"))
        builder.adjust(2, 1)
        
        msg = await callback.message.answer(
            "❗️ Подпишись на <b>оба канала</b>:\n• @new_people32\n• @genesis_bryansk",
            reply_markup=builder.as_markup(), parse_mode="HTML"
        )
        save_message_id(user_id, msg.message_id, msg.chat.id)
        await state.set_state(FinalVotingStates.checking_subscription)
        return
    
    conn = get_db_connection()
    cursor = conn.execute('SELECT COUNT(*) FROM final_votes WHERE user_id = ?', (user_id,))
    answered_count = cursor.fetchone()[0]
    conn.close()
    
    await ask_next_nomination(callback.message, state, user_id, answered_count)

@dp.callback_query(F.data == "check_final_sub", FinalVotingStates.checking_subscription)
async def check_final_sub(callback: types.CallbackQuery, state: FSMContext):
    if await check_subscription(callback.from_user.id):
        await callback.message.delete()
        await callback.answer("✅ Отлично!")
        await ask_next_nomination(callback.message, state, callback.from_user.id, 0)
    else:
        await callback.answer("❌ Подпишись на оба!", show_alert=True)

@dp.callback_query(F.data.startswith("vote:"), FinalVotingStates.voting_process)
async def process_finalist_vote(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("✅ Голос учтён!")
    user_id = callback.from_user.id
    
    data = callback.data.split(":")
    nomination_id = data[1]
    finalist_name = data[2]
    
    nomination = next((n for n in NOMINATIONS if n["id"] == nomination_id), None)
    if not nomination:
        return
    
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

@dp.callback_query(F.data.startswith("custom:"), FinalVotingStates.voting_process)
async def request_custom_proposal(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = callback.data.split(":")
    nomination_id = data[1]
    
    nomination = next((n for n in NOMINATIONS if n["id"] == nomination_id), None)
    text = f"<b>{nomination['title']}</b>\n\n✏️ Напишите своего кандидата:"
    
    await callback.message.answer(text, parse_mode="HTML")
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
    
    # ✅ КАСТОМНОЕ ПРЕДЛОЖЕНИЕ
    conn.execute('''
        INSERT INTO custom_proposals (user_id, nomination_id, nomination_title, proposal_text)
        VALUES (?, ?, ?, ?)
    ''', (user_id, nomination_id, nomination_title, message.text))
    
    # ✅ ГОЛОС ЗА "СВОЙ" (6 параметров = 6 ?)
    conn.execute('''
        INSERT OR REPLACE INTO final_votes (user_id, nomination_id, nomination_title, finalist_name, is_custom, custom_text)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, nomination_id, nomination_title, "СВОЙ", 1, message.text))
    
    conn.commit()
    conn.close()
    
    current_index = data.get("current_index", 0)
    await delete_old_messages(user_id)
    await ask_next_nomination(message, state, user_id, current_index + 1)

@dp.callback_query(F.data.startswith("skip:"), FinalVotingStates.voting_process)
async def skip_final_vote(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("➡️ Пропущено")
    user_id = callback.from_user.id
    
    nomination_id = callback.data.split(":")[1]
    nomination = next((n for n in NOMINATIONS if n["id"] == nomination_id), None)
    
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

# ========== ✅ СТАРЫЕ АДМИН КОМАНДЫ (РАБОТАЮТ!) ==========
@dp.message(Command("results"))
async def admin_results(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    await delete_old_messages(ADMIN_ID)
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT answer_text, COUNT(*) as cnt FROM votes WHERE answer_text != "ПРОПУЩЕНО" GROUP BY LOWER(TRIM(answer_text)) ORDER BY cnt DESC LIMIT 10')
    top_votes = cursor.fetchall()
    
    text = "📊 <b>ТОП ПРЕДЛОЖЕНИЙ (1 ФАЗА)</b>\n\n"
    for ans, cnt in top_votes:
        text += f"▫️ {ans}: {cnt}\n"
    
    conn.close()
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("export"))
async def admin_export(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    export_data = {"votes": []}
    
    cursor.execute('SELECT v.nomination_title, v.answer_text, u.username FROM votes v JOIN users u ON v.user_id = u.user_id')
    for row in cursor.fetchall():
        export_data["votes"].append({
            "nomination": row[0],
            "answer": row[1],
            "user": row[2]
        })
    
    filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    filepath = os.path.join(JSON_EXPORT_PATH, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
        
    await message.answer_document(FSInputFile(filepath), caption="📁 Экспорт 1 фазы")
    conn.close()

@dp.message(Command("testvote"))
async def admin_test(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
        
    user_id = message.from_user.id
    
    # ✅ Удаляем ВСЕ данные админа
    conn = get_db_connection()
    conn.execute('DELETE FROM final_votes WHERE user_id = ?', (user_id,))
    conn.execute('DELETE FROM votes WHERE user_id = ?', (user_id,))
    conn.execute('DELETE FROM custom_proposals WHERE user_id = ?', (user_id,))
    conn.execute('UPDATE users SET is_finished = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    # ✅ Очищаем состояние
    await state.clear()
    await delete_old_messages(user_id)
    
    # ✅ НАЧИНАЕМ ГОЛОСОВАНИЕ С НАЧАЛА!
    await message.answer(
        "🔄 <b>✅ Тест активирован!</b>\n\n"
        "🚀 Голосование начато с первой номинации\n"
        "📋 Все данные сброшены",
        parse_mode="HTML"
    )
    
    # ✅ Автоматически проверяем подписку и начинаем
    if await check_subscription(user_id):
        await ask_next_nomination(message, state, user_id, 0)
    else:
        builder = InlineKeyboardBuilder()
        builder.add(
            InlineKeyboardButton("📢 1-й канал", url="https://t.me/new_people32"),
            InlineKeyboardButton("📢 2-й канал", url="https://t.me/genesis_bryansk")
        )
        builder.add(InlineKeyboardButton("✅ Подписался", callback_data="check_final_sub"))
        builder.adjust(2, 1)
        
        await message.answer(
            "❗️ Для теста подпишись на каналы:",
            reply_markup=builder.as_markup(), parse_mode="HTML"
        )
        await state.set_state(FinalVotingStates.checking_subscription)

@dp.message(Command("cleanup"))
async def admin_cleanup(message: types.Message):
    if message.from_user.id != ADMIN_ID: 
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    deleted = cursor.execute('DELETE FROM bot_messages WHERE created_at < datetime("now", "-1 day")').rowcount
    conn.commit()
    
    cursor.execute('SELECT COUNT(*) FROM votes')
    votes_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM final_votes')
    final_votes_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users')
    users_count = cursor.fetchone()[0]
    
    conn.close()
    await message.answer(
        f"🧹 <b>Очистка завершена!</b>\n\n"
        f"🗑️ Удалено сообщений: {deleted}\n"
        f"✅ Голосов 1 фазы: {votes_count}\n"
        f"✅ Финальных голосов: {final_votes_count}\n"
        f"👥 Пользователей: {users_count}",
        parse_mode="HTML"
    )

# ✅ ИСПРАВЛЕННЫЕ СТАРЫЕ КОМАНДЫ - теперь показывают ФИНАЛЬНЫЕ результаты!

@dp.message(Command("results"))
async def admin_results(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    await delete_old_messages(ADMIN_ID)
    await show_final_results_page(message.chat.id, page=0)  # ← Теперь финальные!
    # Было: показ старых votes → Стало: финальные final_votes

@dp.message(Command("export"))
async def admin_export(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # ✅ ТЕПЕРЬ ЭКСПОРТИРУЕТ ФИНАЛЬНЫЕ ГОЛОСА!
    export_data = {"final_votes": []}
    
    cursor.execute('''
        SELECT nomination_title, finalist_name, is_custom, custom_text, username 
        FROM final_votes v 
        LEFT JOIN users u ON v.user_id = u.user_id
    ''')
    for row in cursor.fetchall():
        export_data["final_votes"].append({
            "nomination": row[0],
            "finalist": row[1],
            "is_custom": bool(row[2]),
            "custom_text": row[3],
            "user": row[4]
        })
    
    filename = f"final_export_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    filepath = os.path.join(JSON_EXPORT_PATH, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
        
    await message.answer_document(FSInputFile(filepath), caption="📁 Экспорт финальных голосов")
    conn.close()

# ========== НАВИГАЦИЯ ПО РЕЗУЛЬТАТАМ ==========
@dp.callback_query(F.data.startswith("final_results:"))
async def handle_final_results_nav(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True)
        return
    page = int(callback.data.split(":")[1])
    await show_final_results_page(callback.message.chat.id, page, callback.message.message_id)
    await callback.answer()

# ========== ЗАПУСК ==========
async def main():
    retry_count = 0
    while True:
        try:
            logger.info("🚀 Бот запускается...")
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("✅ Бот запущен")
            await dp.start_polling(bot)
        except Exception as e:
            retry_count += 1
            logger.error(f"❌ Ошибка (попытка {retry_count}): {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
