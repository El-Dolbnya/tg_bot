import asyncio
import json
import sqlite3
from datetime import datetime
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
print(f"BOT_TOKEN exists: {bool(BOT_TOKEN)}")
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
    {
        "id": "1", 
        "title": "1. Общественное пространство года", 
        "finalists": [
            # Существующие номинанты
            "Курган Бессмертия", 
            "Парк-музей имени А. К. Толстого", 
            "Брянская набережная",
            # Новые номинанты
            "Сквер им. А. А. Морозова",
            "Сквер им. Карла Маркса",
            "Парк в ЖК Мегаполис-парк",
            "Парк им. А. С. Пушкина",
            "Парк Поколений",
            "Парк 'Юность'"
        ]
    },
    {
        "id": "2", 
        "title": "2. Уютное место года", 
        "finalists": [
            # Существующие номинанты
            "Щебетун ДК", 
            "Гриль-парк 'Дача'", 
            "Кофейня 'MIKALE'",
            # Новые номинанты
            "Кофейня 'la Луна'",
            "Кофейня 'Место'",
            "Культурный центр 'Пространство'",
            "Кофейня 'На углу'",
            "Кофейня 'CAT'",
            "Бар-ресторан 'Шишка'",
            "Книжная лавка 'Закладка'"
        ]
    },
    {
        "id": "3", 
        "title": "3. Кофейня года", 
        "finalists": [
            # Существующие номинанты
            "Кофейня 'MIKALE'", 
            "Кофейня 'Механика Кофе'", 
            "Кофейня 'Твоя кофейня'",
            # Новые номинанты
            "Кофейня 'Ветка'",
            "Щебетун",
            "Кофейня 'На углу'",
            "Кофейня 'CAT'",
            "Бар-кондитерская 'Воскресный папа'",
            "Кофейня 'Baker street'",
            "Кофейня 'Surf Coffee'"
        ]
    },
    {
        "id": "4", 
        "title": "4. Гастропроект года", 
        "finalists": [
            # Существующие номинанты
            "Фиби", 
            "Итальянцы", 
            "Тёрки",
            # Новые номинанты
            "Шавелла",
            "Форно",
            "Луи",
            "Пиццерия в ЦУМе",
            "Мимино",
            "Дебри",
            "Wine Connection",
            "Kizoku"
        ]
    },
    {
        "id": "5", 
        "title": "5. Ночная локация года", 
        "finalists": [
            # Существующие номинанты
            "ЦЕНЗУРА", 
            "Taco Boys", 
            "ROLLINGS",
            # Новые номинанты
            "FABRIKA",
            "Лисий Дом Культуры",
            "Куйбышев Бар"
        ]
    },
    {
        "id": "6", 
        "title": "6. Открытие года", 
        "finalists": [
            # Существующие номинанты
            "Аэротермы", 
            "Тёрки", 
            "ЧебурекМи",
            # Новые номинанты
            "Форно",
            "Кофейня 'Место'",
            "Лисий Дом Культуры",
            "Книжная лавка 'Закладка'",
            "БлинБери",
            "Бачата Вайб",
            "Детский спортивный центр 'Лайт Атлетика'"
        ]
    },
    {
        "id": "7", 
        "title": "7. Событие года", 
        "finalists": [
            # Существующие номинанты
            "Премия БРЯ", 
            "'Рок-выпускной' от Брянского шума", 
            "Брянский Кофейный Фестиваль",
            # Новые номинанты
            "Открытие и финал 7-8 сезонов программы 'Я в деле'",
            "Концерт 'Ближе к лету' в ЛДК и парке 'Юность'",
            "Забег 'Соловьи cross'"
        ]
    },
    {
        "id": "8", 
        "title": "8. Личность года", 
        "finalists": [
            # Существующие номинанты
            "Роман Формин - фотохудожник, живописец и график, основатель и руководитель 'Брянского музея истории фотографии''", 
            "Мария Охременко - директор частной школы №1", 
            "Сергей Лапенков - поэт, композитор, музыкант, лидер группы 'Лис и Лапландия'",
            # Новые номинанты
            "Александр Богомаз - политик, губернатор Брянской области",
            "Сергей Горелов - руководитель промышленного холдинга «Локомотив-Дизель-Сервис», председатель регионального отделения партии 'Новые люди' в Брянске",
            "Анастасия Кулешова - предприниматель, тренер",
            "Антон Халяев - предприниматель из Брянска, сооснователь, партнёр и бывший партнёр множества проектов общественного питания (Шебетун, Шавелла, Луи и другие)",
            "Михаил Янченко - предприниматель из Брянской области, является руководителем и учредителем 'MIKALE' и нескольких других организаций",
            "Алексей Пуздров - генеральный директор нескольких организаций в Брянской области, связанных с ресторанной деятельностью ('Дача', ROLLINGS и другие)"
        ]
    },
    {
        "id": "9", 
        "title": "9. Сообщество года", 
        "finalists": ["Пространство", "БРЯ", "Новые люди"]
    },
    {
        "id": "10", 
        "title": "10. Инициатива года", 
        "finalists": ["Путеводитель Брянск", "Субботники от Пространства", "Памятник «ЦИРК» у Брянского Цирка"]
    },
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
        except Exception as e:
            logger.error(f"Error checking subscription for channel {channel_id}: {e}")
            return False
    return True

async def update_user_info(user_id: int, username: Optional[str], first_name: Optional[str]):
    """Обновляем информацию о пользователе в базе"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name, last_active, is_finished) 
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, 0)
        ''', (user_id, username, first_name))
        conn.commit()
    finally:
        conn.close()

async def ask_next_nomination(message: types.Message, state: FSMContext, user_id: int, current_index: int):
    # Обновляем информацию о пользователе
    if hasattr(message, 'from_user') and message.from_user:
        username = message.from_user.username
        first_name = message.from_user.first_name
        await update_user_info(user_id, username, first_name)
    
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
    
    builder.button(text="✏️ Свой вариант", callback_data=f"c{nomination['id']}")
    builder.button(text="➡️ Пропустить номинацию", callback_data=f"s{nomination['id']}")
    # Вертикальное расположение кнопок - по одной в строке
    builder.adjust(1)
    
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
    result = cursor.fetchone()
    voters = result[0] if result else 0
    
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
            await bot.edit_message_text(
                chat_id=chat_id, 
                message_id=edit_message_id, 
                text=text, 
                reply_markup=builder.as_markup(), 
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error editing message: {e}")
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
    
    msg = await message.answer(
        "🎉 <b>ФИНАЛЬНОЕ ГОЛОСОВАНИЕ «Люди любят»</b>\n\n🏆 Выберите победителей!", 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )
    save_message_id(user_id, msg.message_id, msg.chat.id)

@dp.callback_query(F.data == "start_voting")
async def start_final_voting(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    await delete_old_messages(user_id)
    
    # Обновляем информацию о пользователе
    await update_user_info(user_id, callback.from_user.username, callback.from_user.first_name)
    
    if not await check_subscription(user_id):
        builder = InlineKeyboardBuilder()
        builder.button(text="📢 @new_people32", url="https://t.me/new_people32")
        builder.button(text="📢 @genesis_bryansk", url="https://t.me/genesis_bryansk")
        builder.button(text="✅ Подписался", callback_data="check_sub")
        builder.adjust(2)
        
        msg = await callback.message.answer(
            "❗️ Подпишись на <b>оба канала</b>:",
            reply_markup=builder.as_markup(), 
            parse_mode="HTML"
        )
        save_message_id(user_id, msg.message_id, msg.chat.id)
        await state.set_state(FinalVotingStates.checking_subscription)
        return
    
    # Получаем количество уже отвеченных номинаций
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM final_votes WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    answered_count = result[0] if result else 0
    
    await ask_next_nomination(callback.message, state, user_id, answered_count)

@dp.callback_query(F.data == "check_sub", FinalVotingStates.checking_subscription)
async def check_sub(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    if await check_subscription(callback.from_user.id):
        await delete_old_messages(callback.from_user.id)
        await callback.message.delete()
        await ask_next_nomination(callback.message, state, callback.from_user.id, 0)
    else:
        await callback.answer("❌ Подпишись на оба канала!", show_alert=True)

@dp.callback_query(F.data.startswith("v"))
async def process_finalist_vote(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("✅ Голос учтён!")
    user_id = callback.from_user.id
    
    # Обработка callback_data: v1:1 → nomination_id=1, choice_num=1
    parts = callback.data.split(":")
    if len(parts) != 2:
        return
    
    nomination_id = parts[0][1:]  # Убираем 'v' в начале
    choice_num = int(parts[1])
    
    nomination = NOMINATIONS[int(nomination_id) - 1]
    finalist_name = nomination["finalists"][choice_num - 1]
    
    conn = get_db_connection()
    conn.execute('''
        INSERT OR REPLACE INTO final_votes (user_id, nomination_id, nomination_title, finalist_name, is_custom)
        VALUES (?, ?, ?, ?, 0)
    ''', (user_id, nomination_id, nomination["title"], finalist_name))
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
    await delete_old_messages(callback.from_user.id)
    
    msg = await callback.message.answer(
        f"<b>{nomination['title']}</b>\n\n✏️ Напишите своего финалиста (до 200 символов):", 
        parse_mode="HTML"
    )
    save_message_id(callback.from_user.id, msg.message_id, msg.chat.id)
    
    state_data = await state.get_data()
    await state.update_data(
        nomination_id=nomination_id, 
        nomination_title=nomination["title"],
        current_index=state_data.get("current_index", 0)
    )
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
    conn.execute('''
        INSERT INTO custom_proposals (user_id, nomination_id, nomination_title, proposal_text)
        VALUES (?, ?, ?, ?)
    ''', (user_id, nomination_id, nomination_title, message.text))
    
    conn.execute('''
        INSERT OR REPLACE INTO final_votes (user_id, nomination_id, nomination_title, finalist_name, is_custom, custom_text)
        VALUES (?, ?, ?, ?, 1, ?)
    ''', (user_id, nomination_id, nomination_title, "СВОЙ ВАРИАНТ", message.text))
    
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
@dp.callback_query(F.data == "final_results")
async def show_final_results(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True)
        return
    
    await callback.answer()
    await delete_old_messages(ADMIN_ID)
    await show_final_results_page(callback.message.chat.id, 0)

@dp.callback_query(F.data.startswith("fr:"))
async def handle_final_results_nav(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True)
        return
    
    try:
        page = int(callback.data.split(":")[1])
        await show_final_results_page(
            callback.message.chat.id, 
            page, 
            callback.message.message_id
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in handle_final_results_nav: {e}")

@dp.callback_query(F.data == "admin_export")
async def admin_export_callback(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только админ", show_alert=True)
        return
    
    await callback.answer("Экспорт начат...")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
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
            "custom_text": row[3] or "",
            "user": row[4] or "unknown"
        })
    
    filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    filepath = os.path.join(JSON_EXPORT_PATH, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
        
    await callback.message.answer_document(
        FSInputFile(filepath), 
        caption="📁 Экспорт финального голосования"
    )
    conn.close()

@dp.message(Command("resetall"))
async def admin_reset_all(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('UPDATE users SET is_finished = 0')
    reset_count = cursor.rowcount
    
    cursor.execute('DELETE FROM final_votes')
    deleted_votes = cursor.rowcount
    
    cursor.execute('DELETE FROM custom_proposals')
    deleted_proposals = cursor.rowcount
    
    conn.commit()
    conn.close()
    
    await message.answer(
        f"🔄 <b>ГЛОБАЛЬНЫЙ СБРОС!</b>\n\n"
        f"👥 Пользователей сброшено: <b>{reset_count}</b>\n"
        f"🗑️ Финальных голосов удалено: <b>{deleted_votes}</b>\n"
        f"✏️ Предложений удалено: <b>{deleted_proposals}</b>\n\n"
        f"✅ <i>Все начнут голосование с 1-й номинации!</i>",
        parse_mode="HTML"
    )

@dp.message(Command("results"))
@dp.message(Command("finalresults"))
async def admin_results(message: types.Message):
    if message.from_user.id != ADMIN_ID: 
        return
    await delete_old_messages(ADMIN_ID)
    await show_final_results_page(message.chat.id, 0)

@dp.message(Command("export"))
async def admin_export_command(message: types.Message):
    if message.from_user.id != ADMIN_ID: 
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
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
            "custom_text": row[3] or "",
            "user": row[4] or "unknown"
        })
    
    filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    filepath = os.path.join(JSON_EXPORT_PATH, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
        
    await message.answer_document(
        FSInputFile(filepath), 
        caption="📁 Экспорт финального голосования"
    )
    conn.close()

@dp.message(Command("testvote"))
async def admin_test(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: 
        return
    
    user_id = message.from_user.id
    conn = get_db_connection()
    conn.execute('DELETE FROM final_votes WHERE user_id = ?', (user_id,))
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
        builder.button(text="📢 @new_people32", url="https://t.me/new_people32")
        builder.button(text="📢 @genesis_bryansk", url="https://t.me/genesis_bryansk")
        builder.button(text="✅ Подписался", callback_data="check_sub")
        builder.adjust(2)
        
        msg = await message.answer(
            "❗️ Подпишись на каналы:", 
            reply_markup=builder.as_markup(), 
            parse_mode="HTML"
        )
        save_message_id(user_id, msg.message_id, msg.chat.id)
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
    await message.answer("🔄 <b>Переголосование!</b>\n✅ Нажми /start", parse_mode="HTML")

@dp.message(Command("cleanup"))
async def admin_cleanup(message: types.Message):
    if message.from_user.id != ADMIN_ID: 
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM bot_messages WHERE created_at < datetime("now", "-1 day")')
    deleted = cursor.rowcount
    
    conn.commit()
    
    cursor.execute('SELECT COUNT(*) FROM final_votes')
    result = cursor.fetchone()
    final_votes = result[0] if result else 0
    
    cursor.execute('SELECT COUNT(*) FROM users')
    result = cursor.fetchone()
    users = result[0] if result else 0
    
    conn.close()
    
    await message.answer(
        f"🧹 <b>Очистка завершена!</b>\n\n"
        f"🗑️ Сообщений удалено: {deleted}\n"
        f"✅ Финальных голосов: {final_votes}\n"
        f"👥 Пользователей: {users}",
        parse_mode="HTML"
    )

# ========== ЗАПУСК ==========
async def main():
    logger.info("🚀 Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())